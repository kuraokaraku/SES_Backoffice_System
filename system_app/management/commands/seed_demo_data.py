"""デモデータ生成コマンド

Usage:
    python manage.py seed_demo_data          # 生成
    python manage.py seed_demo_data --clear  # シードデータ削除
"""
import random
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from system_app.models import Assignment, Invoice, Payable
from system_app.services.contracts import get_active_contract
from system_app.services.invoicing import create_or_update_invoice_from_parsed
from system_app.services.payable_service import create_or_update_payable_from_parsed

TARGET_YMS = ["202509", "202510", "202511", "202512", "202601", "202602"]

# 再現可能なランダムシード
RANDOM_SEED = 42


def _make_parsed(billing_ym, actual_hours):
    """invoicing / payable_service が受け付ける parsed dict を組み立てる"""
    return {
        "billing_ym": {"value": billing_ym, "confidence": 1.0},
        "actual_hours": {"value": actual_hours, "confidence": 1.0},
        "travel_amount": {"value": Decimal("0"), "confidence": 1.0},
    }


class Command(BaseCommand):
    help = "デモ用の Invoice / Payable データを生成（202512〜202602）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="シードデータ（対象月）を削除",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["clear"]:
            self._clear()
            return

        rng = random.Random(RANDOM_SEED)
        assignments = list(Assignment.objects.filter(is_active=True))

        if not assignments:
            self.stderr.write(self.style.ERROR("稼働中の Assignment がありません"))
            return

        self.stdout.write(f"対象 Assignment: {len(assignments)}件")

        created_inv = 0
        created_pay = 0
        skipped = 0

        for ym in TARGET_YMS:
            for asn in assignments:
                # 契約の存在チェック
                try:
                    contract = get_active_contract(asn, ym)
                except ValueError:
                    skipped += 1
                    continue

                # 固定報酬なら 160h、それ以外はランダム
                if contract.is_fixed_fee:
                    hours = Decimal("160.00")
                else:
                    hours = Decimal(str(rng.randint(140, 185))) + Decimal(str(rng.choice([0, 0.25, 0.5, 0.75])))

                parsed = _make_parsed(ym, hours)

                # --- Invoice ---
                try:
                    existing = Invoice.objects.filter(
                        assignment=asn, billing_ym=ym
                    ).exclude(status="draft").first()
                    if existing:
                        self.stdout.write(
                            f"  SKIP Invoice {asn.id}/{ym} (status={existing.status})"
                        )
                    else:
                        inv = create_or_update_invoice_from_parsed(
                            assignment_id=asn.id, parsed=parsed
                        )
                        inv.status = "sent"
                        inv.save(update_fields=["status"])
                        created_inv += 1
                except Exception as e:
                    self.stderr.write(f"  ERROR Invoice {asn.id}/{ym}: {e}")

                # --- Payable ---
                try:
                    existing = Payable.objects.filter(
                        assignment=asn, billing_ym=ym
                    ).exclude(status="draft").first()
                    if existing:
                        self.stdout.write(
                            f"  SKIP Payable {asn.id}/{ym} (status={existing.status})"
                        )
                    else:
                        pay = create_or_update_payable_from_parsed(
                            assignment_id=asn.id, parsed=parsed
                        )
                        if pay:
                            pay.status = "sent"
                            pay.save(update_fields=["status"])
                            created_pay += 1
                except Exception as e:
                    self.stderr.write(f"  ERROR Payable {asn.id}/{ym}: {e}")

        self.stdout.write(self.style.SUCCESS(
            f"完了: Invoice {created_inv}件, Payable {created_pay}件 生成 "
            f"(スキップ {skipped}件)"
        ))

    def _clear(self):
        inv_del, _ = Invoice.objects.filter(billing_ym__in=TARGET_YMS).delete()
        pay_del, _ = Payable.objects.filter(billing_ym__in=TARGET_YMS).delete()
        self.stdout.write(self.style.SUCCESS(
            f"削除完了: Invoice関連 {inv_del}件, Payable関連 {pay_del}件"
        ))
