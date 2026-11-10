// Copyright (c) 2026, connect and contributors
// For license information, please see license.txt

frappe.query_reports["Commission Report"] = {
    filters: [
        {
            fieldname: "company", label: __("Company"), fieldtype: "Link",
            options: "Company", reqd: 1,
            default: frappe.defaults.get_user_default("Company")
        },
        {
            fieldname: "from_date", label: __("From Date"), fieldtype: "Date",
            reqd: 1, default: frappe.datetime.month_start()
        },
        {
            fieldname: "to_date", label: __("To Date"), fieldtype: "Date",
            reqd: 1, default: frappe.datetime.get_today()
        },
        {fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer"},
        {fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item"},
        {fieldname: "sales_partner", label: __("Sales Partner"), fieldtype: "Link", options: "Sales Partner"},
        {fieldname: "exclude_maintenance", label: __("Exclude Maintenance Replacement"), fieldtype: "Check", default: 1}
    ]
};
