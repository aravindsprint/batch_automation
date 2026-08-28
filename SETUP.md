# Setting up the `batch_automation` app

**This app has been built and validated end-to-end in a real Frappe v15 bench** (fresh site, real MariaDB — not just a syntax check). `bench migrate` completed with no errors, and the resolver's `build_batch_name()` was run against a real `Batch Naming Rule` record pulled from the real database, producing exactly the batch names shown in the design doc's Example column (e.g. `26PTIN123/PSS/9507-C1-D`). Four real bugs were found and fixed in that process — see §5 below.

The one thing this validation *couldn't* cover: the Custom Fields fixture targets ERPNext doctypes (`Purchase Receipt Item`, `Subcontracting Receipt Item`, `Stock Entry Detail`), and the validation environment only had bare Frappe framework installed, not full ERPNext. Those three custom fields — and the `doc_events` hooks actually firing on real Purchase Receipt/Subcontracting Receipt/Stock Entry submissions — still need testing on your ERPNext bench.

## 1. Get this onto your bench

This is already a complete, correctly-structured Frappe app repo (not a partial scaffold you need to merge into `bench new-app` output like before). On your local bench:

```bash
cd ~/webapps/version15/frappe-bench
cp -r /path/to/batch_automation apps/batch_automation
echo "batch_automation" >> sites/apps.txt
./env/bin/pip install -e apps/batch_automation
```

## 2. Install on your local site

```bash
bench --site pranera.com install-app batch_automation
bench --site pranera.com migrate
```

The `Batch Naming Rule` DocType, all 40 rules, and the custom fields will be created automatically via fixtures.

## 3. Test locally

Test one criteria per doctype before touching the rest — a Yarn Purchase Receipt, a Knitting Subcontracting Receipt, a Dyeing Stock Entry — per the rollout plan in the design doc.

## 4. Push and deploy to erp.pranera.in

```bash
cd apps/batch_automation
git init && git add -A && git commit -m "Initial batch automation app"
git remote add origin git@github.com:aravindsprint/batch_automation.git
git push -u origin main
```

Then in the Frappe Cloud dashboard: Bench → Apps → Add App (paste the repo URL) → Deploy. Once deployed, go to the site's Apps tab and install `batch_automation` on erp.pranera.in — this runs `migrate` automatically as part of the deploy.

## 5. Real bugs found by actually building this (not just reviewing it)

- **`process` is a reserved-collision field name.** The `Batch Naming Rule` DocType originally had a field named `process`. Creating a DocType with a field called `process` breaks Frappe's own metadata system — `Meta.process()` is a real method on the class that handles DocType schema loading, and defining a field with that exact name causes it to get shadowed, crashing with `TypeError: 'NoneType' object is not callable` the moment the DocType is installed. Confirmed by direct reproduction and fix. **Renamed to `process_stage` everywhere** (the DocType field, the fixture data, and the two `frappe.get_all(...)` filter dicts in `resolver.py`). This does **not** affect Purchase Order's own `process` field — that's a different DocType and wasn't touched.
- **Fixture files need an explicit `name` key**, even when the DocType uses `autoname: field:criteria`. Frappe's fixture loader checks `doc["name"]` directly rather than deriving it from the autoname field the way a normal `.insert()` does. Both `batch_naming_rule.json` and `custom_field.json` now include an explicit `name` (matching `criteria` for rules, and `<dt>-<fieldname>` — Frappe's real Custom Field naming convention — for custom fields).
- **The DocType folder was missing a nesting level.** Needed `apps/batch_automation/batch_automation/batch_automation/doctype/...` (an extra folder matching the module name in `modules.txt`), not the two-level structure originally built.
- **`hooks.py`, `batch_naming/`, and `fixtures/` were sitting at the repo root** instead of inside the importable inner package — Python would never have found them. Also added the required `app_name`/`app_title`/`app_publisher`/`app_email`/`app_license` fields to `hooks.py`, a `modules.txt`, and a `pyproject.toml`, none of which existed before (needed for the app to install as a proper Python package at all).
- **`frappe.db.get_single_value()` does not apply a Check field's JSON `default`** when the Settings record has never been saved — it returns a type-coerced `0`, indistinguishable from an explicit "disabled". Two follow-up attempts (`is None` check, then `frappe.db.exists("Singles", ...)`) were each tried and each failed under direct testing before landing on a plain SQL query against `tabSingles`, which is the only approach that actually distinguishes "never configured" from "explicitly disabled." See `is_enabled()` in `resolver.py`.

## 6. Batch Automation Settings — global on/off switch

A new Single DocType, **Batch Automation Settings**, with one field: "Enable Auto Batch Creation" (checked by default). `is_enabled()` in `resolver.py` is checked first thing in both `compute_preview` and `lock_batches` — when unchecked, every hook is a no-op on every document, regardless of how the 40 rules are configured. Tested directly against a real database: fresh/never-touched state reads as enabled (matching the checkbox's default), explicitly unchecking it reads as disabled, and re-checking it reads as enabled again.

Find it in the desk UI by searching "Batch Automation Settings".

## 7. Things you still need to fill in / confirm before relying on this

- `resolver.py` has a few `# TODO` markers where I made a reasonable assumption but it depends on your exact BOM/consumption structure — search for `TODO` and review each one against real documents.
- Confirm the `Item Type` and `Purchase Order.process` option lists cover every value used in `fixtures/batch_naming_rule.json`.
- The `Supplier's Batch No` field is added as a plain Data field — decide if it should be mandatory before submit, and adjust the fixture if so.
- Test the three ERPNext-targeted custom fields and the `doc_events` hooks against real Purchase Receipt / Subcontracting Receipt / Stock Entry documents — this is the one piece the sandbox validation couldn't reach.
