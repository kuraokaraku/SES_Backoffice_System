"""
重複する ContactEntity をマージする管理コマンド。

使い方:
  python manage.py merge_duplicate_entities          # dry-run（変更なし）
  python manage.py merge_duplicate_entities --apply   # 実行

ロジック:
  同じ kind + name を持つ ContactEntity をグループ化し、
  最も多くの Assignment FK を持つレコードを canonical（正）とする。
  残りのレコードが持つ FK 参照を canonical に付け替えてから削除する。
"""
from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from system_app.models import (
    ContactEntity,
    EntityContactPerson,
    Assignment,
    SalesDeal,
)


class Command(BaseCommand):
    help = "重複する ContactEntity をマージ (--apply で実行)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="実際にマージを実行する（指定しなければ dry-run）",
        )

    def handle(self, *args, **options):
        dry_run = not options["apply"]
        if dry_run:
            self.stdout.write(self.style.WARNING("=== DRY RUN (--apply で実行) ===\n"))

        # FK フィールド一覧: (Model, field_name)
        assignment_fks = [
            ("worker_entity", Assignment),
            ("sales_owner_entity", Assignment),
            ("upstream_entity", Assignment),
            ("downstream_entity", Assignment),
        ]

        total_merged = 0
        total_deleted = 0

        for kind in ("PERSON", "COMPANY"):
            dupes = (
                ContactEntity.objects.filter(kind=kind)
                .values("name")
                .annotate(cnt=Count("id"))
                .filter(cnt__gt=1)
                .order_by("name")
            )

            for dup in dupes:
                name = dup["name"]
                group = list(
                    ContactEntity.objects.filter(kind=kind, name=name).order_by("id")
                )

                # canonical = Assignment で最も参照されているもの（同数なら最小ID）
                def fk_count(entity):
                    count = 0
                    for fk_field, _ in assignment_fks:
                        count += Assignment.objects.filter(**{fk_field: entity}).count()
                    count += SalesDeal.objects.filter(candidate_entity=entity).count()
                    return count

                group.sort(key=lambda e: (-fk_count(e), e.id))
                canonical = group[0]
                others = group[1:]

                self.stdout.write(
                    f"\n{kind} \"{name}\" — canonical=id:{canonical.id}, "
                    f"merge {len(others)} duplicate(s)"
                )

                for other in others:
                    # Assignment FKs
                    for fk_field, model in assignment_fks:
                        qs = model.objects.filter(**{fk_field: other})
                        cnt = qs.count()
                        if cnt:
                            self.stdout.write(
                                f"  Assignment.{fk_field}: {cnt} row(s) → id:{canonical.id}"
                            )
                            if not dry_run:
                                qs.update(**{fk_field: canonical})

                    # SalesDeal.candidate_entity
                    sd_qs = SalesDeal.objects.filter(candidate_entity=other)
                    sd_cnt = sd_qs.count()
                    if sd_cnt:
                        self.stdout.write(
                            f"  SalesDeal.candidate_entity: {sd_cnt} row(s) → id:{canonical.id}"
                        )
                        if not dry_run:
                            sd_qs.update(candidate_entity=canonical)

                    # EntityContactPerson（COMPANY の担当者を canonical に移動）
                    cp_qs = EntityContactPerson.objects.filter(corporate_entity=other)
                    cp_cnt = cp_qs.count()
                    if cp_cnt:
                        self.stdout.write(
                            f"  EntityContactPerson: {cp_cnt} row(s) → id:{canonical.id}"
                        )
                        if not dry_run:
                            cp_qs.update(corporate_entity=canonical)

                    # canonical の空フィールドを other から補完
                    if not dry_run:
                        for field in ("email", "phone", "worker_type", "address",
                                      "mailing_address", "company_phone"):
                            if not getattr(canonical, field) and getattr(other, field):
                                setattr(canonical, field, getattr(other, field))
                        if other.has_invoice_registration and not canonical.has_invoice_registration:
                            canonical.has_invoice_registration = True
                        canonical.save()

                    self.stdout.write(f"  DELETE id:{other.id}")
                    if not dry_run:
                        other.delete()
                    total_deleted += 1

                total_merged += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\n完了: {total_merged} グループ, {total_deleted} レコード削除"
                + (" (dry-run)" if dry_run else "")
            )
        )
