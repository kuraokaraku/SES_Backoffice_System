"""契約取得サービス"""
from datetime import date

from django.db.models import Q

from system_app.models import ServiceContract


def get_active_contract(assignment, billing_ym: str):
    """
    assignment に紐づく ServiceContract のうち billing_ym 時点で有効なものを返す。

    Parameters
    ----------
    assignment : Assignment
    billing_ym : str  "YYYYMM"

    Returns
    -------
    ServiceContract

    Raises
    ------
    ValueError  該当する契約が無い場合
    """
    y, m = int(billing_ym[:4]), int(billing_ym[4:])
    billing_month = date(y, m, 1)

    contract = (
        ServiceContract.objects
        .filter(assignment=assignment)
        .filter(
            Q(valid_from__isnull=True) | Q(valid_from__lte=billing_month),
            Q(valid_to__isnull=True) | Q(valid_to__gte=billing_month),
        )
        .order_by("-valid_from")
        .first()
    )

    if contract is None:
        raise ValueError(
            f"No active contract for Assignment {assignment.id} in {billing_ym}"
        )

    return contract
