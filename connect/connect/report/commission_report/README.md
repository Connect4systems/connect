# Commission Report

Standard Script Report for ERPNext, based on Free Commission Report.A. The original
report is untouched. Existing custom columns are included when present and readable
on the installed site. Report roles are copied from the original report.

The report returns one row per submitted Sales Invoice item. Required filters are
company and invoice posting-date range; optional filters are customer, item, sales
partner, and exclusion of payment method `بدل صيانة` (enabled by default).
The default date range is the current month through today.

## Valuation

The report uses these sources in order, matching transaction item IDs and item code:

1. The invoice item's `dn_detail` → Delivery Note Item `incoming_rate`.
2. Delivery Note items linked back through `si_detail` to this invoice item.
3. Delivery Note items linked through `so_detail` to the same Sales Order item.
   Multiple deliveries use the absolute stock-quantity-weighted incoming rate.
   This order-level average is an estimate for the invoice, not exact stock allocation.
   Return deliveries are excluded from this order-level average.
4. Sales Order Item `valuation_rate`, explicitly labelled as an estimate.

Only submitted source documents in the selected company, dated on or before the
report end date, and readable by the current user are eligible. Source child field
permissions are checked too. Delivery Notes before the start date are eligible.
Delivery Notes after an invoice but before the report end date can be included;
this report is not an immutable valuation snapshot at invoice posting time.

Valuation Rate is in company currency per **stock UOM**. Total Valuation is this
rate multiplied by the **invoice item's stock quantity**, retaining the sign for
returns. Invoice selling amounts retain invoice currency. Zero stored rates remain
zero; missing/inaccessible rates stay blank and show `Not Available`. This report
does not use current Bin rates, recompute stock-ledger costs, or roll up bundle
component costs. An invoice with no eligible Delivery Note or Sales Order source
therefore has no valuation, including a standalone stock-updating invoice.

Invoice-level totals and commission repeat per item, matching the original report.
Automatic totals are disabled to avoid summing repeated invoice totals.

## Deployment and validation

Deploy the updated connect app to your ERPNext bench, then run there:

```sh
bench --site <your-site-name> migrate
bench --site <your-site-name> clear-cache
```

Open **Commission Report**, or `/app/query-report/Commission%20Report`.
Use the actual bench site name; the public domain is not always the site name.

Local tests (no Frappe installation needed):

```sh
python -m unittest discover -s tests -v
```

Before using this for commission decisions, validate on the target ERPNext site
against an invoice linked to a Delivery Note, an order-only invoice, partial
deliveries at different costs, a return, and a different selling/stock UOM.
Local tests validate cost selection and mocked permission boundaries; they do not
replace a live ERPNext database and UI test.

Source field references:
- https://github.com/frappe/erpnext/blob/version-15/erpnext/stock/doctype/delivery_note_item/delivery_note_item.json
- https://github.com/frappe/erpnext/blob/version-15/erpnext/selling/doctype/sales_order_item/sales_order_item.json
