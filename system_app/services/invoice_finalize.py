"""請求書確定サービス"""
from datetime import date

from django.db import transaction

from system_app.models import Invoice
from system_app.services.contracts import get_active_contract
from system_app.services.invoice_calculator import (
    default_due_date,
    generate_invoice_number,
)


@transaction.atomic
def finalize_invoice(invoice_id, issue_date=None):
    """
    請求書を確定する。

    Parameters
    ----------
    invoice_id : int
    issue_date : date | None  省略時は今日

    Returns
    -------
    Invoice
    """
    invoice = Invoice.objects.select_for_update().get(id=invoice_id)

    if invoice.status != "draft":
        raise ValueError(
            f"Invoice {invoice.id} はステータス '{invoice.status}' のため確定できません"
        )

    # issue_date
    if issue_date is None:
        issue_date = date.today()
    invoice.issue_date = issue_date

    # due_date
    if not invoice.due_date:
        try:
            contract = get_active_contract(invoice.assignment, invoice.billing_ym)
            terms = contract.upstream_payment_terms
        except ValueError:
            terms = None
        invoice.due_date = default_due_date(invoice.billing_ym, terms)

    # invoice_number
    if not invoice.invoice_number:
        invoice.invoice_number = generate_invoice_number(
            invoice.billing_ym, exclude_invoice_id=invoice.id
        )

    invoice.status = "final"
    invoice.save()
    return invoice
