"""請求書生成サービス（上位向け売上請求）"""
from datetime import date
from decimal import Decimal

from django.db import transaction

from system_app.models import Assignment, Invoice, InvoiceLine
from system_app.services.contracts import get_active_contract
from system_app.services.invoice_calculator import (
    calculate_invoice_lines,
    default_due_date,
    generate_invoice_number,
    recalculate_totals,
)


@transaction.atomic
def create_or_update_invoice_from_parsed(
    assignment_id,
    parsed,
    fallback_billing_ym=None,
    fallback_actual_hours=None,
    fallback_travel_amount=Decimal("0"),
):
    """
    パーサ出力(parsed dict)からInvoice(draft)を生成/更新する。

    Parameters
    ----------
    assignment_id : int
    parsed : dict  parse_timesheet_xlsx_generic() の戻り値
    fallback_billing_ym : str | None
    fallback_actual_hours : Decimal | None
    fallback_travel_amount : Decimal | None

    Returns
    -------
    Invoice
    """
    assignment = Assignment.objects.get(id=assignment_id)

    # --- 値の解決（parsed優先 → fallback） ---
    billing_ym = (parsed.get("billing_ym") or {}).get("value") or fallback_billing_ym
    if not billing_ym:
        raise ValueError("billing_ym が特定できません（パーサ結果にもfallbackにもありません）")

    actual_hours = (parsed.get("actual_hours") or {}).get("value") or fallback_actual_hours
    if actual_hours is None:
        raise ValueError("actual_hours が特定できません（パーサ結果にもfallbackにもありません）")
    actual_hours = Decimal(str(actual_hours))

    travel_raw = (parsed.get("travel_amount") or {}).get("value")
    travel_amount = Decimal(str(travel_raw)) if travel_raw is not None else (fallback_travel_amount or Decimal("0"))

    # --- 契約取得 ---
    contract = get_active_contract(assignment, billing_ym)

    # --- 既存Invoice確認 ---
    invoice, created = Invoice.objects.get_or_create(
        assignment=assignment,
        billing_ym=billing_ym,
        defaults={"status": "draft"},
    )

    if not created and invoice.status != "draft":
        raise ValueError(
            f"Invoice {invoice.id} はステータス '{invoice.status}' のため更新できません"
        )

    # --- 明細行計算 ---
    line_dicts = calculate_invoice_lines(
        assignment=assignment,
        contract=contract,
        billing_ym=billing_ym,
        actual_hours=actual_hours,
        travel_amount=travel_amount,
    )

    # --- 明細行保存（全削除→再作成） ---
    invoice.lines.all().delete()
    for ld in line_dicts:
        InvoiceLine.objects.create(invoice=invoice, **ld)

    invoice.actual_hours = actual_hours

    # --- デフォルトのヘッダ値（未設定の場合のみ） ---
    if not invoice.invoice_number:
        invoice.invoice_number = generate_invoice_number(billing_ym, exclude_invoice_id=invoice.id)
    if not invoice.issue_date:
        invoice.issue_date = date.today()
    if not invoice.due_date:
        invoice.due_date = default_due_date(billing_ym, contract.upstream_payment_terms)

    invoice.save()

    # --- 集計 ---
    recalculate_totals(invoice)

    return invoice
