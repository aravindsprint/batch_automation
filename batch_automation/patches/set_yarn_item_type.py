"""Item type "Yarn" for every yarn item, so the "Yarn Purchase" Batch Naming Rule applies.

The rule matches Item.custom_item_type = "Yarn", but that Select had no "Yarn" option and none
of the 1,178 yarn items (item group YARN…) had a type, so a yarn Purchase Receipt never got an
automatic batch name: every batch was typed by hand.

This adds "Yarn" to the field's options and sets it on yarn items whose type is empty. It writes
the column directly: 16 yarn items on erptest can't be saved (missing / short HSN code, a zero
UOM conversion factor) and would otherwise be left out. Items that already have a type keep it.
"""
import frappe

FIELD = "Item-custom_item_type"


def execute():
    if not frappe.db.exists("Custom Field", FIELD):
        return
    cf = frappe.get_doc("Custom Field", FIELD)
    options = (cf.options or "").split("\n")
    if "Yarn" not in options:
        cf.options = (cf.options or "").rstrip("\n") + "\nYarn"
        cf.save()

    frappe.db.sql("""UPDATE `tabItem` SET custom_item_type = 'Yarn'
                     WHERE item_group LIKE 'YARN%%' AND IFNULL(custom_item_type, '') = ''""")
    frappe.db.commit()
    frappe.clear_cache(doctype="Item")
    print(frappe.db.count("Item", {"item_group": ["like", "YARN%"], "custom_item_type": "Yarn"}), "yarn items set to Yarn")
