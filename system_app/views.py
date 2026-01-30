# system_app/views.py
import os
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import MonthlyProcess, TaskStatus, Freelancer, PurchaseOrder, BusinessPartner, BusinessCard
from .forms import FreelancerForm, TaskStatusForm, BusinessPartnerForm
from django.utils import timezone

from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.contrib.admin.views.decorators import staff_member_required
from .forms import UserEditForm

from django.urls import reverse

from django.http import FileResponse, Http404
#from .services.email_service import search_and_sync_emails # 検索用サービス
from .services.email_service import search_and_save_to_vps

from django.http import HttpResponseForbidden



def index(request):
    return render(request, 'index.html')

@login_required  # ログインしていない人がアクセスしたらログイン画面に飛ばす設定
def menu(request):
    return render(request, 'menu.html')

# ユーザー一覧
def user_list(request):
    # 1. ログインユーザーが管理者(superuser)かどうか判定
    if request.user.is_superuser:
        # 管理者の場合は、全ユーザーを取得
        users = User.objects.all().order_by('-date_joined')
    else:
        # 一般ユーザーの場合は、自分自身のデータのみを取得
        users = User.objects.filter(pk=request.user.pk)

    return render(request, 'user_list.html', {'users': users})


# ユーザー新規登録
@staff_member_required
def user_create(request):
    if request.method == 'POST':
        # 日本語版フォームを使用
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('user_list')
    else:
        # 日本語版フォームを使用
        form = UserCreationForm()
    return render(request, 'user_form.html', {'form': form, 'title': 'ユーザー新規登録'})


def user_edit(request, pk):
    # 管理者でない、かつ、編集対象が自分自身でない場合はアクセス拒否
    if not request.user.is_superuser and request.user.pk != pk:
        return HttpResponseForbidden("自分のプロフィール以外は編集できません。")

    target_user = get_object_or_404(User, pk=pk)

    if request.method == "POST":
        # request_user をフォームに渡す
        form = UserEditForm(request.POST, instance=target_user, request_user=request.user)
        if form.is_valid():
            form.save()
            return redirect('user_list')
    else:
        form = UserEditForm(instance=target_user, request_user=request.user)

    return render(request, 'user_edit.html', {'form': form, 'target_user': target_user})

#統合一覧表示
@login_required
def party_list(request):
    """
    Freelancer / BusinessPartner を同じ一覧で表示する
    フィルタ: ?type=all|freelancer|partner
    """
    filter_type = request.GET.get("type", "all")  # all / freelancer / partner

    rows = []

    # 個人事業主
    if filter_type in ("all", "freelancer"):
        freelancers = Freelancer.objects.all().order_by("-updated_at")
        for f in freelancers:
            # 契約状態
            # contract_start/end がどっちか入ってたら「契約設定あり」扱いにする
            # もう少し厳密にするなら today と比較して "契約中/未開始/終了" にできる
            status = "-"
            if f.contract_start or f.contract_end:
                status = "契約あり"

            rows.append({
                "kind": "個人事業主",
                "kind_key": "freelancer",
                "name": f.name,
                "sub": f.client_name or "",
                "base_unit_price": f.base_unit_price,
                "lower": f.lower_limit_hours,
                "upper": f.upper_limit_hours,
                "status": status,
                "date_label": "更新日",
                "date_value": f.updated_at,
                "detail_url": reverse("freelancer_detail", args=[f.pk]),
                "edit_url": reverse("freelancer_update", args=[f.pk]),
            })

    # 提携パートナー
    if filter_type in ("all", "partner"):
        partners = BusinessPartner.objects.all().order_by("-created_at")
        for p in partners:
            rows.append({
                "kind": "BP",
                "kind_key": "partner",
                "name": p.name,
                "sub": p.contact_person or "",
                "base_unit_price": p.base_unit_price,
                "lower": p.lower_limit_hours,
                "upper": p.upper_limit_hours,
                "status": "稼働中" if p.is_active else "停止中",
                "date_label": "登録日",
                "date_value": p.created_at,
                "detail_url": reverse("partner_detail", args=[p.pk]),
                "edit_url": reverse("partner_edit", args=[p.pk]),
            })

    # 日付で降順（更新日 or 登録日）
    rows.sort(key=lambda r: r["date_value"] or timezone.datetime.min, reverse=True)

    return render(request, "party_list.html", {
        "rows": rows,
        "filter_type": filter_type,
    })
# フリーランサー詳細
@login_required
def freelancer_detail(request, pk):
    f = get_object_or_404(Freelancer, pk=pk)
    return render(request, "freelancer_detail.html", {"f": f})

# BP詳細
@login_required
def partner_detail(request, pk):
    p = get_object_or_404(BusinessPartner, pk=pk)
    return render(request, "partner_detail.html", {"p": p})


# フリーランサー一覧
@login_required
def freelancer_list(request):
    # データベースから全データを取得
    freelancers = Freelancer.objects.all()
    return render(request, 'freelancer_list.html', {'freelancers': freelancers})

@login_required
def freelancer_create(request):
    if request.method == 'POST':
        form = FreelancerForm(request.POST)
        if form.is_valid():
            form.save() # データベースに保存
            return redirect('freelancer_list') # 一覧画面に自動で戻る
    else:
        form = FreelancerForm()
    
    return render(request, 'freelancer_form.html', {'form': form})

# --- 編集処理 ---
@login_required
def freelancer_update(request, pk):
    # ID(pk)に該当するデータを取得、なければ404エラーを出す
    freelancer = get_object_or_404(Freelancer, pk=pk)
    
    if request.method == 'POST':
        # 取得したデータ(instance)を元にフォームを作成
        form = FreelancerForm(request.POST, instance=freelancer)
        if form.is_valid():
            form.save()
            return redirect('freelancer_list')
    else:
        # 既存データが入った状態のフォームを表示
        form = FreelancerForm(instance=freelancer)
    
    return render(request, 'freelancer_form.html', {'form': form, 'update': True})

# --- 削除処理 ---
@login_required
def freelancer_delete(request, pk):
    freelancer = get_object_or_404(Freelancer, pk=pk)
    if request.method == 'POST':
        freelancer.delete()
        return redirect('freelancer_list')
    return render(request, 'freelancer_confirm_delete.html', {'freelancer': freelancer})

# 親：月次一覧画面
@login_required
def monthly_list(request):
    # データベースから全データを取得
    processes = MonthlyProcess.objects.all().order_by('-year_month')
    
    # テンプレートに渡す（左側の 'processes' がHTMLで使う名前になります）
    return render(request, 'monthly_list.html', {'processes': processes})


# 子：その月の個人別進捗画面
@login_required
def monthly_detail(request, pk):
    # 1. 該当する月次プロセスを取得
    monthly_process = get_object_or_404(MonthlyProcess, pk=pk)
    
    # 2. そのプロセスに紐づく「全員分の進捗データ」を取得
    # monthly_process=monthly_process となっているか確認！
    task_statuses = TaskStatus.objects.filter(monthly_process=monthly_process)
    # この月に紐づく全個人の進捗を取得
    return render(request, 'monthly_detail.html', {
        'monthly_process': monthly_process,
        'task_statuses': task_statuses,
    })

@login_required
def create_monthly_batch(request):
    if request.method == 'POST':
        # 現在の年月を取得（例: 2025-01-01）
        now = timezone.now()
        first_day_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # すでにその月のデータがあるか確認、なければ作成
        monthly_process, created = MonthlyProcess.objects.get_or_create(
            year_month=first_day_of_month
        )
        
        # 登録されている全個人事業主を取得
        freelancers = Freelancer.objects.all()
        
        # 各個人事業主の進捗レコードを作成（すでに存在する場合は作成しない）
        for freelancer in freelancers:
            TaskStatus.objects.get_or_create(
                monthly_process=monthly_process,
                freelancer=freelancer
            )
            
        return redirect('monthly_list')
    
    return redirect('monthly_list')


@login_required
def task_update(request, pk):
    task = get_object_or_404(TaskStatus, pk=pk)
    if request.method == 'POST':
        form = TaskStatusForm(request.POST, instance=task)
        if form.is_valid():
            form.save()
            # 更新後、元の月次詳細画面に戻る
            return redirect('monthly_detail', pk=task.monthly_process.pk)
    else:
        form = TaskStatusForm(instance=task)
    
    return render(request, 'task_form.html', {'form': form, 'task': task})

# 注文書
# 1. 一覧表示
def purchase_order_list(request):
    orders = PurchaseOrder.objects.all().order_by('-received_at')
    return render(request, 'purchase_order_list.html', {'purchase_orders': orders})

# 2. 検索
def purchase_search_view(request):
    # 両方のマスターから名前のリストを取得
    partners = BusinessPartner.objects.filter(is_active=True)
    freelancers = Freelancer.objects.filter(is_active=True)

    context = {
        'partners': partners,
        'freelancers': freelancers,
    }
    return render(request, 'search_order.html', context)

# 3. ダウンロード処理
def purchase_download(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
    if not order.file:
        raise Http404("ファイルが見つかりません")
    
    order.download_count += 1
    order.save()
    
    return FileResponse(open(order.file.path, 'rb'), as_attachment=True)

# 4. 削除処理
def purchase_delete(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
    order.delete()
    return redirect('purchase_order_list')

# 5. 同期実行の橋渡し（email_serviceを呼び出す）
def sync_mail_view(request):
    # ここでメール同期ロジックを呼び出す（後ほど作成）
    # sync_purchase_orders_from_mail() 
    return redirect('purchase_order_list')

def download_purchase_order(request, pk):
    po = get_object_or_404(PurchaseOrder, pk=pk)
    # カウントを増やす
    po.download_count += 1
    po.save()
    # ファイルを返す
    return FileResponse(open(po.file.path, 'rb'), as_attachment=True)

def purchase_search_view(request):
    print (f"-----  purchase_search_view start.")
    # 1. 選択肢として表示するマスタデータを取得
    freelancers_list = Freelancer.objects.all().values_list('name', flat=True)
    #partners = BusinessPartner.objects.all().values_list('name', flat=True)
    # 選択肢を1つのリストにまとめる（重複削除）
    client_choices = sorted(list(set(list(freelancers_list))))

    partners = BusinessPartner.objects.all()
    freelancers = Freelancer.objects.all()


    if request.method == 'POST':
        # 2. フォームから送信された条件を取得
        client_name = request.POST.get('client_name')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')

        # 3. 条件をもとにメール検索を実行（後述のサービスを呼び出し）
        result_message = search_and_save_to_vps(client_name, start_date, end_date)
        # 完了後、一覧画面へ（メッセージを持っていく）
        return render(request, 'purchase_order_list.html', {
            'purchase_orders': PurchaseOrder.objects.all().order_by('-received_at'),
            'message': result_message
        })

    return render(request, 'purchase_search.html', {
        'client_choices': client_choices, # TODO あとで整理する
        'partners': partners,
        'freelancers': freelancers,
    })

# 提携パートナー
# 一覧表示
def partner_list(request):
    partners = BusinessPartner.objects.all().order_by('-created_at')
    return render(request, 'partner_list.html', {'partners': partners})

# 詳細/編集（簡易版）
def partner_detail(request, pk=None):
    if pk:
        partner = get_object_or_404(BusinessPartner, pk=pk)
    else:
        partner = None
    
    if request.method == "POST":
        # 本来はFormクラスを使うのがベストですが、一旦簡易的に取得
        name = request.POST.get('name')
        base_unit_price = request.POST.get('base_unit_price')
        # ... 他の項目も同様に取得 ...
        
        BusinessPartner.objects.update_or_create(
            pk=pk,
            defaults={
                'name': name,
                'base_unit_price': base_unit_price,
                # ... 
            }
        )
        return redirect('partner_list')
        
    return render(request, 'partner_detail.html', {'partner': partner})



def business_card_list(request):
    cards = BusinessCard.objects.all().order_by('-created_at')
    return render(request, 'business_card_list.html', {'cards': cards})