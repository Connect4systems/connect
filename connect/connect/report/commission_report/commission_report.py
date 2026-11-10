# Copyright (c) 2026, connect and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model import get_permitted_fields
from frappe.utils import getdate

from .valuation import build_indexes, get_valuation


PAYMENT_FIELD = 'طريقة_الدفع'
INVOICE_FIELDS = ['name', 'docstatus', 'customer', 'posting_date', PAYMENT_FIELD,
                  'status', 'customer_group', 'grand_total', 'net_total']
DISPLAY_FIELDS = [(field, 'Sales Invoice') for field in INVOICE_FIELDS] + [
    (field, 'Sales Invoice Item') for field in [
        'item_code', 'item_name', 'item_group', 'brand', 'qty', 'rate', 'amount',
        'discount_percentage', 'crate', 'camount'
    ]
] + [('commission_amount', 'Sales Invoice'), ('base_price_list_rate', 'Sales Invoice Item'),
     ('sales_partner', 'Sales Invoice')]


def execute(filters=None):
    filters = frappe._dict(filters or {})
    if not filters.get('company') or not filters.get('from_date') or not filters.get('to_date'):
        frappe.throw(_('Company, From Date and To Date are required.'))
    if getdate(filters.from_date) > getdate(filters.to_date):
        frappe.throw(_('From Date must be on or before To Date.'))
    frappe.has_permission('Sales Invoice', 'read', throw=True)
    permitted = {
        'Sales Invoice': set(get_permitted_fields('Sales Invoice', permission_type='read')),
        'Sales Invoice Item': set(get_permitted_fields('Sales Invoice Item', parenttype='Sales Invoice', permission_type='read')),
    }
    display = [(field, dt) for field, dt in DISPLAY_FIELDS if field in permitted[dt]]
    columns = get_columns(display)
    conditions = {'docstatus': 1, 'company': filters.company,
                  'posting_date': ['between', [filters.from_date, filters.to_date]]}
    if filters.get('exclude_maintenance', 1) and PAYMENT_FIELD in permitted['Sales Invoice']:
        conditions[PAYMENT_FIELD] = ['!=', 'بدل صيانة']
    for field in ('customer', 'sales_partner'):
        if filters.get(field):
            conditions[field] = filters[field]
    invoice_fields = {field for field, dt in display if dt == 'Sales Invoice'} | {'name', 'currency'}
    invoices = frappe.get_list('Sales Invoice', filters=conditions, fields=sorted(invoice_fields),
                              order_by='modified desc', limit_page_length=0)
    if not invoices:
        return columns, []
    item_fields = {field for field, dt in display if dt == 'Sales Invoice Item'} | {
        'name', 'parent', 'idx', 'item_code', 'stock_qty', 'stock_uom', 'uom',
        'sales_order', 'so_detail', 'delivery_note', 'dn_detail', 'base_net_amount'
    }
    if not item_fields.issubset(permitted['Sales Invoice Item']):
        frappe.throw(_('You do not have access to the item fields required by this report.'), frappe.PermissionError)
    # Child reads are bounded by permission-filtered parent invoices.
    items = []
    for names in batches([invoice.name for invoice in invoices]):
        item_filters = {'parent': ['in', names], 'parenttype': 'Sales Invoice', 'parentfield': 'items'}
        if filters.get('item_code'):
            item_filters['item_code'] = filters.item_code
        items.extend(frappe.get_all('Sales Invoice Item', filters=item_filters,
                                    fields=sorted(item_fields), order_by='idx asc'))
    deliveries = get_deliveries(items, filters)
    order_ids = {item.get('so_detail') for item in items} | {row.get('so_detail') for row in deliveries}
    orders = get_source_items('Sales Order', order_ids - {None, ''}, ['name', 'parent', 'item_code', 'valuation_rate'], filters)
    indexes = build_indexes(deliveries, orders)
    by_invoice = {}
    for item in items:
        by_invoice.setdefault(item.parent, []).append(item)
    company_currency = frappe.get_cached_value('Company', filters.company, 'default_currency')
    data = []
    for invoice in invoices:
        for item in by_invoice.get(invoice.name, []):
            row = {field: (invoice if dt == 'Sales Invoice' else item).get(field) for field, dt in display}
            row.update({field: item.get(field) for field in ('stock_qty', 'stock_uom', 'uom', 'sales_order', 'delivery_note')})
            row.update(currency=invoice.currency, company_currency=company_currency)
            row.update(get_valuation(item, indexes))
            row['valuation_source'] = _(row['valuation_source'])
            data.append(row)
    message = _('Valuation Rate is per stock unit in company currency. Total Valuation = stock quantity × valuation rate. Gross Profit = item net sales in company currency − Total Valuation. Sales Order sources are estimates. Missing or inaccessible costs and their gross profit remain blank. Invoice totals repeat on each item row.')
    return columns, data, message


def batches(values, size=500):
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start:start + size]


def get_deliveries(items, filters):
    fields = ['name', 'parent', 'item_code', 'stock_qty', 'incoming_rate', 'so_detail', 'si_detail']
    found = {}
    for source, target in [('dn_detail', 'name'), ('name', 'si_detail'), ('so_detail', 'so_detail')]:
        values = {item.get(source) for item in items} - {None, ''}
        for row in get_source_items('Delivery Note', values, fields, filters, target):
            found[row.name] = row
    return list(found.values())


def get_source_items(doctype, values, fields, filters, match_field='name'):
    if not values or not frappe.has_permission(doctype, 'read'):
        return []
    childtype = doctype + ' Item'
    permitted = set(get_permitted_fields(childtype, parenttype=doctype, permission_type='read'))
    if not set(fields + [match_field]).issubset(permitted):
        return []
    candidates = []
    for batch in batches(values):
        candidates.extend(frappe.get_all(childtype, filters={
            match_field: ['in', batch], 'parenttype': doctype, 'parentfield': 'items'
        }, fields=fields))
    allowed = set()
    for parents in batches({row.parent for row in candidates}):
        conditions = {'name': ['in', parents], 'docstatus': 1, 'company': filters.company}
        date_field = 'posting_date' if doctype == 'Delivery Note' else 'transaction_date'
        conditions[date_field] = ['<=', filters.to_date]
        allowed.update(row.name for row in frappe.get_list(doctype, filters=conditions, fields=['name'], limit_page_length=0))
    return [row for row in candidates if row.parent in allowed]


def get_columns(display):
    columns = []
    for field, doctype in display:
        df = frappe.get_meta(doctype).get_field(field)
        column = {'fieldname': field, 'label': _(df.label if df else field.title()),
                  'fieldtype': df.fieldtype if df else 'Data', 'width': 130}
        if field == 'name':
            column.update(label=_('Sales Invoice'), fieldtype='Link', options='Sales Invoice', width=180)
        elif field == 'docstatus':
            column.update(label=_('Document Status'), fieldtype='Int')
        elif df and df.fieldtype == 'Currency':
            column['options'] = 'company_currency' if field == 'base_price_list_rate' else 'currency'
        elif df and df.options:
            column['options'] = df.options
        columns.append(column)
    for field, label, fieldtype, options in [
        ('uom', 'UOM', 'Link', 'UOM'),
        ('stock_qty', 'Stock Quantity', 'Float', None),
        ('stock_uom', 'Stock UOM', 'Link', 'UOM'),
        ('valuation_rate', 'Valuation Rate', 'Currency', 'company_currency'),
        ('total_valuation', 'Total Valuation', 'Currency', 'company_currency'),
        ('gross_profit', 'Gross Profit', 'Currency', 'company_currency'),
        ('valuation_source', 'Valuation Source', 'Data', None),
        ('valuation_reference', 'Valuation Reference', 'Data', None),
        ('sales_order', 'Sales Order', 'Link', 'Sales Order'),
        ('delivery_note', 'Delivery Note', 'Link', 'Delivery Note'),
        ('currency', 'Invoice Currency', 'Link', 'Currency'),
        ('company_currency', 'Valuation Currency', 'Link', 'Currency'),
    ]:
        columns.append({'fieldname': field, 'label': _(label), 'fieldtype': fieldtype,
                        'options': options, 'width': 180 if field.startswith('valuation_') else 130})
    return columns
