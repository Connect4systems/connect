"""Run locally with: python -m unittest discover -s tests -v"""

import importlib
import json
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from connect.connect.report.commission_report.valuation import build_indexes, get_valuation


class ValuationTests(unittest.TestCase):
    def setUp(self):
        self.item = dict(name='SI-ROW', item_code='ITEM', stock_qty=6, qty=2,
                         dn_detail='DN-ROW', so_detail='SO-ROW')
        self.delivery = dict(name='DN-ROW', parent='DN-1', item_code='ITEM',
                             stock_qty=10, incoming_rate=20, so_detail='SO-ROW')
        self.order = dict(name='SO-ROW', parent='SO-1', item_code='ITEM', valuation_rate=15)

    def value(self, deliveries=(), orders=()):
        return get_valuation(self.item, build_indexes(deliveries, orders))

    def test_direct_delivery_wins_and_uses_invoice_stock_quantity(self):
        value = self.value([self.delivery], [self.order])
        self.assertEqual(value['valuation_rate'], 20)
        self.assertEqual(value['total_valuation'], 120)
        self.assertEqual(value['valuation_source'], 'Delivery Note')

    def test_order_estimate_fallback(self):
        value = self.value(orders=[self.order])
        self.assertEqual(value['total_valuation'], 90)
        self.assertEqual(value['valuation_source'], 'Sales Order (Estimate)')

    def test_multiple_partial_deliveries_weighted_without_duplicate_invoice_rows(self):
        self.item['dn_detail'] = None
        other = dict(self.delivery, name='DN-ROW-2', parent='DN-2', stock_qty=30, incoming_rate=40)
        value = self.value([self.delivery, other], [self.order])
        self.assertEqual(value['valuation_rate'], 35)
        self.assertEqual(value['total_valuation'], 210)
        self.assertEqual(value['valuation_reference'], 'DN-1, DN-2')

    def test_reverse_invoice_item_link_has_priority_over_order_average(self):
        self.item['dn_detail'] = None
        reverse = dict(self.delivery, name='DN-ROW-2', parent='DN-2', si_detail='SI-ROW', incoming_rate=30)
        value = self.value([self.delivery, reverse])
        self.assertEqual(value['valuation_rate'], 30)

    def test_repeated_item_code_does_not_match_other_order_row(self):
        delivery = dict(self.delivery, name='UNRELATED', so_detail='OTHER-SO-ROW')
        self.assertIsNone(self.value([delivery])['valuation_rate'])

    def test_wrong_item_on_link_is_rejected(self):
        delivery = dict(self.delivery, item_code='OTHER-ITEM')
        self.assertIsNone(self.value([delivery])['valuation_rate'])

    def test_valid_zero_does_not_fall_back_to_order_estimate(self):
        value = self.value([dict(self.delivery, incoming_rate=0)], [self.order])
        self.assertEqual(value['total_valuation'], 0)
        self.assertEqual(value['valuation_source'], 'Delivery Note')

    def test_missing_cost_stays_blank(self):
        value = self.value()
        self.assertIsNone(value['valuation_rate'])
        self.assertIsNone(value['total_valuation'])
        self.assertEqual(value['valuation_source'], 'Not Available')

    def test_missing_rate_on_one_delivery_does_not_understate_average(self):
        self.item['dn_detail'] = None
        other = dict(self.delivery, name='DN-ROW-2', incoming_rate=None)
        value = self.value([self.delivery, other], [self.order])
        self.assertEqual(value['valuation_source'], 'Sales Order (Estimate)')

    def test_return_has_negative_cost(self):
        self.item['stock_qty'] = -6
        self.assertEqual(self.value([self.delivery])['total_valuation'], -120)

    def test_order_average_excludes_return_deliveries(self):
        self.item['dn_detail'] = None
        returned = dict(self.delivery, name='RETURN', stock_qty=-5, incoming_rate=100)
        self.assertEqual(self.value([self.delivery, returned])['valuation_rate'], 20)

    def test_order_fallback_can_follow_direct_delivery_order_link(self):
        self.item['so_detail'] = None
        value = self.value([dict(self.delivery, incoming_rate=None)], [self.order])
        self.assertEqual(value['valuation_rate'], 15)

    def test_gross_profit_uses_net_company_amount_not_invoice_amount(self):
        self.item.update(amount=10, base_net_amount=300)
        self.assertEqual(self.value([self.delivery])['gross_profit'], 180)

    def test_gross_profit_stays_blank_when_cost_is_missing(self):
        self.item['base_net_amount'] = 300
        self.assertIsNone(self.value()['gross_profit'])

    def test_gross_profit_for_zero_cost_and_zero_sales(self):
        self.item['base_net_amount'] = 0
        self.assertEqual(self.value([self.delivery])['gross_profit'], -120)
        self.item['base_net_amount'] = 300
        self.assertEqual(self.value([dict(self.delivery, incoming_rate=0)])['gross_profit'], 300)

    def test_gross_profit_reverses_on_return(self):
        self.item.update(stock_qty=-6, base_net_amount=-300)
        self.assertEqual(self.value([self.delivery])['gross_profit'], -180)


class AttrDict(dict):
    __getattr__ = dict.get


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The local checkout has no Frappe server. Only its IO boundary is stubbed.
        cls.frappe = ModuleType('frappe')
        cls.frappe._ = lambda value: value
        cls.frappe._dict = AttrDict
        cls.frappe.PermissionError = PermissionError
        model = ModuleType('frappe.model')
        model.get_permitted_fields = Mock()
        utils = ModuleType('frappe.utils')
        from datetime import date
        utils.getdate = lambda value: date.fromisoformat(value)
        with patch.dict(sys.modules, {'frappe': cls.frappe, 'frappe.model': model, 'frappe.utils': utils}):
            cls.report = importlib.import_module('connect.connect.report.commission_report.commission_report')

    def setUp(self):
        self.report.get_permitted_fields.reset_mock(side_effect=True)
        self.frappe.has_permission = Mock(return_value=True)
        self.frappe.get_all = Mock()
        self.frappe.get_list = Mock()
        self.frappe.throw = Mock(side_effect=ValueError)
        self.filters = AttrDict(company='Sky Way', from_date='2026-11-01', to_date='2026-11-30')

    def test_preserves_original_column_order(self):
        path = Path(__file__).resolve().parents[1] / 'connect/connect/report/free_commission_report.a/free_commission_report.a.json'
        original = json.loads(json.loads(path.read_text(encoding='utf-8'))['json'])
        self.assertEqual([list(pair) for pair in self.report.DISPLAY_FIELDS], original['fields'])

    def test_source_costs_require_parent_permissions_and_submitted_same_company(self):
        fields = ['name', 'parent', 'incoming_rate']
        self.report.get_permitted_fields.return_value = fields
        self.frappe.get_all.return_value = [AttrDict(name='A', parent='ALLOWED', incoming_rate=20), AttrDict(name='B', parent='DENIED', incoming_rate=90)]
        self.frappe.get_list.return_value = [AttrDict(name='ALLOWED')]
        rows = self.report.get_source_items('Delivery Note', {'A', 'B'}, fields, self.filters)
        self.assertEqual([row.name for row in rows], ['A'])
        conditions = self.frappe.get_list.call_args.kwargs['filters']
        self.assertEqual(conditions['company'], 'Sky Way')
        self.assertEqual(conditions['docstatus'], 1)
        self.assertEqual(conditions['posting_date'], ['<=', '2026-11-30'])

    def test_no_source_read_permission_means_no_cost_query(self):
        self.frappe.has_permission.return_value = False
        rows = self.report.get_source_items('Delivery Note', {'A'}, ['name'], self.filters)
        self.assertEqual(rows, [])
        self.frappe.get_all.assert_not_called()

    def test_restricted_cost_field_is_not_read(self):
        self.report.get_permitted_fields.return_value = ['name', 'parent']
        rows = self.report.get_source_items('Sales Order', {'A'}, ['name', 'valuation_rate'], self.filters)
        self.assertEqual(rows, [])
        self.frappe.get_all.assert_not_called()

    def test_invalid_date_range_rejected_before_read(self):
        self.filters['from_date'] = '2026-12-01'
        with self.assertRaises(ValueError):
            self.report.execute(self.filters)
        self.frappe.get_list.assert_not_called()

    def test_execute_keeps_one_row_per_item_and_applies_report_filters(self):
        invoice_fields = {field for field, dt in self.report.DISPLAY_FIELDS if dt == 'Sales Invoice'} | {'currency'}
        item_fields = {field for field, dt in self.report.DISPLAY_FIELDS if dt == 'Sales Invoice Item'} | {
            'name', 'parent', 'idx', 'stock_qty', 'stock_uom', 'uom',
            'sales_order', 'so_detail', 'delivery_note', 'dn_detail', 'base_net_amount'
        }
        self.report.get_permitted_fields.side_effect = lambda dt, **kwargs: invoice_fields if dt == 'Sales Invoice' else item_fields
        self.frappe.get_list.return_value = [AttrDict(name='SI-1', currency='USD', grand_total=200)]
        self.frappe.get_all.return_value = [
            AttrDict(name='ROW-1', parent='SI-1', item_code='ITEM', qty=2, stock_qty=6, dn_detail='DN-ROW', base_net_amount=300),
            AttrDict(name='ROW-2', parent='SI-1', item_code='ITEM', qty=1, stock_qty=3, base_net_amount=150)
        ]
        self.frappe.get_cached_value = Mock(return_value='EGP')
        delivery = AttrDict(name='DN-ROW', parent='DN-1', item_code='ITEM', stock_qty=10, incoming_rate=20)
        self.filters['customer'] = 'CUSTOMER-1'
        with patch.object(self.report, 'get_columns', return_value=[]), \
                patch.object(self.report, 'get_deliveries', return_value=[delivery]), \
                patch.object(self.report, 'get_source_items', return_value=[]):
            columns, data, message = self.report.execute(self.filters)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['total_valuation'], 120)
        self.assertIsNone(data[1]['total_valuation'])
        self.assertEqual(data[0]['gross_profit'], 180)
        self.assertIsNone(data[1]['gross_profit'])
        self.assertIn('base_net_amount', self.frappe.get_all.call_args.kwargs['fields'])
        self.assertEqual(data[0]['currency'], 'USD')
        self.assertEqual(data[0]['company_currency'], 'EGP')
        self.assertEqual(data[0]['grand_total'], 200)
        conditions = self.frappe.get_list.call_args.kwargs['filters']
        self.assertEqual(conditions['docstatus'], 1)
        self.assertEqual(conditions['customer'], 'CUSTOMER-1')
        self.assertEqual(conditions[self.report.PAYMENT_FIELD], ['!=', 'بدل صيانة'])
        self.assertEqual(self.frappe.get_list.call_args.kwargs['limit_page_length'], 0)

    def test_columns_distinguish_invoice_and_company_currency(self):
        self.frappe.get_meta = Mock(return_value=Mock(get_field=Mock(return_value=AttrDict(
            label='Amount', fieldtype='Currency'
        ))))
        columns = self.report.get_columns([('amount', 'Sales Invoice Item'), ('base_price_list_rate', 'Sales Invoice Item')])
        by_field = {column['fieldname']: column for column in columns}
        self.assertEqual(by_field['amount']['options'], 'currency')
        self.assertEqual(by_field['base_price_list_rate']['options'], 'company_currency')
        self.assertEqual(by_field['valuation_rate']['options'], 'company_currency')
        self.assertEqual(by_field['total_valuation']['options'], 'company_currency')
        self.assertEqual(by_field['gross_profit']['options'], 'company_currency')
        field_order = [column['fieldname'] for column in columns]
        self.assertEqual(field_order.index('gross_profit'), field_order.index('total_valuation') + 1)

    def test_missing_required_filters_rejected(self):
        with self.assertRaises(ValueError):
            self.report.execute({})
        self.frappe.get_list.assert_not_called()


if __name__ == '__main__':
    unittest.main()
