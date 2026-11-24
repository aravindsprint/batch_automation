"""Delete subcontract finishing / dryer rules replaced on 2026-11-23.

Subcontract finishing (STENTER and its variants) and DRYER job work are now named after
the job work's own Purchase Order ("{project}/{supplier}/{PO}-F", collars "-C1-F",
"-C1-DR"), confirmed by Aravind. The old rules were named after the dyeing order, which
could only be found for fabric dyed in-house and stamped by this app, so almost every
stenter receipt got no batch. The dyeing reference is still stamped on the new batch.

Fabric: "Dyeing Inhouse Finishing Subcontract" is replaced by "Finished Fabric Subcontract".
Collar / Cuff: one rule each now, so the "(Inhouse Dyed)" variants go.
"""
import frappe

RETIRED = (
	"Dyeing Inhouse Finishing Subcontract",
	"Finished Collar Subcontracting (Inhouse Dyed)",
	"Finished Cuff Subcontracting (Inhouse Dyed)",
	"Dried/Squeezed Collar Subcontracting (Inhouse Dyed)",
	"Dried/Squeezed Cuff Subcontracting (Inhouse Dyed)",
)


def execute():
	for name in RETIRED:
		if frappe.db.exists("Batch Naming Rule", name):
			frappe.delete_doc("Batch Naming Rule", name, ignore_permissions=True, force=True)
	frappe.db.commit()
