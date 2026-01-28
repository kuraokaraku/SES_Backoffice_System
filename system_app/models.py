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

class TaskStatus(models.Model):
    """個人ごとの作業ステータス"""
    STATUS_CHOICES = [
        ('not_started', '未着手'),
        ('working', '書類待ち'),
        ('completed', '完了'),
    ]

    monthly_process = models.ForeignKey(MonthlyProcess, on_delete=models.CASCADE, related_name='tasks')
    freelancer = models.ForeignKey('Freelancer', on_delete=models.CASCADE)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='not_started', verbose_name="進捗状況")
    working_hours = models.DecimalField(max_length=10, decimal_places=2, max_digits=5, default=0, verbose_name="勤務時間")
    payment_amount = models.IntegerField(default=0, verbose_name="支払金額")
    google_drive_url = models.URLField(blank=True, null=True, verbose_name="資料URL")

    # 追加項目：実稼働時間と計算結果
    actual_working_hours = models.FloatField(default=0.0, verbose_name="実稼働時間")
    calculated_amount = models.IntegerField(default=0, verbose_name="計算請求金額")

    def save(self, *args, **kwargs):
        # 紐付いている個人事業主の精算ルールを取得
        f = self.freelancer
        hours = self.actual_working_hours
        
        # 自動計算ロジック
        if hours == 0:
            self.calculated_amount = 0
        elif hours < f.lower_limit_hours:
            # 下限割れ（控除）： 基準単価 - (不足時間 × 控除単価)
            diff = f.lower_limit_hours - hours
            self.calculated_amount = f.base_unit_price - int(diff * f.deduction_unit_price)
        elif hours > f.upper_limit_hours:
            # 上限超え（超過）： 基準単価 + (超過時間 × 超過単価)
            diff = hours - f.upper_limit_hours
            self.calculated_amount = f.base_unit_price + int(diff * f.overtime_unit_price)
        else:
            # 精算幅内： 基準単価そのまま
            self.calculated_amount = f.base_unit_price
            
        super().save(*args, **kwargs)

    class Meta:
        # 同じ月に同じ人を2回登録できないようにする
        unique_together = ('monthly_process', 'freelancer')

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
