"""Cost selection using exact transaction item references, never item code alone."""

from collections import defaultdict


def build_indexes(deliveries, orders):
    by_name, by_invoice, by_order = {}, defaultdict(list), defaultdict(list)
    for row in deliveries:
        by_name[row['name']] = row
        if row.get('si_detail'):
            by_invoice[row['si_detail']].append(row)
        if row.get('so_detail'):
            by_order[row['so_detail']].append(row)
    return by_name, by_invoice, by_order, {row['name']: row for row in orders}


def weighted_rate(rows):
    # A missing rate invalidates the group; zero is a legitimate stored cost.
    if not rows or any(row.get('incoming_rate') is None for row in rows):
        return None
    quantity = sum(abs(row.get('stock_qty') or 0) for row in rows)
    if not quantity:
        return None
    return sum(row['incoming_rate'] * abs(row.get('stock_qty') or 0) for row in rows) / quantity


def get_valuation(item, indexes):
    by_name, by_invoice, by_order, orders = indexes
    direct = by_name.get(item.get('dn_detail'))
    order_id = item.get('so_detail') or (direct or {}).get('so_detail')

    def matches(row):
        return row.get('item_code') == item.get('item_code')

    groups = []
    if direct and matches(direct):
        groups.append(('Delivery Note', [direct]))
    # Reverse links cover Delivery Notes made after a Sales Invoice.
    reverse = [row for row in by_invoice.get(item['name'], []) if matches(row)]
    reverse = [row for row in reverse if ((row.get('stock_qty') or 0) < 0) == ((item.get('stock_qty') or 0) < 0)]
    groups.append(('Delivery Note (Invoice Item)', reverse))
    # Order-level fallback is an estimate, not an allocation to a particular invoice.
    order_rows = [row for row in by_order.get(order_id, []) if matches(row) and (row.get('stock_qty') or 0) > 0]
    groups.append(('Delivery Note (Sales Order Average)', order_rows))
    for source, rows in groups:
        rate = weighted_rate(rows)
        if rate is not None:
            return result(item, rate, source, ', '.join(sorted({row['parent'] for row in rows})))

    order = orders.get(order_id)
    if order and matches(order) and order.get('valuation_rate') is not None:
        return result(item, order['valuation_rate'], 'Sales Order (Estimate)', order['parent'])
    return result(item, None, 'Not Available', '')


def result(item, rate, source, reference):
    total_valuation = None if rate is None else rate * (item.get('stock_qty') or 0)
    net_sales = item.get('base_net_amount')
    return {
        'valuation_rate': rate,
        'total_valuation': total_valuation,
        'gross_profit': None if total_valuation is None or net_sales is None else net_sales - total_valuation,
        'valuation_source': source,
        'valuation_reference': reference,
    }
