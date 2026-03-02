"""買掛生成サービス（下位向け支払い）"""
from datetime import date
from decimal import Decimal

from django.db import transaction

from system_app.models import Assignment, Payable, PayableLine
from system_app.services.contracts import get_active_contract
from system_app.services.invoice_calculator import (
    calculate_payable_lines,
    default_due_date,
    generate_payable_number,
    recalculate_payable_totals,
)


@transaction.atomic
def create_or_update_payable_from_parsed(
    assignment_id,
    parsed,
    fallback_billing_ym=None,
    fallback_actual_hours=None,
    fallback_travel_amount=Decimal("0"),
):
    """
    パーサ出力(parsed dict)からPayable(draft)を生成/更新する。

    下位契約条件（downstream_unit_price）が無い場合は None を返す（スキップ）。

    Parameters
    ----------
    assignment_id : int
    parsed : dict  parse_timesheet_xlsx_generic() の戻り値
    fallback_billing_ym : str | None
    fallback_actual_hours : Decimal | None
    fallback_travel_amount : Decimal | None

    Returns
    -------
    Payable | None
    """
    assignment = Assignment.objects.get(id=assignment_id)

    # --- 値の解決（parsed優先 → fallback） ---
    billing_ym = (parsed.get("billing_ym") or {}).get("value") or fallback_billing_ym
    if not billing_ym:
        raise ValueError("billing_ym が特定できません")

    actual_hours = (parsed.get("actual_hours") or {}).get("value") or fallback_actual_hours
    if actual_hours is None:
        raise ValueError("actual_hours が特定できません")
    actual_hours = Decimal(str(actual_hours))

    travel_raw = (parsed.get("travel_amount") or {}).get("value")
    travel_amount = Decimal(str(travel_raw)) if travel_raw is not None else (fallback_travel_amount or Decimal("0"))

    # --- 契約取得 ---
    contract = get_active_contract(assignment, billing_ym)

    # --- 下位契約なし → スキップ ---
    if contract.downstream_unit_price is None:
        return None

    # --- 既存Payable確認 ---
    payable, created = Payable.objects.get_or_create(
        assignment=assignment,
        billing_ym=billing_ym,
        defaults={"status": "draft"},
    )

    if not created and payable.status != "draft":
        raise ValueError(
            f"Payable {payable.id} はステータス '{payable.status}' のため更新できません"
        )

    # --- 明細行計算 ---
    line_dicts = calculate_payable_lines(
        assignment=assignment,
        contract=contract,
        billing_ym=billing_ym,
        actual_hours=actual_hours,
        travel_amount=travel_amount,
    )

    # --- 明細行保存（全削除→再作成） ---
    payable.lines.all().delete()
    for ld in line_dicts:
        PayableLine.objects.create(payable=payable, **ld)

    payable.actual_hours = actual_hours

    # --- デフォルトのヘッダ値（未設定の場合のみ） ---
    if not payable.payable_number:
        payable.payable_number = generate_payable_number(billing_ym, exclude_payable_id=payable.id)
    if not payable.issue_date:
        payable.issue_date = date.today()
    if not payable.due_date:
        payable.due_date = default_due_date(billing_ym, contract.downstream_payment_terms)

    payable.save()

    # --- 集計 ---
    recalculate_payable_totals(payable)

    return payable
