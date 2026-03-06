from decimal import Decimal

from django.db import models
import os

class Freelancer(models.Model):
    """個人事業主モデル"""
    name = models.CharField(max_length=100, verbose_name="氏名")
    email = models.EmailField(unique=True, verbose_name="メールアドレス")
    client_name = models.CharField(max_length=100, blank=True, verbose_name="クライアント名")
    project_name = models.CharField(max_length=100, blank=True, verbose_name="案件名")

    # 精算・単価設定
    base_unit_price = models.IntegerField(default=0, verbose_name="基準単価(月単価)")
    lower_limit_hours = models.FloatField(default=140.0, verbose_name="精算下限時間")
    upper_limit_hours = models.FloatField(default=180.0, verbose_name="精算上限時間")
    deduction_unit_price = models.IntegerField(default=0, verbose_name="控除単価(不足時)")
    overtime_unit_price = models.IntegerField(default=0, verbose_name="超過単価(超過時)")

    # 契約期間（稼働なし月を判定するため）
    contract_start = models.DateField(null=True, blank=True, verbose_name="契約開始日")
    contract_end = models.DateField(null=True, blank=True, verbose_name="契約終了日")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="登録日")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新日")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "個人事業主"
        verbose_name_plural = "個人事業主一覧"

class MonthlyProcess(models.Model):
    """月次管理（例：2024年1月、2024年2月...）"""
    year_month = models.DateField(unique=True, verbose_name="対象年月")
    is_completed = models.BooleanField(default=False, verbose_name="全体の完了フラグ")

    def __str__(self):
        return self.year_month.strftime('%Y年%m月')

class ContactEntity(models.Model):
    """連絡先エンティティ（個人/法人）"""
    kind = models.CharField(max_length=20)  # "PERSON" or "COMPANY"
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    worker_type = models.CharField(max_length=50, blank=True, null=True)  # PERSON only
    # COMPANY用
    address = models.TextField(blank=True, null=True, verbose_name="会社住所")
    mailing_address = models.TextField(blank=True, null=True, verbose_name="送付先住所")
    company_phone = models.CharField(max_length=50, blank=True, null=True, verbose_name="会社電話番号")
    has_invoice_registration = models.BooleanField(default=False, verbose_name="インボイス登録済み")

    def __str__(self):
        return f"{self.name} ({self.kind})"


class EntityContactPerson(models.Model):
    """法人エンティティの担当者"""
    corporate_entity = models.ForeignKey(
        ContactEntity,
        on_delete=models.CASCADE,
        related_name="contact_people",
    )
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    line_available = models.BooleanField(default=False, verbose_name="LINE連絡可")

    def __str__(self):
        return f"{self.name}"


class ContactEmail(models.Model):
    """担当者の追加メールアドレス"""
    contact_person = models.ForeignKey(
        EntityContactPerson,
        on_delete=models.CASCADE,
        related_name="extra_emails",
    )
    email = models.EmailField()
    description = models.CharField(max_length=100, blank=True, verbose_name="説明")

    def __str__(self):
        return f"{self.email} ({self.description})"


class Assignment(models.Model):
    """アサインメント（案件）"""
    worker_entity = models.ForeignKey(
        ContactEntity,
        on_delete=models.PROTECT,
        related_name="assignments_as_worker",
    )
    sales_owner_entity = models.ForeignKey(
        ContactEntity,
        on_delete=models.PROTECT,
        related_name="assignments_as_sales_owner",
    )

    notes = models.TextField(blank=True, null=True)
    project_name = models.CharField(max_length=255, blank=True, null=True)

    upstream_entity = models.ForeignKey(
        ContactEntity,
        on_delete=models.PROTECT,
        related_name="assignments_as_upstream",
    )
    upstream_contact_person = models.ForeignKey(
        EntityContactPerson,
        on_delete=models.PROTECT,
        related_name="assignments_as_upstream_contact",
        blank=True,
        null=True,
    )

    downstream_entity = models.ForeignKey(
        ContactEntity,
        on_delete=models.PROTECT,
        related_name="assignments_as_downstream",
    )
    downstream_contact_person = models.ForeignKey(
        EntityContactPerson,
        on_delete=models.PROTECT,
        related_name="assignments_as_downstream_contact",
        blank=True,
        null=True,
    )

    is_active = models.BooleanField(default=True, verbose_name="稼働中")

    def __str__(self):
        return f"Assignment {self.id}"


class ServiceContract(models.Model):
    """契約条件"""
    TIMESHEET_SOURCE_CHOICES = [
        ('UPSTREAM', '上位から'),
        ('DOWNSTREAM', '下位から'),
    ]

    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.CASCADE,
        related_name="contracts",
    )

    valid_from = models.DateField(blank=True, null=True)
    valid_to = models.DateField(blank=True, null=True)  # NULL = current

    unit_price = models.IntegerField()
    is_fixed_fee = models.BooleanField(default=False, verbose_name="固定報酬")
    travel_expense_included = models.BooleanField(default=False, verbose_name="交通費込み")
    # 勤務表回収（上位/下位）
    upstream_timesheet_collection_method = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="上位 勤務表回収手段"
    )
    downstream_timesheet_collection_method = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="下位 勤務表回収手段"
    )
    lower_limit_hour = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    upper_limit_hours = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    deduction_unit_price = models.IntegerField(blank=True, null=True)
    excess_unit_price = models.IntegerField(blank=True, null=True)
    settlement_unit_minutes = models.IntegerField(blank=True, null=True, verbose_name="精算時間単位（分）")
    upstream_payment_terms = models.IntegerField(blank=True, null=True, verbose_name="上位支払いサイト（日）")
    downstream_payment_terms = models.IntegerField(blank=True, null=True, verbose_name="下位支払いサイト（日）")
    bank_holiday_handling = models.CharField(max_length=100, blank=True, null=True, verbose_name="金融機関休業日の場合")
    downstream_bank_holiday_handling = models.CharField(max_length=100, blank=True, null=True, verbose_name="下位 金融機関休業日の場合")
    timesheet_due_date = models.DateField(blank=True, null=True, verbose_name="勤務表締め日（旧）")
    downstream_timesheet_due_day = models.PositiveSmallIntegerField(
        blank=True, null=True, verbose_name="下位 勤務表締め日（翌月N日）"
    )

    # 下位（発注先）契約条件
    downstream_unit_price = models.IntegerField(blank=True, null=True, verbose_name="下位単価")
    downstream_is_fixed_fee = models.BooleanField(default=False, verbose_name="下位固定報酬")
    downstream_lower_limit_hour = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, verbose_name="下位精算下限時間")
    downstream_upper_limit_hours = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, verbose_name="下位精算上限時間")
    downstream_deduction_unit_price = models.IntegerField(blank=True, null=True, verbose_name="下位控除単価")
    downstream_excess_unit_price = models.IntegerField(blank=True, null=True, verbose_name="下位超過単価")
    downstream_settlement_unit_minutes = models.IntegerField(blank=True, null=True, verbose_name="下位精算時間単位（分）")

    def __str__(self):
        return f"ServiceContract {self.id}"


class LegacyTaskStatus(models.Model):
    """旧：個人ごとの作業ステータス"""
    STATUS_CHOICES = [
        ('not_started', '未着手'),
        ('working', '書類待ち'),
        ('completed', '完了'),
    ]

    monthly_process = models.ForeignKey(MonthlyProcess, on_delete=models.CASCADE, related_name='legacy_tasks')
    freelancer = models.ForeignKey('Freelancer', on_delete=models.CASCADE)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='not_started', verbose_name="進捗状況")
    working_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name="勤務時間")
    payment_amount = models.IntegerField(default=0, verbose_name="支払金額")
    google_drive_url = models.URLField(blank=True, null=True, verbose_name="資料URL")
    actual_working_hours = models.FloatField(default=0.0, verbose_name="実稼働時間")
    calculated_amount = models.IntegerField(default=0, verbose_name="計算請求金額")

    class Meta:
        unique_together = ('monthly_process', 'freelancer')

    def __str__(self):
        return f"LegacyTaskStatus {self.id}"


class TaskStatus(models.Model):
    """新：月次タスクステータス"""
    month = models.ForeignKey(
        MonthlyProcess,
        on_delete=models.CASCADE,
        related_name="task_statuses",
    )
    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.CASCADE,
        related_name="task_statuses",
    )

    timesheet_status = models.CharField(max_length=30)
    invoice_status = models.CharField(max_length=30)
    purchase_order_status = models.CharField(max_length=30)
    actual_hours = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

    def __str__(self):
        return f"TaskStatus {self.id}"

class Invoice(models.Model):
    """請求書ヘッダ"""
    STATUS_CHOICES = [
        ('draft', '下書き'),
        ('final', '確定'),
        ('sent', '送付済'),
        ('cancelled', '取消'),
    ]

    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.CASCADE,
        related_name="invoices",
    )
    billing_ym = models.CharField(max_length=6, verbose_name="請求対象年月")  # "YYYYMM"
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='draft',
        verbose_name="ステータス",
    )
    invoice_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        unique=True,
        verbose_name="請求書番号",
    )
    issue_date = models.DateField(null=True, blank=True, verbose_name="発行日")
    due_date = models.DateField(null=True, blank=True, verbose_name="支払期日")
    tax_rate = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("0.10"),
        verbose_name="税率",
    )
    subtotal_amount = models.DecimalField(
        max_digits=12, decimal_places=0, default=0, verbose_name="小計"
    )
    tax_amount = models.DecimalField(
        max_digits=12, decimal_places=0, default=0, verbose_name="消費税額"
    )
    total_amount = models.DecimalField(
        max_digits=12, decimal_places=0, default=0, verbose_name="合計金額"
    )
    actual_hours = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="実稼働時間"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="作成日時")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新日時")

    class Meta:
        verbose_name = "請求書"
        verbose_name_plural = "請求書一覧"
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "billing_ym"],
                name="uniq_invoice_assignment_month",
            ),
        ]
        indexes = [
            models.Index(fields=["billing_ym", "status"]),
        ]

    def __str__(self):
        return f"Invoice {self.invoice_number or 'DRAFT'} ({self.billing_ym})"


class InvoiceLine(models.Model):
    """請求書明細行"""
    KIND_CHOICES = [
        ('basic', '基本'),
        ('excess', '超過'),
        ('deduction', '控除'),
        ('expense', '交通費等'),
        ('adjustment', '調整'),
    ]

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    kind = models.CharField(
        max_length=20,
        choices=KIND_CHOICES,
        default='basic',
        verbose_name="種別",
    )
    display_order = models.PositiveSmallIntegerField(default=0, verbose_name="並び順")
    item_name = models.CharField(max_length=255, verbose_name="品名")
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2, default=1, verbose_name="数量"
    )
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=0, default=0, verbose_name="単価"
    )
    amount = models.DecimalField(
        max_digits=12, decimal_places=0, default=0, verbose_name="金額"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="作成日時")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新日時")

    class Meta:
        verbose_name = "請求書明細行"
        verbose_name_plural = "請求書明細行一覧"
        constraints = [
            models.UniqueConstraint(
                fields=["invoice", "display_order"],
                name="uniq_invoice_line_order",
            ),
        ]
        indexes = [
            models.Index(fields=["invoice", "kind"]),
        ]

    def __str__(self):
        return f"{self.item_name} ({self.get_kind_display()})"


class Timesheet(models.Model):
    """勤務表"""
    STATUS_CHOICES = [
        ('received', '受領済'),
        ('processed', '請求書生成済'),
    ]

    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.CASCADE,
        related_name="timesheets",
    )
    billing_ym = models.CharField(max_length=6, verbose_name="対象年月")  # "YYYYMM"
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='received',
        verbose_name="ステータス",
    )
    file = models.FileField(upload_to='timesheets/%Y/%m/', verbose_name="勤務表ファイル")
    original_filename = models.CharField(max_length=255, verbose_name="元ファイル名")
    actual_hours = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="実稼働時間"
    )
    travel_amount = models.DecimalField(
        max_digits=12, decimal_places=0, null=True, blank=True, verbose_name="交通費"
    )
    parse_confidence = models.JSONField(null=True, blank=True, verbose_name="パース信頼度")
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="timesheets",
        verbose_name="請求書",
    )
    received_at = models.DateTimeField(auto_now_add=True, verbose_name="受領日時")
    notes = models.TextField(blank=True, verbose_name="備考")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="作成日時")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新日時")

    class Meta:
        verbose_name = "勤務表"
        verbose_name_plural = "勤務表一覧"
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "billing_ym"],
                name="uniq_timesheet_assignment_month",
            ),
        ]

    def __str__(self):
        return f"Timesheet {self.assignment_id} ({self.billing_ym})"


class InvoicePayment(models.Model):
    """入金（消込）レコード"""
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="payments",
        verbose_name="請求書",
    )
    paid_date = models.DateField(verbose_name="入金日")
    amount = models.DecimalField(
        max_digits=12, decimal_places=0, verbose_name="入金額"
    )
    note = models.TextField(blank=True, default="", verbose_name="メモ")
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="登録者",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="登録日時")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新日時")

    class Meta:
        verbose_name = "入金"
        verbose_name_plural = "入金一覧"
        ordering = ["-paid_date", "-created_at"]
        indexes = [
            models.Index(fields=["invoice"]),
            models.Index(fields=["paid_date"]),
        ]

    def __str__(self):
        return f"{self.invoice} - ¥{self.amount:,.0f} ({self.paid_date})"


class Payable(models.Model):
    """買掛ヘッダ（下位への支払い）"""
    STATUS_CHOICES = [
        ('draft', '下書き'),
        ('final', '確定'),
        ('sent', '請求書受領済'),
        ('cancelled', '取消'),
    ]

    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.CASCADE,
        related_name="payables",
    )
    billing_ym = models.CharField(max_length=6, verbose_name="対象年月")  # "YYYYMM"
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='draft',
        verbose_name="ステータス",
    )
    payable_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        unique=True,
        verbose_name="買掛番号",
    )
    issue_date = models.DateField(null=True, blank=True, verbose_name="発行日")
    due_date = models.DateField(null=True, blank=True, verbose_name="支払期日")
    tax_rate = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("0.10"),
        verbose_name="税率",
    )
    subtotal_amount = models.DecimalField(
        max_digits=12, decimal_places=0, default=0, verbose_name="小計"
    )
    tax_amount = models.DecimalField(
        max_digits=12, decimal_places=0, default=0, verbose_name="消費税額"
    )
    total_amount = models.DecimalField(
        max_digits=12, decimal_places=0, default=0, verbose_name="合計金額"
    )
    actual_hours = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="実稼働時間"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="作成日時")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新日時")

    class Meta:
        verbose_name = "買掛"
        verbose_name_plural = "買掛一覧"
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "billing_ym"],
                name="uniq_payable_assignment_month",
            ),
        ]
        indexes = [
            models.Index(fields=["billing_ym", "status"]),
        ]

    def __str__(self):
        return f"Payable {self.payable_number or 'DRAFT'} ({self.billing_ym})"


class PayableLine(models.Model):
    """買掛明細行"""
    KIND_CHOICES = [
        ('basic', '基本'),
        ('excess', '超過'),
        ('deduction', '控除'),
        ('expense', '交通費等'),
        ('adjustment', '調整'),
    ]

    payable = models.ForeignKey(
        Payable,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    kind = models.CharField(
        max_length=20,
        choices=KIND_CHOICES,
        default='basic',
        verbose_name="種別",
    )
    display_order = models.PositiveSmallIntegerField(default=0, verbose_name="並び順")
    item_name = models.CharField(max_length=255, verbose_name="品名")
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2, default=1, verbose_name="数量"
    )
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=0, default=0, verbose_name="単価"
    )
    amount = models.DecimalField(
        max_digits=12, decimal_places=0, default=0, verbose_name="金額"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="作成日時")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新日時")

    class Meta:
        verbose_name = "買掛明細行"
        verbose_name_plural = "買掛明細行一覧"
        constraints = [
            models.UniqueConstraint(
                fields=["payable", "display_order"],
                name="uniq_payable_line_order",
            ),
        ]

    def __str__(self):
        return f"{self.item_name} ({self.get_kind_display()})"


class PayablePayment(models.Model):
    """出金（消込）レコード"""
    payable = models.ForeignKey(
        Payable,
        on_delete=models.CASCADE,
        related_name="payments",
        verbose_name="買掛",
    )
    paid_date = models.DateField(verbose_name="支払日")
    amount = models.DecimalField(
        max_digits=12, decimal_places=0, verbose_name="支払額"
    )
    note = models.TextField(blank=True, default="", verbose_name="メモ")
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="登録者",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="登録日時")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新日時")

    class Meta:
        verbose_name = "出金"
        verbose_name_plural = "出金一覧"
        ordering = ["-paid_date", "-created_at"]
        indexes = [
            models.Index(fields=["payable"]),
            models.Index(fields=["paid_date"]),
        ]

    def __str__(self):
        return f"{self.payable} - ¥{self.amount:,.0f} ({self.paid_date})"


class PurchaseOrder(models.Model):
    client_name = models.CharField(max_length=255, verbose_name="クライアント名")
    file = models.FileField(upload_to='purchase_orders/%Y/%m/', verbose_name="注文書ファイル")
    received_at = models.DateTimeField(verbose_name="メール受信日")
    saved_at = models.DateTimeField(auto_now_add=True, verbose_name="保存日")
    download_count = models.PositiveIntegerField(default=0, verbose_name="ダウンロード回数")

    def __str__(self):
        return f"{self.client_name} - {self.received_at.strftime('%Y/%m/%d')}"

    # ファイル削除時に物理ファイルも消すための処理（任意）
    def delete(self, *args, **kwargs):
        if self.file:
            if os.path.isfile(self.file.path):
                os.remove(self.file.path)
        super().delete(*args, **kwargs)

class BusinessPartner(models.Model):
    name = models.CharField(max_length=255, verbose_name="会社名/屋号")
    contact_person = models.CharField(max_length=255, verbose_name="担当者名", blank=True, null=True)
    base_unit_price = models.IntegerField(verbose_name="基本単価")
    lower_limit_hours = models.FloatField(verbose_name="下限時間")
    upper_limit_hours = models.FloatField(verbose_name="上限時間")
    overtime_unit_price = models.IntegerField(verbose_name="超過単価")
    deduction_unit_price = models.IntegerField(verbose_name="控除単価")
    is_active = models.BooleanField(default=True, verbose_name="稼働中")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "提携パートナー"
        verbose_name_plural = "提携パートナー一覧"

# 名刺管理
class BusinessCard(models.Model):
    company_name = models.CharField("会社名", max_length=100, blank=True)
    name = models.CharField("氏名", max_length=100)
    department = models.CharField("部署", max_length=100, blank=True)
    position = models.CharField("役職", max_length=100, blank=True)
    email = models.EmailField("メールアドレス", blank=True)
    phone_number = models.CharField("電話番号", max_length=20, blank=True)
    address = models.TextField("住所", blank=True)
    image = models.ImageField("名刺画像", upload_to='business_cards/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.company_name} - {self.name}"


