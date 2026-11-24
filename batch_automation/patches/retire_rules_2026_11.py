"""Delete Batch Naming Rules that were removed from the fixture (2026-11-23).

A fixture sync adds and updates records but never deletes them, so rules dropped from
fixtures/batch_naming_rule.json have to be removed here:

- Greige Fabric / Collar / Cuff Inhouse Knitting: knitting manufacture is named by the
  knit app ("{project}/{work order}"), so this app no longer names it.
- Chemical Dyes Purchase: matched item type "Chemical-Dye", which no item uses. Replaced
  by the "Chemicals Purchase" and "Dyes Purchase" rules.
"""
import frappe

RETIRED = (
	"Greige Fabric Inhouse Knitting",
	"Greige Collar Inhouse Knitting",
	"Greige Cuff Inhouse Knitting",
	"Chemical Dyes Purchase",
)


def execute():
	for name in RETIRED:
		if frappe.db.exists("Batch Naming Rule", name):
			frappe.delete_doc("Batch Naming Rule", name, ignore_permissions=True, force=True)
	frappe.db.commit()
