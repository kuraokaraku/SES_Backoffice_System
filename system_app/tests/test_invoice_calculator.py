"""請求計算ロジックのユニットテスト"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
import unittest

from system_app.services.invoice_calculator import (
    _floor_decimal,
    calculate_invoice_lines,
    default_due_date,
)


def _contract(**kwargs):
    defaults = dict(
        unit_price=500000,
        lower_limit_hour=140,
        upper_limit_hours=180,
        excess_unit_price=3000,
        deduction_unit_price=3500,
        settlement_unit_minutes=30,
        travel_expense_included=True,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _assignment(project_name="テスト案件", pk=1):
    return SimpleNamespace(project_name=project_name, id=pk)


class FloorDecimalTest(unittest.TestCase):
    def test_rounds_down(self):
        self.assertEqual(_floor_decimal(Decimal("1.75"), Decimal("0.5")), Decimal("1.5"))

    def test_exact_multiple(self):
        self.assertEqual(_floor_decimal(Decimal("2.0"), Decimal("0.5")), Decimal("2.0"))

    def test_truncates_to_zero(self):
        self.assertEqual(_floor_decimal(Decimal("0.25"), Decimal("0.5")), Decimal("0.0"))

    def test_step_zero_returns_value(self):
        self.assertEqual(_floor_decimal(Decimal("1.75"), Decimal("0")), Decimal("1.75"))


class CalculateInvoiceLinesTest(unittest.TestCase):
    def setUp(self):
        self.a = _assignment()
        self.c = _contract()

    # --- 基本行 ---

    def test_within_range_only_basic_line(self):
        lines = calculate_invoice_lines(self.a, self.c, "202601", Decimal("160"), Decimal("0"))
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["kind"], "basic")
        self.assertEqual(lines[0]["amount"], Decimal("500000"))

    def test_basic_line_item_name_contains_billing_ym(self):
        lines = calculate_invoice_lines(self.a, self.c, "202601", Decimal("160"), Decimal("0"))
        self.assertIn("202601", lines[0]["item_name"])

    # --- 超過精算 ---

    def test_excess_line_added_over_upper(self):
        lines = calculate_invoice_lines(self.a, self.c, "202601", Decimal("182"), Decimal("0"))
        kinds = [l["kind"] for l in lines]
        self.assertIn("excess", kinds)

    def test_excess_amount_correct(self):
        # 182 - 180 = 2.0h → 2.0 × 3000 = 6000
        lines = calculate_invoice_lines(self.a, self.c, "202601", Decimal("182"), Decimal("0"))
        excess = next(l for l in lines if l["kind"] == "excess")
        self.assertEqual(excess["quantity"], Decimal("2.0"))
        self.assertEqual(excess["amount"], Decimal("6000"))

    def test_excess_rounded_down_by_settlement_unit(self):
        # 181.25h → excess=1.25h, step=0.5h → floor to 1.0h → 3000円
        lines = calculate_invoice_lines(self.a, self.c, "202601", Decimal("181.25"), Decimal("0"))
        excess = next(l for l in lines if l["kind"] == "excess")
        self.assertEqual(excess["quantity"], Decimal("1.0"))
        self.assertEqual(excess["amount"], Decimal("3000"))

    def test_no_excess_at_exact_upper(self):
        lines = calculate_invoice_lines(self.a, self.c, "202601", Decimal("180"), Decimal("0"))
        kinds = [l["kind"] for l in lines]
        self.assertNotIn("excess", kinds)

    # --- 控除精算 ---

    def test_deduction_line_added_under_lower(self):
        lines = calculate_invoice_lines(self.a, self.c, "202601", Decimal("138"), Decimal("0"))
        kinds = [l["kind"] for l in lines]
        self.assertIn("deduction", kinds)

    def test_deduction_amount_is_negative(self):
        lines = calculate_invoice_lines(self.a, self.c, "202601", Decimal("138"), Decimal("0"))
        ded = next(l for l in lines if l["kind"] == "deduction")
        self.assertLess(ded["amount"], 0)

    def test_deduction_rounded_down_by_settlement_unit(self):
        # 140 - 138.75 = 1.25h → floor to 1.0h → 3500円
        lines = calculate_invoice_lines(self.a, self.c, "202601", Decimal("138.75"), Decimal("0"))
        ded = next(l for l in lines if l["kind"] == "deduction")
        self.assertEqual(ded["quantity"], Decimal("1.0"))

    def test_no_deduction_at_exact_lower(self):
        lines = calculate_invoice_lines(self.a, self.c, "202601", Decimal("140"), Decimal("0"))
        kinds = [l["kind"] for l in lines]
        self.assertNotIn("deduction", kinds)

    # --- 交通費 ---

    def test_travel_excluded_when_included_in_contract(self):
        lines = calculate_invoice_lines(self.a, self.c, "202601", Decimal("160"), Decimal("10000"))
        kinds = [l["kind"] for l in lines]
        self.assertNotIn("expense", kinds)

    def test_travel_line_added_when_not_included(self):
        c = _contract(travel_expense_included=False)
        lines = calculate_invoice_lines(self.a, c, "202601", Decimal("160"), Decimal("10000"))
        expense = next(l for l in lines if l["kind"] == "expense")
        self.assertEqual(expense["amount"], Decimal("10000"))

    def test_no_travel_line_when_amount_zero(self):
        c = _contract(travel_expense_included=False)
        lines = calculate_invoice_lines(self.a, c, "202601", Decimal("160"), Decimal("0"))
        kinds = [l["kind"] for l in lines]
        self.assertNotIn("expense", kinds)


class DefaultDueDateTest(unittest.TestCase):
    def test_with_terms_40(self):
        # 202601 → 翌月2026-02-01 + 40日 = 2026-03-13
        self.assertEqual(default_due_date("202601", 40), date(2026, 3, 13))

    def test_with_terms_30(self):
        # 202601 → 翌月2026-02-01 + 30日 = 2026-03-03
        self.assertEqual(default_due_date("202601", 30), date(2026, 3, 3))

    def test_without_terms_end_of_next_month(self):
        # 202601 → 翌月末 = 2026-02-28
        self.assertEqual(default_due_date("202601"), date(2026, 2, 28))

    def test_december_without_terms(self):
        # 202512 → 翌月末 = 2026-01-31
        self.assertEqual(default_due_date("202512"), date(2026, 1, 31))

    def test_december_with_terms(self):
        # 202512 → 2026-01-01 + 30日 = 2026-01-31
        self.assertEqual(default_due_date("202512", 30), date(2026, 1, 31))
