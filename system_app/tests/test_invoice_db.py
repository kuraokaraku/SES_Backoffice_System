"""DB を使う請求書サービスのテスト（採番・合計再計算）"""
from decimal import Decimal

from django.test import TestCase

from system_app.models import Assignment, ContactEntity, Invoice, InvoiceLine
from system_app.services.invoice_calculator import (
    generate_invoice_number,
    recalculate_totals,
)


def _make_assignment():
    """テスト用 Assignment を返す。Assignment には 4 つの ContactEntity が必要。"""
    worker = ContactEntity.objects.create(kind="PERSON", name="テスト 太郎")
    sales = ContactEntity.objects.create(kind="COMPANY", name="営業会社")
    upstream = ContactEntity.objects.create(kind="COMPANY", name="上位会社")
    downstream = ContactEntity.objects.create(kind="COMPANY", name="下位会社")
    return Assignment.objects.create(
        worker_entity=worker,
        sales_owner_entity=sales,
        upstream_entity=upstream,
        downstream_entity=downstream,
        project_name="テスト案件",
    )


class GenerateInvoiceNumberTest(TestCase):
    def setUp(self):
        self.assignment = _make_assignment()

    def _make_invoice(self, billing_ym, number):
        return Invoice.objects.create(
            assignment=self.assignment,
            billing_ym=billing_ym,
            invoice_number=number,
        )

    def test_first_invoice_gets_suffix_A(self):
        self.assertEqual(generate_invoice_number("202601"), "202601A")

    def test_second_invoice_gets_suffix_B(self):
        self._make_invoice("202601", "202601A")
        self.assertEqual(generate_invoice_number("202601"), "202601B")

    def test_third_invoice_gets_suffix_C(self):
        self._make_invoice("202601", "202601A")
        # 別の assignment で2本目を作る（同月カウント用）
        a2 = _make_assignment()
        Invoice.objects.create(assignment=a2, billing_ym="202601", invoice_number="202601B")
        self.assertEqual(generate_invoice_number("202601"), "202601C")

    def test_different_month_resets_to_A(self):
        self._make_invoice("202601", "202601A")
        self.assertEqual(generate_invoice_number("202602"), "202602A")

    def test_exclude_self_when_editing(self):
        # 自分自身を除外してカウント → まだ0本扱い → "A" を返す
        invoice = self._make_invoice("202601", "202601A")
        self.assertEqual(
            generate_invoice_number("202601", exclude_invoice_id=invoice.id),
            "202601A",
        )


class RecalculateTotalsTest(TestCase):
    def setUp(self):
        assignment = _make_assignment()
        self.invoice = Invoice.objects.create(
            assignment=assignment,
            billing_ym="202601",
            tax_rate=Decimal("0.10"),
        )

    def _add_line(self, kind, amount, order):
        InvoiceLine.objects.create(
            invoice=self.invoice,
            kind=kind,
            display_order=order,
            item_name=f"{kind} テスト",
            quantity=Decimal("1"),
            unit_price=abs(amount),
            amount=amount,
        )

    def test_basic_subtotal_and_tax(self):
        self._add_line("basic", Decimal("500000"), 10)
        recalculate_totals(self.invoice)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.subtotal_amount, Decimal("500000"))
        self.assertEqual(self.invoice.tax_amount, Decimal("50000"))
        self.assertEqual(self.invoice.total_amount, Decimal("550000"))

    def test_excess_added_to_subtotal(self):
        self._add_line("basic", Decimal("500000"), 10)
        self._add_line("excess", Decimal("6000"), 20)
        recalculate_totals(self.invoice)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.subtotal_amount, Decimal("506000"))
        self.assertEqual(self.invoice.tax_amount, Decimal("50600"))

    def test_deduction_reduces_subtotal(self):
        self._add_line("basic", Decimal("500000"), 10)
        self._add_line("deduction", Decimal("-7000"), 30)
        recalculate_totals(self.invoice)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.subtotal_amount, Decimal("493000"))
        self.assertEqual(self.invoice.tax_amount, Decimal("49300"))

    def test_expense_not_taxed_but_included_in_total(self):
        self._add_line("basic", Decimal("500000"), 10)
        self._add_line("expense", Decimal("10000"), 40)
        recalculate_totals(self.invoice)
        self.invoice.refresh_from_db()
        # 交通費は課税対象外なので小計・税に含まれない
        self.assertEqual(self.invoice.subtotal_amount, Decimal("500000"))
        self.assertEqual(self.invoice.tax_amount, Decimal("50000"))
        # 合計には交通費を加算
        self.assertEqual(self.invoice.total_amount, Decimal("560000"))

    def test_tax_rounds_down(self):
        # 501 × 0.10 = 50.1 → 切り捨て → 50
        self._add_line("basic", Decimal("501"), 10)
        recalculate_totals(self.invoice)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.tax_amount, Decimal("50"))
