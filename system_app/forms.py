# system_app/forms.py
from django import forms
from .models import Freelancer, BusinessPartner, ContactEntity
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm

class FreelancerForm(forms.ModelForm):
    class Meta:
        model = Freelancer
        fields = '__all__'  # モデルにある項目をすべて自動で使う設定

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            # 日付入力欄だけカレンダー形式にする
            if field.label in ["開始日", "終了日"]:
                field.widget = forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
            else:
                field.widget.attrs.update({'class': 'form-control'})

# system_app/forms.py
from .models import TaskStatus

class TaskStatusForm(forms.ModelForm):
    class Meta:
        model = TaskStatus
        fields = ['timesheet_status', 'invoice_status', 'purchase_order_status', 'actual_hours']
        widgets = {
            'timesheet_status': forms.Select(attrs={'class': 'form-select'}),
            'invoice_status': forms.Select(attrs={'class': 'form-select'}),
            'purchase_order_status': forms.Select(attrs={'class': 'form-select'}),
            'actual_hours': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }


class UserCreationForm(UserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 全フィールドにBootstrapのクラスを一括適用
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'
        
        # ユーザー名のヘルプテキストを日本語に上書き
        self.fields['username'].help_text = (
            "必須項目です。150文字以内の半角英数字、および「@/./+/-/_」が使用可能です。"
        )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username",) # 必要に応じて "email" なども追加可能

class UserEditForm(forms.ModelForm):
    new_password = forms.CharField(
        label="新しいパスワード (変更する場合のみ)",
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '未入力なら変更されません'})
    )

    class Meta:
        model = User
        fields = ['username', 'is_active']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        # Viewから渡される「操作しているユーザー」を取得
        self.request_user = kwargs.pop('request_user', None)
        super().__init__(*args, **kwargs)

        # 操作ユーザーが管理者(is_superuser)でない場合、is_activeを隠す
        if self.request_user and not self.request_user.is_superuser:
            self.fields.pop('is_active')

    def save(self, commit=True):
        user = super().save(commit=False)
        new_password = self.cleaned_data.get("new_password")
        if new_password:
            user.set_password(new_password)
        if commit:
            user.save()
        return user

class BusinessPartnerForm(forms.ModelForm):
    class Meta:
        model = BusinessPartner
        fields = [
            'name', 'contact_person', 'base_unit_price',
            'lower_limit_hours', 'upper_limit_hours',
            'overtime_unit_price', 'deduction_unit_price', 'is_active'
        ]
        # デザイン（Bootstrap）を適用するための設定
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '株式会社〇〇'}),
            'contact_person': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '田中 太郎'}),
            'base_unit_price': forms.NumberInput(attrs={'class': 'form-control'}),
            'lower_limit_hours': forms.NumberInput(attrs={'class': 'form-control'}),
            'upper_limit_hours': forms.NumberInput(attrs={'class': 'form-control'}),
            'overtime_unit_price': forms.NumberInput(attrs={'class': 'form-control'}),
            'deduction_unit_price': forms.NumberInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class ContactEntityForm(forms.Form):
    """人材+アサインメント+契約 一括登録フォーム"""
    WORKER_TYPE_CHOICES = [
        ('', '-- 選択 --'),
        ('フリーランス', 'フリーランス'),
        ('BP', 'BP'),
        ('正社員', '正社員'),
        ('契約社員', '契約社員'),
    ]

    # --- 人材情報 ---
    name = forms.CharField(
        label='氏名', max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '氏名'})
    )
    worker_type = forms.ChoiceField(
        label='種別', choices=WORKER_TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    email = forms.EmailField(
        label='メールアドレス', required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@example.com'})
    )
    phone = forms.CharField(
        label='電話番号', max_length=50, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '090-xxxx-xxxx'})
    )

    # --- 案件情報 ---
    sales_owner_name = forms.CharField(
        label='営業担当', max_length=255, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '営業担当者名'})
    )
    project_name = forms.CharField(
        label='案件名', max_length=255, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '案件名'})
    )
    order_period_start_ym = forms.DateField(
        label='発注期間開始', required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    order_period_end_ym = forms.DateField(
        label='発注期間終了', required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    notes = forms.CharField(
        label='備考', required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3})
    )
    is_active = forms.BooleanField(
        label='稼働中', required=False, initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    # --- 契約情報 ---
    unit_price = forms.IntegerField(
        label='単価（円）',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '500000'})
    )
    is_fixed_fee = forms.BooleanField(
        label='固定報酬', required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_is_fixed_fee'})
    )
    travel_expense_included = forms.BooleanField(
        label='交通費込み', required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    valid_from = forms.DateField(
        label='契約開始日', required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    valid_to = forms.DateField(
        label='契約終了日', required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    lower_limit_hour = forms.DecimalField(
        label='精算下限時間', required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '140', 'step': '0.5'})
    )
    upper_limit_hours = forms.DecimalField(
        label='精算上限時間', required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '180', 'step': '0.5'})
    )
    deduction_unit_price = forms.IntegerField(
        label='控除単価（円）', required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '3000'})
    )
    excess_unit_price = forms.IntegerField(
        label='超過単価（円）', required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '3500'})
    )
    settlement_unit_minutes = forms.IntegerField(
        label='精算時間単位（分）', required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '60'})
    )
    upstream_timesheet_collection_method = forms.CharField(
        label='勤務表回収手段', max_length=100, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'メール / LINE など'})
    )
    downstream_timesheet_collection_method = forms.CharField(
        label='勤務表回収手段', max_length=100, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'メール / LINE など'})
    )
    upstream_payment_terms = forms.IntegerField(
        label='上位 支払いサイト（日）', required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '30'})
    )
    downstream_payment_terms = forms.IntegerField(
        label='下位 支払いサイト（日）', required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '30'})
    )
    bank_holiday_handling = forms.CharField(
        label='金融機関休業日の場合', max_length=100, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '翌営業日払い'})
    )
    downstream_bank_holiday_handling = forms.CharField(
        label='金融機関休業日の場合（下位）', max_length=100, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '翌営業日払い'})
    )
    timesheet_due_date = forms.DateField(
        label='勤務表締め日', required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )

    # --- 下位契約条件 ---
    downstream_unit_price = forms.IntegerField(
        label='下位単価（円）', required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '450000'})
    )
    downstream_is_fixed_fee = forms.BooleanField(
        label='下位固定報酬', required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'id_downstream_is_fixed_fee'})
    )
    downstream_lower_limit_hour = forms.DecimalField(
        label='下位精算下限時間', required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '140', 'step': '0.5'})
    )
    downstream_upper_limit_hours = forms.DecimalField(
        label='下位精算上限時間', required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '180', 'step': '0.5'})
    )
    downstream_deduction_unit_price = forms.IntegerField(
        label='下位控除単価（円）', required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '3000'})
    )
    downstream_excess_unit_price = forms.IntegerField(
        label='下位超過単価（円）', required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '3500'})
    )
    downstream_settlement_unit_minutes = forms.IntegerField(
        label='下位精算時間単位（分）', required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '60'})
    )

    # --- 上位（発注元）---
    upstream_company_name = forms.CharField(
        label='会社名', max_length=255, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '株式会社〇〇'})
    )
    upstream_address = forms.CharField(
        label='会社住所', required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '東京都...'})
    )
    upstream_mailing_address = forms.CharField(
        label='送付先住所', required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '会社住所と異なる場合'})
    )
    upstream_company_phone = forms.CharField(
        label='会社電話番号', max_length=50, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '03-xxxx-xxxx'})
    )
    upstream_contact_name = forms.CharField(
        label='担当者名', max_length=255, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '担当者名'})
    )
    # upstream メールは templates で動的に管理（ContactEmail テーブル）
    upstream_contact_phone = forms.CharField(
        label='担当者電話', max_length=50, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    upstream_line_available = forms.BooleanField(
        label='LINE連絡可', required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    # --- 下位（発注先）---
    downstream_company_name = forms.CharField(
        label='会社名', max_length=255, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '株式会社〇〇'})
    )
    downstream_address = forms.CharField(
        label='会社住所', required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '東京都...'})
    )
    downstream_mailing_address = forms.CharField(
        label='送付先住所', required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '会社住所と異なる場合'})
    )
    downstream_company_phone = forms.CharField(
        label='会社電話番号', max_length=50, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '03-xxxx-xxxx'})
    )
    downstream_has_invoice_registration = forms.BooleanField(
        label='インボイス登録済み', required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    downstream_contact_name = forms.CharField(
        label='担当者名', max_length=255, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '担当者名'})
    )
    # downstream メールは templates で動的に管理（ContactEmail テーブル）
    downstream_contact_phone = forms.CharField(
        label='担当者電話', max_length=50, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    downstream_line_available = forms.BooleanField(
        label='LINE連絡可', required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
