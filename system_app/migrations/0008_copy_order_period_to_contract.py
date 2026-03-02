"""
order_period_start_ym / order_period_end_ym のデータを
ServiceContract.valid_from / valid_to に移行する。
契約側に既にデータがある場合は上書きしない。
"""
from django.db import migrations


def copy_order_period_to_contract(apps, schema_editor):
    Assignment = apps.get_model('system_app', 'Assignment')
    ServiceContract = apps.get_model('system_app', 'ServiceContract')

    for a in Assignment.objects.all():
        start = a.order_period_start_ym
        end = a.order_period_end_ym
        if not start and not end:
            continue

        # 最新の契約を取得（valid_to DESC, id DESC）
        contract = (
            ServiceContract.objects
            .filter(assignment=a)
            .order_by('-valid_to', '-id')
            .first()
        )
        if not contract:
            continue

        updated = False
        if start and not contract.valid_from:
            contract.valid_from = start
            updated = True
        if end and not contract.valid_to:
            contract.valid_to = end
            updated = True

        if updated:
            contract.save(update_fields=['valid_from', 'valid_to'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('system_app', '0007_payable_payableline_payablepayment_and_more'),
    ]

    operations = [
        migrations.RunPython(copy_order_period_to_contract, noop),
    ]
