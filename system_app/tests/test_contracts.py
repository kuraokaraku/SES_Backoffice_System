"""get_active_contract サービスのテスト"""
from datetime import date

from django.test import TestCase

from system_app.models import Assignment, ContactEntity, ServiceContract
from system_app.services.contracts import get_active_contract


def _make_assignment():
    worker = ContactEntity.objects.create(kind="PERSON", name="テスト 太郎")
    sales = ContactEntity.objects.create(kind="COMPANY", name="営業会社")
    upstream = ContactEntity.objects.create(kind="COMPANY", name="上位会社")
    downstream = ContactEntity.objects.create(kind="COMPANY", name="下位会社")
    return Assignment.objects.create(
        worker_entity=worker,
        sales_owner_entity=sales,
        upstream_entity=upstream,
        downstream_entity=downstream,
    )


def _make_contract(assignment, valid_from=None, valid_to=None):
    return ServiceContract.objects.create(
        assignment=assignment,
        unit_price=500000,
        valid_from=valid_from,
        valid_to=valid_to,
    )


class GetActiveContractTest(TestCase):
    def setUp(self):
        self.assignment = _make_assignment()

    def test_returns_contract_within_period(self):
        contract = _make_contract(
            self.assignment,
            valid_from=date(2025, 7, 1),
            valid_to=date(2025, 12, 31),
        )
        result = get_active_contract(self.assignment, "202509")
        self.assertEqual(result, contract)

    def test_raises_when_no_contract(self):
        with self.assertRaises(ValueError):
            get_active_contract(self.assignment, "202601")

    def test_raises_when_billing_before_valid_from(self):
        _make_contract(
            self.assignment,
            valid_from=date(2025, 7, 1),
            valid_to=date(2025, 12, 31),
        )
        with self.assertRaises(ValueError):
            get_active_contract(self.assignment, "202506")

    def test_raises_when_billing_after_valid_to(self):
        _make_contract(
            self.assignment,
            valid_from=date(2025, 7, 1),
            valid_to=date(2025, 12, 31),
        )
        with self.assertRaises(ValueError):
            get_active_contract(self.assignment, "202601")

    def test_null_valid_to_means_open_ended(self):
        contract = _make_contract(
            self.assignment,
            valid_from=date(2025, 7, 1),
            valid_to=None,  # 終了日なし
        )
        result = get_active_contract(self.assignment, "202612")
        self.assertEqual(result, contract)

    def test_null_valid_from_matches_any_month(self):
        contract = _make_contract(self.assignment, valid_from=None, valid_to=None)
        result = get_active_contract(self.assignment, "202601")
        self.assertEqual(result, contract)

    def test_returns_latest_contract_when_multiple(self):
        # 旧契約（2025年）と更新契約（2026年）が重なっている場合、新しい方を返す
        _make_contract(
            self.assignment,
            valid_from=date(2025, 1, 1),
            valid_to=date(2025, 12, 31),
        )
        new_contract = _make_contract(
            self.assignment,
            valid_from=date(2026, 1, 1),
            valid_to=None,
        )
        result = get_active_contract(self.assignment, "202601")
        self.assertEqual(result, new_contract)
