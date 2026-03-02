"""請求書の計算・採番・期日ロジック"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_DOWN


def _decimal(value, default=Decimal("0")):
    """安全に Decimal へ変換。None は default を返す。"""
    if value is None:
        return default
    return Decimal(str(value))


def _floor_decimal(value, step):
    """Decimal の切り捨て丸め。step 刻みで切り捨てる。
    例: _floor_decimal(Decimal("1.75"), Decimal("0.5")) -> Decimal("1.5")
    """
    if step <= 0:
        return value
    return value - (value % step)


def calculate_invoice_lines(assignment, contract, billing_ym, actual_hours, travel_amount):
    """
    契約条件と実績から請求書明細行(dict list)を生成する。

    Parameters
    ----------
    assignment : Assignment
    contract : ServiceContract
    billing_ym : str  "YYYYMM"
    actual_hours : Decimal
    travel_amount : Decimal

    Returns
    -------
    list[dict]
    """
    actual = _decimal(actual_hours)
    upper = _decimal(contract.upper_limit_hours)
    lower = _decimal(contract.lower_limit_hour)
    unit_price = _decimal(contract.unit_price)
    excess_price = _decimal(contract.excess_unit_price)
    deduction_price = _decimal(contract.deduction_unit_price)
    settlement_min = contract.settlement_unit_minutes

    # 丸めステップ（分→時間）
    if settlement_min:
        step_hours = Decimal(str(settlement_min)) / Decimal("60")
    else:
        step_hours = None

    lines = []

    # A. 基本行
    project = assignment.project_name or f"Assignment {assignment.id}"
    lines.append({
        "kind": "basic",
        "display_order": 10,
        "item_name": f"{project} 作業代（{billing_ym}）",
        "quantity": Decimal("1"),
        "unit_price": unit_price,
        "amount": unit_price,
    })

    # B. 超過
    if upper and actual > upper:
        excess_raw = actual - upper
        excess_rounded = _floor_decimal(excess_raw, step_hours) if step_hours else excess_raw
        excess_amount = (excess_rounded * excess_price).to_integral_value(rounding=ROUND_DOWN)
        if excess_amount > 0:
            lines.append({
                "kind": "excess",
                "display_order": 20,
                "item_name": "超過精算",
                "quantity": excess_rounded,
                "unit_price": excess_price,
                "amount": excess_amount,
            })

    # B. 控除（マイナスで保存）
    if lower and actual < lower:
        deduction_raw = lower - actual
        deduction_rounded = _floor_decimal(deduction_raw, step_hours) if step_hours else deduction_raw
        deduction_amount = (deduction_rounded * deduction_price).to_integral_value(rounding=ROUND_DOWN)
        if deduction_amount > 0:
            lines.append({
                "kind": "deduction",
                "display_order": 30,
                "item_name": "控除精算",
                "quantity": deduction_rounded,
                "unit_price": deduction_price,
                "amount": -deduction_amount,
            })

    # C. 交通費
    travel = _decimal(travel_amount)
    if not contract.travel_expense_included and travel > 0:
        lines.append({
            "kind": "expense",
            "display_order": 40,
            "item_name": "交通費（実費）",
            "quantity": Decimal("1"),
            "unit_price": travel,
            "amount": travel,
        })

    return lines


# =====================================================
# 集計（小計→税→合計）
# =====================================================

def recalculate_totals(invoice):
    """
    invoice の明細行から小計・税・合計を再計算して保存する。

    交通費(expense)は非課税なので小計から除外し、合計にのみ加算する。
    """
    lines = invoice.lines.all()
    subtotal = sum(l.amount for l in lines if l.kind != "expense")
    expense_total = sum(l.amount for l in lines if l.kind == "expense")
    tax = (subtotal * invoice.tax_rate).to_integral_value(rounding=ROUND_DOWN)

    invoice.subtotal_amount = subtotal
    invoice.tax_amount = tax
    invoice.total_amount = subtotal + tax + expense_total
    invoice.save()


# =====================================================
# 支払期日
# =====================================================

def default_due_date(billing_ym, upstream_payment_terms=None):
    """
    billing_ym (YYYYMM) と支払サイト(日数) からデフォルトの支払期日を返す。

    terms が指定されていれば翌月1日 + terms日、
    なければ翌月末日を返す。
    """
    y, m = int(billing_ym[:4]), int(billing_ym[4:])
    if m == 12:
        next_month_first = date(y + 1, 1, 1)
    else:
        next_month_first = date(y, m + 1, 1)

    if upstream_payment_terms:
        return next_month_first + timedelta(days=upstream_payment_terms)

    # 翌月末
    if next_month_first.month == 12:
        return date(next_month_first.year, 12, 31)
    return date(next_month_first.year, next_month_first.month + 1, 1) - timedelta(days=1)


# =====================================================
# 請求書番号の採番
# =====================================================

def generate_invoice_number(billing_ym, exclude_invoice_id=None):
    """
    YYYYMM + アルファベット連番（202602A, 202602B, ...）を生成する。
    """
    from system_app.models import Invoice

    qs = Invoice.objects.filter(
        billing_ym=billing_ym,
        invoice_number__isnull=False,
    )
    if exclude_invoice_id:
        qs = qs.exclude(id=exclude_invoice_id)
    suffix = chr(ord("A") + qs.count())
    return f"{billing_ym}{suffix}"


# =====================================================
# 買掛（Payable）向けラッパー
# =====================================================

class _DownstreamProxy:
    """ServiceContract の downstream_* を upstream 名に読み替えるプロキシ"""

    def __init__(self, contract):
        self.unit_price = contract.downstream_unit_price
        self.is_fixed_fee = contract.downstream_is_fixed_fee
        self.lower_limit_hour = contract.downstream_lower_limit_hour
        self.upper_limit_hours = contract.downstream_upper_limit_hours
        self.deduction_unit_price = contract.downstream_deduction_unit_price
        self.excess_unit_price = contract.downstream_excess_unit_price
        self.settlement_unit_minutes = contract.downstream_settlement_unit_minutes
        self.travel_expense_included = contract.travel_expense_included


def calculate_payable_lines(assignment, contract, billing_ym, actual_hours, travel_amount):
    """
    下位向け買掛明細行を生成する。
    contract の downstream_* フィールドを使い、calculate_invoice_lines() に委譲。
    """
    proxy = _DownstreamProxy(contract)
    return calculate_invoice_lines(
        assignment=assignment,
        contract=proxy,
        billing_ym=billing_ym,
        actual_hours=actual_hours,
        travel_amount=travel_amount,
    )


def recalculate_payable_totals(payable):
    """
    payable の明細行から小計・税・合計を再計算して保存する。
    recalculate_totals() と同一ロジック。
    """
    lines = payable.lines.all()
    subtotal = sum(l.amount for l in lines if l.kind != "expense")
    expense_total = sum(l.amount for l in lines if l.kind == "expense")
    tax = (subtotal * payable.tax_rate).to_integral_value(rounding=ROUND_DOWN)

    payable.subtotal_amount = subtotal
    payable.tax_amount = tax
    payable.total_amount = subtotal + tax + expense_total
    payable.save()


def generate_payable_number(billing_ym, exclude_payable_id=None):
    """
    P{YYYYMM}{A,B,C...} 形式の買掛番号を生成する。
    """
    from system_app.models import Payable

    qs = Payable.objects.filter(
        billing_ym=billing_ym,
        payable_number__isnull=False,
    )
    if exclude_payable_id:
        qs = qs.exclude(id=exclude_payable_id)
    suffix = chr(ord("A") + qs.count())
    return f"P{billing_ym}{suffix}"
