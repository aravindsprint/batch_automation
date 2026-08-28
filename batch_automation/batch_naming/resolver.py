"""
Batch naming resolver.

Central logic for:
  - picking the right Batch Naming Rule for a line (item_type + process + mode)
  - resolving every token in that rule's template
  - the two-phase preview / lock flow used by hooks.py

TODOs are left wherever a design decision depends on data we haven't
confirmed against the real system yet (see SETUP.md, section 6).
"""

import frappe
from frappe.utils import cstr


def is_enabled():
	"""
	Global on/off switch, checked first in both hook entry points below.

	Deliberately avoids frappe.db.get_single_value() and frappe.db.exists()
	against "Singles" — both were tried and both failed under direct
	testing: get_single_value() type-coerces a missing Check field to 0
	rather than applying the DocType's default="1", and exists()/get_value()
	against the raw Singles pseudo-table error out (it isn't a normal
	doctype-backed table with a "modified" column). A plain SQL query
	against tabSingles is what actually distinguishes "never configured"
	(no row — treated as enabled, matching the field's declared default)
	from "explicitly set" (row present — respects the real 0/1 value).
	"""
	row = frappe.db.sql(
		"SELECT value FROM tabSingles WHERE doctype=%s AND field=%s",
		("Batch Automation Settings", "enabled"),
	)
	if not row:
		return True
	return bool(int(row[0][0]))

# ---------------------------------------------------------------------------
# Mode + process + item_type resolution
# ---------------------------------------------------------------------------

MODE_BY_DOCTYPE = {
	"Purchase Receipt": "Purchase",
	"Subcontracting Receipt": "Subcontract",
	"Stock Entry": "Inhouse",  # only when purpose == "Manufacture"
}


def strip_doc_prefix(doc_name):
	"""
	'WO/26/9507' -> '9507', 'PO/26/1530' -> '1530'. Confirmed: applies to
	every Work Order-derived AND Purchase Order-derived token used in a
	batch name — only the final segment after the last '/' is kept.
	"""
	if not doc_name:
		return doc_name
	return doc_name.split("/")[-1]


def get_mode(doc):
	if doc.doctype == "Stock Entry":
		if doc.purpose != "Manufacture":
			return None
	return MODE_BY_DOCTYPE.get(doc.doctype)


def get_item_type(item_code):
	return frappe.db.get_value("Item", item_code, "item_type")


def get_process_for_purchase_receipt(pr_item_row, pr_doc):
	# process lives on the Purchase Order, not the Purchase Receipt itself
	po = pr_item_row.get("purchase_order") or pr_doc.get("purchase_order")
	if not po:
		return None
	return frappe.db.get_value("Purchase Order", po, "process")


def get_process_for_subcontracting_receipt(scr_item_row, scr_doc):
	# Confirmed: Subcontracting Order doesn't carry its own process value —
	# fetch it from the linked Purchase Order instead.
	po = scr_item_row.get("purchase_order")
	if not po:
		sco = scr_item_row.get("subcontracting_order")
		if sco:
			po = frappe.db.get_value("Subcontracting Order", sco, "purchase_order")
	if not po:
		return None
	return frappe.db.get_value("Purchase Order", po, "process")


def get_process_for_stock_entry(se_doc):
	# Confirmed: use the last row of the Work Order's Operations table
	# (in practice there is normally only one row).
	if not se_doc.get("work_order"):
		return None
	operations = frappe.get_all(
		"Work Order Operation",
		filters={"parent": se_doc.work_order},
		fields=["operation"],
		order_by="idx asc",
	)
	if not operations:
		return None
	return operations[-1].operation


# ---------------------------------------------------------------------------
# Rule lookup
# ---------------------------------------------------------------------------

def get_rule(item_type, process, mode, origin=None):
	if not (item_type and process and mode):
		return None
	matches = frappe.get_all(
		"Batch Naming Rule",
		filters={"item_type": item_type, "process_stage": process, "mode": mode},
		fields=["name", "origin"],
	)
	if not matches:
		return None
	if len(matches) == 1:
		return frappe.get_cached_doc("Batch Naming Rule", matches[0].name)

	# More than one rule shares the same (item_type, process, mode) —
	# this only happens where the true anchor depends on which reference
	# the traced batch carries (e.g. fabric inspected inhouse, whether
	# dyed inhouse or via subcontract). Disambiguate using origin.
	for m in matches:
		if m.origin == origin:
			return frappe.get_cached_doc("Batch Naming Rule", m.name)

	frappe.throw(
		f"Multiple Batch Naming Rule rows match item_type={item_type}, "
		f"process={process}, mode={mode}, and none has origin='{origin}' "
		f"set to disambiguate. Set the 'origin' field on the correct row."
	)


# ---------------------------------------------------------------------------
# Dyeing reference tracing (the carry-forward mechanism)
# ---------------------------------------------------------------------------

def get_dyeing_refs_from_batch(batch_name):
	"""Read the two traced-reference fields stamped on a Batch record."""
	if not batch_name:
		return None, None
	row = frappe.db.get_value(
		"Batch", batch_name, ["custom_dyeing_work_order", "custom_dyeing_purchase_order"], as_dict=True
	)
	if not row:
		return None, None
	return row.custom_dyeing_work_order, row.custom_dyeing_purchase_order


def resolve_consumed_batch_stock_entry(se_doc, produced_row):
	"""
	Find the batch of raw material consumed on this Stock Entry that
	this produced row's dyeing lineage should trace back through.

	TODO: this picks the first consumed row (s_warehouse set, t_warehouse
	empty) that has a batch with a dyeing reference stamped on it. If a
	Stock Entry consumes multiple batched raw materials, you may need to
	instead match on item_group/item_code family (e.g. only look at rows
	whose item is a "Fabric" item) rather than taking the first match.
	Review against a real multi-input Dyeing/Finishing Stock Entry.
	"""
	for row in se_doc.items:
		if row.s_warehouse and not row.t_warehouse and row.batch_no:
			wo_ref, po_ref = get_dyeing_refs_from_batch(row.batch_no)
			if wo_ref or po_ref:
				return wo_ref, po_ref
	return None, None


def resolve_consumed_batch_subcontracting_receipt(scr_doc, produced_item_row):
	"""
	Find the batch of raw material supplied to the subcontractor for
	this produced item row, resolving through Serial and Batch Bundle
	when the plain batch_no field is empty (confirmed against a live
	Subcontracting Receipt: SCRECT26/15864).
	"""
	for supplied_row in scr_doc.get("supplied_items", []):
		if supplied_row.reference_name != produced_item_row.name:
			continue

		batch_no = supplied_row.get("batch_no")

		if not batch_no and supplied_row.get("serial_and_batch_bundle"):
			bundle = frappe.get_doc("Serial and Batch Bundle", supplied_row.serial_and_batch_bundle)
			batch_entries = [e.batch_no for e in bundle.entries if e.batch_no]
			# TODO: a bundle can list more than one batch. Taking the first
			# is a simplification — confirm whether that's acceptable, or
			# whether the dyeing reference needs to be reconciled across
			# multiple batches in the same bundle.
			if batch_entries:
				batch_no = batch_entries[0]

		if batch_no:
			wo_ref, po_ref = get_dyeing_refs_from_batch(batch_no)
			if wo_ref or po_ref:
				return wo_ref, po_ref

	return None, None


def resolve_dyeing_purchase_order(scr_item_row, scr_doc):
	"""
	Base case for the subcontract-dyed chain: find the Purchase Order
	(linked via the Subcontracting Order) whose process == 'Dyeing'.
	"""
	sco = scr_item_row.get("subcontracting_order")
	if not sco:
		return None
	po = frappe.db.get_value("Subcontracting Order", sco, "purchase_order")
	if not po:
		return None
	process = frappe.db.get_value("Purchase Order", po, "process")
	if process == "Dyeing":
		return po
	return None


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------

def compute_dyeing_trace(doc, item_row):
	"""
	Compute (dyeing_work_order, dyeing_purchase_order) for this row before
	rule lookup, so the result can both disambiguate which rule applies
	(via 'origin') and be reused for token resolution — no need to trace
	twice.
	"""
	if doc.doctype == "Stock Entry":
		process = get_process_for_stock_entry(doc)
		if process == "Dyeing":
			return doc.get("work_order"), None
		return resolve_consumed_batch_stock_entry(doc, item_row)
	elif doc.doctype == "Subcontracting Receipt":
		dyeing_po = resolve_dyeing_purchase_order(item_row, doc)
		if dyeing_po:
			return None, dyeing_po
		return resolve_consumed_batch_subcontracting_receipt(doc, item_row)
	return None, None


def resolve_tokens(doc, item_row, rule, seq_value, dyeing_wo, dyeing_po):
	tokens = {}

	# INDENT — the Project field, wherever it lives on this row/doc
	tokens["INDENT"] = item_row.get("project") or doc.get("project") or ""

	# SUPPLIER CODE — via the linked Purchase Order's supplier
	# TODO: confirm the actual fieldname holding the supplier's short code
	# (placeholder: Supplier.custom_supplier_code)
	po_for_supplier = item_row.get("purchase_order") or doc.get("purchase_order")
	if po_for_supplier:
		supplier = frappe.db.get_value("Purchase Order", po_for_supplier, "supplier")
		if supplier:
			tokens["SUPPLIER_CODE"] = frappe.db.get_value("Supplier", supplier, "custom_supplier_code") or ""

	# SUPPLIER'S BATCH NO — new field entered at receipt
	tokens["SUPPLIERS_BATCH_NO"] = item_row.get("custom_suppliers_batch_no") or ""

	# WORK ORDER NO — Stock Entry's own Work Order
	tokens["WORK_ORDER_NO"] = strip_doc_prefix(doc.get("work_order")) or ""

	# PURCHASE ORDER NO / SUPPLIER PO NO — the linked Purchase Order's own
	# name (confirmed: not the Subcontracting Order's own name)
	po_no = item_row.get("purchase_order")
	if not po_no and item_row.get("subcontracting_order"):
		po_no = frappe.db.get_value("Subcontracting Order", item_row.subcontracting_order, "purchase_order")
	tokens["PURCHASE_ORDER_NO"] = strip_doc_prefix(po_no) or ""
	tokens["SUPPLIER_PO_NO"] = strip_doc_prefix(po_no) or ""

	# DYEING WORK ORDER NO / DYEING PO NO — already traced by the caller
	tokens["DYEING_WORK_ORDER_NO"] = strip_doc_prefix(dyeing_wo) or ""
	tokens["DYEING_PO_NO"] = strip_doc_prefix(dyeing_po) or ""

	# DYEING SUPPLIER CODE — supplier of the traced dyeing Purchase Order
	if dyeing_po:
		dyeing_supplier = frappe.db.get_value("Purchase Order", dyeing_po, "supplier")
		tokens["DYEING_SUPPLIER_CODE"] = (
			frappe.db.get_value("Supplier", dyeing_supplier, "custom_supplier_code") if dyeing_supplier else ""
		) or ""
	else:
		tokens["DYEING_SUPPLIER_CODE"] = ""

	# PRINTING WORK ORDER NO — unlike Dyeing, Printing Inspection runs
	# under the same Work Order as the Printing step itself, so this is
	# just the current Stock Entry's own work_order field — no tracing
	# or propagation needed.
	tokens["PRINTING_WORK_ORDER_NO"] = strip_doc_prefix(doc.get("work_order")) or ""

	# PSS — fixed literal
	tokens["PSS"] = "PSS"

	# SEQ
	tokens["SEQ"] = cstr(seq_value) if seq_value else ""

	return tokens


def row_matches_rule(item_type, process, mode, rule_name):
	"""
	Best-effort check used only for SEQ counting: does this row's
	(item_type, process, mode) resolve to rule_name? Doesn't need full
	origin disambiguation — if rule_name is among the candidates, that's
	enough to count it, since the rules that actually need SEQ never
	collide with the fabric-inspection ambiguity in the first place.
	"""
	if not (item_type and process and mode):
		return False
	names = frappe.get_all(
		"Batch Naming Rule", filters={"item_type": item_type, "process_stage": process, "mode": mode}, pluck="name"
	)
	return rule_name in names


def compute_seq(doc, rule_name, current_row):
	"""Count this row's position among rows on this doc matched to the same rule."""
	count = 0
	for row in doc.items:
		row_item_type = get_item_type(row.item_code)
		# Re-derive the same (item_type, process, mode) match for every row —
		# cheap enough at typical row counts, and keeps this self-contained.
		process = (
			get_process_for_purchase_receipt(row, doc)
			if doc.doctype == "Purchase Receipt"
			else get_process_for_subcontracting_receipt(row, doc)
			if doc.doctype == "Subcontracting Receipt"
			else get_process_for_stock_entry(doc)
		)
		mode = get_mode(doc)
		if row_matches_rule(row_item_type, process, mode, rule_name):
			count += 1
			if row.name == current_row.name:
				return count
	return count


def build_batch_name(template, tokens):
	name = template
	for token, value in tokens.items():
		name = name.replace("{%s}" % token, cstr(value))

	if "{" in name and "}" in name:
		# A token in the template has no resolver yet — fail loudly rather
		# than create a batch with literal "{TOKEN}" text baked into its
		# name.
		frappe.throw(
			f"Batch naming template '{template}' has an unresolved token — "
			f"got '{name}'. This token isn't wired up in resolve_tokens() yet."
		)

	return name


# ---------------------------------------------------------------------------
# Batch creation (idempotent)
# ---------------------------------------------------------------------------

def get_or_create_batch(item_code, batch_id, dyeing_work_order=None, dyeing_purchase_order=None):
	if frappe.db.exists("Batch", batch_id):
		return batch_id

	batch = frappe.get_doc(
		{
			"doctype": "Batch",
			"batch_id": batch_id,
			"item": item_code,
			"custom_dyeing_work_order": dyeing_work_order,
			"custom_dyeing_purchase_order": dyeing_purchase_order,
		}
	)
	batch.insert(ignore_permissions=True)
	return batch.name


# ---------------------------------------------------------------------------
# Row targeting per doctype
# ---------------------------------------------------------------------------

def eligible_rows(doc):
	if doc.doctype == "Stock Entry":
		# Confirmed: only finished-item and scrap-item rows are batch
		# targets; plain consumed inputs are skipped.
		return [r for r in doc.items if r.is_finished_item or r.is_scrap_item]
	# Purchase Receipt / Subcontracting Receipt: every item row is a
	# potential batch target (has_batch_no is checked by the caller).
	return list(doc.items)


# ---------------------------------------------------------------------------
# Public hook entry points (see hooks.py)
# ---------------------------------------------------------------------------

def compute_preview(doc, method=None):
	"""validate hook — writes the draft preview field, creates nothing."""
	if not is_enabled():
		return
	mode = get_mode(doc)
	if not mode:
		return

	for row in eligible_rows(doc):
		if not frappe.db.get_value("Item", row.item_code, "has_batch_no"):
			continue

		item_type = get_item_type(row.item_code)
		process = (
			get_process_for_purchase_receipt(row, doc)
			if doc.doctype == "Purchase Receipt"
			else get_process_for_subcontracting_receipt(row, doc)
			if doc.doctype == "Subcontracting Receipt"
			else get_process_for_stock_entry(doc)
		)
		dyeing_wo, dyeing_po = compute_dyeing_trace(doc, row)
		origin = "Work Order" if dyeing_wo else "Purchase Order" if dyeing_po else None
		rule = get_rule(item_type, process, mode, origin)
		if not rule:
			continue

		seq = compute_seq(doc, rule.name, row) if "{SEQ}" in rule.template else None
		tokens = resolve_tokens(doc, row, rule, seq, dyeing_wo, dyeing_po)
		row.custom_computed_batch_no = build_batch_name(rule.template, tokens)


def lock_batches(doc, method=None):
	"""before_submit hook — recomputes, creates/reuses the Batch, sets batch_no."""
	if not is_enabled():
		return
	mode = get_mode(doc)
	if not mode:
		return

	for row in eligible_rows(doc):
		if not frappe.db.get_value("Item", row.item_code, "has_batch_no"):
			continue
		if row.get("batch_no"):
			continue  # already set (manual override) — don't touch it

		item_type = get_item_type(row.item_code)
		process = (
			get_process_for_purchase_receipt(row, doc)
			if doc.doctype == "Purchase Receipt"
			else get_process_for_subcontracting_receipt(row, doc)
			if doc.doctype == "Subcontracting Receipt"
			else get_process_for_stock_entry(doc)
		)
		dyeing_wo, dyeing_po = compute_dyeing_trace(doc, row)
		origin = "Work Order" if dyeing_wo else "Purchase Order" if dyeing_po else None
		rule = get_rule(item_type, process, mode, origin)
		if not rule:
			continue

		seq = compute_seq(doc, rule.name, row) if "{SEQ}" in rule.template else None
		tokens = resolve_tokens(doc, row, rule, seq, dyeing_wo, dyeing_po)
		batch_id = build_batch_name(rule.template, tokens)

		row.batch_no = get_or_create_batch(
			row.item_code, batch_id, dyeing_work_order=dyeing_wo, dyeing_purchase_order=dyeing_po
		)
