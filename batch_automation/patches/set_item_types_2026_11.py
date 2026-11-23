"""Item type for batch items that have none, so their Batch Naming Rules apply.

Same rules as the backfill tested on erptest (2026-11-23):

- item group FABRIC... / COATED FABRIC...: "Collar" if the item name has COLLAR (and not
  CUFF), "Cuff" if it has CUFF (and not COLLAR), otherwise "Fabric". Names with both words
  are left blank for a person to set. Checked against existing items: 98% of Collar items
  and 99% of Cuff items carry the word in their name, Fabric items almost never do.
- item group CHEM... -> "Chemicals", DYES... -> "Dyes".

Only batch-tracked, enabled items whose type is empty are touched; a type that is already
set is never changed. The column is written directly, as in set_yarn_item_type, so items
that fail unrelated validation on save are not skipped.
"""
import frappe

FABRIC = """has_batch_no = 1 AND disabled = 0 AND IFNULL(custom_item_type, '') = ''
	AND (item_group LIKE 'FABRIC%%' OR item_group LIKE 'COATED FABRIC%%')"""
OTHER = "has_batch_no = 1 AND disabled = 0 AND IFNULL(custom_item_type, '') = ''"

UPDATES = (
	("Collar", f"{FABRIC} AND item_name LIKE '%%COLLAR%%' AND item_name NOT LIKE '%%CUFF%%'"),
	("Cuff", f"{FABRIC} AND item_name LIKE '%%CUFF%%' AND item_name NOT LIKE '%%COLLAR%%'"),
	("Fabric", f"{FABRIC} AND item_name NOT LIKE '%%COLLAR%%' AND item_name NOT LIKE '%%CUFF%%'"),
	("Chemicals", f"{OTHER} AND item_group LIKE 'CHEM%%'"),
	("Dyes", f"{OTHER} AND item_group LIKE 'DYES%%'"),
)


def execute():
	for item_type, where in UPDATES:
		frappe.db.sql(f"UPDATE `tabItem` SET custom_item_type = %s WHERE {where}", (item_type,))
	frappe.db.commit()
	frappe.clear_cache(doctype="Item")
