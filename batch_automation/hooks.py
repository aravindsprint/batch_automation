app_name = "batch_automation"
app_title = "Batch Automation"
app_publisher = "Arkotrix"
app_description = "Auto batch number generation for Purchase Receipt, Subcontracting Receipt, and Stock Entry (Manufacture)"
app_email = "aravindsprint@gmail.com"
app_license = "MIT"

doc_events = {
	"Purchase Receipt": {
		"validate": "batch_automation.batch_naming.resolver.compute_preview",
		"before_submit": "batch_automation.batch_naming.resolver.lock_batches",
	},
	"Subcontracting Receipt": {
		"validate": "batch_automation.batch_naming.resolver.compute_preview",
		"before_submit": "batch_automation.batch_naming.resolver.lock_batches",
	},
	"Stock Entry": {
		"validate": "batch_automation.batch_naming.resolver.compute_preview",
		"before_submit": "batch_automation.batch_naming.resolver.lock_batches",
	},
}

fixtures = [
	"Batch Naming Rule",
	{
		"doctype": "Custom Field",
		"filters": [["module", "=", "Batch Automation"]],
	},
]
