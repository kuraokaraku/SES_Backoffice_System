# system_app/forms.py
from django import forms
from .models import Freelancer, BusinessPartner
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

