# system_app/views.py
import os
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import MonthlyProcess, TaskStatus, Freelancer, PurchaseOrder, BusinessPartner, BusinessCard, Assignment, ServiceContract, ContactEntity
from .forms import FreelancerForm, TaskStatusForm, BusinessPartnerForm, ContactEntityForm
from django.utils import timezone

from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.contrib.admin.views.decorators import staff_member_required
from .forms import UserEditForm

from django.urls import reverse
from django.db.models import Q

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
    Assignment ベースで人材一覧を表示
    """
    from datetime import date
    today = date.today()

    # 検索・フィルタ
    search_name = request.GET.get("search", "").strip()
    filter_type = request.GET.get("worker_type", "")

    assignments = Assignment.objects.select_related(
        'worker_entity', 'sales_owner_entity'
    ).prefetch_related('contracts').all()

    # 名前検索
    if search_name:
        assignments = assignments.filter(worker_entity__name__icontains=search_name)

    # worker_type フィルタ
    if filter_type:
        assignments = assignments.filter(worker_entity__worker_type=filter_type)

    rows = []
    for a in assignments:
        # 現行の契約を取得（valid_to が NULL または今日以降）
        current_contract = a.contracts.filter(
            Q(valid_to__isnull=True) | Q(valid_to__gte=today)
        ).filter(
            Q(valid_from__isnull=True) | Q(valid_from__lte=today)
        ).first()

        # 稼働中判定
        is_active = current_contract is not None

        # 単価
        unit_price = current_contract.unit_price if current_contract else None

        rows.append({
            "id": a.id,
            "name": a.worker_entity.name if a.worker_entity else "-",
            "worker_type": a.worker_entity.worker_type if a.worker_entity else "-",
            "sales_owner": a.sales_owner_entity.name if a.sales_owner_entity else "-",
            "is_active": is_active,
            "unit_price": unit_price,
            "project_name": a.project_name or "-",
        })

    # worker_type の選択肢を取得
    worker_types = ContactEntity.objects.filter(
        kind="PERSON", worker_type__isnull=False
    ).values_list('worker_type', flat=True).distinct()

    return render(request, "party_list.html", {
        "rows": rows,
        "search_name": search_name,
        "filter_type": filter_type,
        "worker_types": worker_types,
    })


@login_required
def contact_entity_create(request):
    """新規人材+アサインメント+契約 一括登録"""
    from .models import EntityContactPerson

    if request.method == 'POST':
        form = ContactEntityForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data

            # 1. 人材（worker）作成
            worker = ContactEntity.objects.create(
                kind='PERSON',
                name=data['name'],
                worker_type=data['worker_type'],
                email=data['email'] or None,
                phone=data['phone'] or None,
            )

            # 2. 上流会社・担当者作成（任意）
            upstream_entity = None
            upstream_contact = None
            if data.get('upstream_company_name'):
                upstream_entity = ContactEntity.objects.create(
                    kind='COMPANY',
                    name=data['upstream_company_name'],
                )
                if data.get('upstream_contact_name'):
                    upstream_contact = EntityContactPerson.objects.create(
                        corporate_entity=upstream_entity,
                        name=data['upstream_contact_name'],
                        email=data.get('upstream_contact_email') or None,
                        phone=data.get('upstream_contact_phone') or None,
                    )

            # 3. 下流会社・担当者作成（任意）
            downstream_entity = None
            downstream_contact = None
            if data.get('downstream_company_name'):
                downstream_entity = ContactEntity.objects.create(
                    kind='COMPANY',
                    name=data['downstream_company_name'],
                )
                if data.get('downstream_contact_name'):
                    downstream_contact = EntityContactPerson.objects.create(
                        corporate_entity=downstream_entity,
                        name=data['downstream_contact_name'],
                        email=data.get('downstream_contact_email') or None,
                        phone=data.get('downstream_contact_phone') or None,
                    )

            # 4. 営業担当作成（任意）
            sales_owner = None
            if data.get('sales_owner_name'):
                sales_owner = ContactEntity.objects.create(
                    kind='PERSON',
                    name=data['sales_owner_name'],
                )

            # 5. Assignment作成
            # upstream/downstreamが無い場合はworker自身を設定（必須フィールドのため）
            assignment = Assignment.objects.create(
                worker_entity=worker,
                sales_owner_entity=sales_owner or worker,
                upstream_entity=upstream_entity or worker,
                upstream_contact_person=upstream_contact,
                downstream_entity=downstream_entity or worker,
                downstream_contact_person=downstream_contact,
                project_name=data.get('project_name') or None,
                timesheet_collection_method=data.get('timesheet_collection_method') or None,
                order_period_start_ym=data.get('order_period_start_ym') or None,
                order_period_end_ym=data.get('order_period_end_ym') or None,
                notes=data.get('notes') or None,
            )

            # 6. ServiceContract作成
            ServiceContract.objects.create(
                assignment=assignment,
                unit_price=data['unit_price'],
                valid_from=data.get('valid_from'),
                valid_to=data.get('valid_to'),
                lower_limit_hour=data.get('lower_limit_hour'),
                upper_limit_hours=data.get('upper_limit_hours'),
                deduction_unit_price=data.get('deduction_unit_price'),
                excess_unit_price=data.get('excess_unit_price'),
            )

            return redirect('party_list')
    else:
        form = ContactEntityForm()
    return render(request, 'contact_entity_form.html', {'form': form})


@login_required
def assignment_detail(request, pk):
    """アサインメント詳細"""
    from datetime import date
    today = date.today()

    assignment = get_object_or_404(
        Assignment.objects.select_related(
            'worker_entity', 'sales_owner_entity',
            'upstream_entity', 'downstream_entity',
            'upstream_contact_person', 'downstream_contact_person'
        ).prefetch_related('contracts'),
        pk=pk
    )

    # 現行契約
    current_contract = assignment.contracts.filter(
        Q(valid_to__isnull=True) | Q(valid_to__gte=today)
    ).filter(
        Q(valid_from__isnull=True) | Q(valid_from__lte=today)
    ).first()

    return render(request, 'assignment_detail.html', {
        'assignment': assignment,
        'current_contract': current_contract,
    })


@login_required
def assignment_edit(request, pk):
    """アサインメント編集"""
    from .models import EntityContactPerson
    from datetime import date
    today = date.today()

    assignment = get_object_or_404(
        Assignment.objects.select_related(
            'worker_entity', 'sales_owner_entity',
            'upstream_entity', 'downstream_entity',
            'upstream_contact_person', 'downstream_contact_person'
        ).prefetch_related('contracts'),
        pk=pk
    )

    # 現行契約
    current_contract = assignment.contracts.filter(
        Q(valid_to__isnull=True) | Q(valid_to__gte=today)
    ).filter(
        Q(valid_from__isnull=True) | Q(valid_from__lte=today)
    ).first()

    if request.method == 'POST':
        form = ContactEntityForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data

            # 1. 人材（worker）更新
            worker = assignment.worker_entity
            worker.name = data['name']
            worker.worker_type = data['worker_type']
            worker.email = data['email'] or None
            worker.phone = data['phone'] or None
            worker.save()

            # 2. 営業担当更新
            if data.get('sales_owner_name'):
                if assignment.sales_owner_entity and assignment.sales_owner_entity != worker:
                    assignment.sales_owner_entity.name = data['sales_owner_name']
                    assignment.sales_owner_entity.save()
                else:
                    sales_owner = ContactEntity.objects.create(
                        kind='PERSON',
                        name=data['sales_owner_name'],
                    )
                    assignment.sales_owner_entity = sales_owner

            # 3. 上流更新
            if data.get('upstream_company_name'):
                if assignment.upstream_entity and assignment.upstream_entity != worker:
                    assignment.upstream_entity.name = data['upstream_company_name']
                    assignment.upstream_entity.save()
                else:
                    assignment.upstream_entity = ContactEntity.objects.create(
                        kind='COMPANY',
                        name=data['upstream_company_name'],
                    )
                if data.get('upstream_contact_name'):
                    if assignment.upstream_contact_person:
                        assignment.upstream_contact_person.name = data['upstream_contact_name']
                        assignment.upstream_contact_person.email = data.get('upstream_contact_email') or None
                        assignment.upstream_contact_person.phone = data.get('upstream_contact_phone') or None
                        assignment.upstream_contact_person.save()
                    else:
                        assignment.upstream_contact_person = EntityContactPerson.objects.create(
                            corporate_entity=assignment.upstream_entity,
                            name=data['upstream_contact_name'],
                            email=data.get('upstream_contact_email') or None,
                            phone=data.get('upstream_contact_phone') or None,
                        )

            # 4. 下流更新
            if data.get('downstream_company_name'):
                if assignment.downstream_entity and assignment.downstream_entity != worker:
                    assignment.downstream_entity.name = data['downstream_company_name']
                    assignment.downstream_entity.save()
                else:
                    assignment.downstream_entity = ContactEntity.objects.create(
                        kind='COMPANY',
                        name=data['downstream_company_name'],
                    )
                if data.get('downstream_contact_name'):
                    if assignment.downstream_contact_person:
                        assignment.downstream_contact_person.name = data['downstream_contact_name']
                        assignment.downstream_contact_person.email = data.get('downstream_contact_email') or None
                        assignment.downstream_contact_person.phone = data.get('downstream_contact_phone') or None
                        assignment.downstream_contact_person.save()
                    else:
                        assignment.downstream_contact_person = EntityContactPerson.objects.create(
                            corporate_entity=assignment.downstream_entity,
                            name=data['downstream_contact_name'],
                            email=data.get('downstream_contact_email') or None,
                            phone=data.get('downstream_contact_phone') or None,
                        )

            # 5. Assignment更新
            assignment.project_name = data.get('project_name') or None
            assignment.timesheet_collection_method = data.get('timesheet_collection_method') or None
            assignment.order_period_start_ym = data.get('order_period_start_ym') or None
            assignment.order_period_end_ym = data.get('order_period_end_ym') or None
            assignment.notes = data.get('notes') or None
            assignment.save()

            # 6. 契約更新
            if current_contract:
                current_contract.unit_price = data['unit_price']
                current_contract.valid_from = data.get('valid_from')
                current_contract.valid_to = data.get('valid_to')
                current_contract.lower_limit_hour = data.get('lower_limit_hour')
                current_contract.upper_limit_hours = data.get('upper_limit_hours')
                current_contract.deduction_unit_price = data.get('deduction_unit_price')
                current_contract.excess_unit_price = data.get('excess_unit_price')
                current_contract.save()
            else:
                ServiceContract.objects.create(
                    assignment=assignment,
                    unit_price=data['unit_price'],
                    valid_from=data.get('valid_from'),
                    valid_to=data.get('valid_to'),
                    lower_limit_hour=data.get('lower_limit_hour'),
                    upper_limit_hours=data.get('upper_limit_hours'),
                    deduction_unit_price=data.get('deduction_unit_price'),
                    excess_unit_price=data.get('excess_unit_price'),
                )

            return redirect('assignment_detail', pk=pk)
    else:
        # 初期値設定
        initial = {
            'name': assignment.worker_entity.name if assignment.worker_entity else '',
            'worker_type': assignment.worker_entity.worker_type if assignment.worker_entity else '',
            'email': assignment.worker_entity.email if assignment.worker_entity else '',
            'phone': assignment.worker_entity.phone if assignment.worker_entity else '',
            'sales_owner_name': assignment.sales_owner_entity.name if assignment.sales_owner_entity and assignment.sales_owner_entity != assignment.worker_entity else '',
            'project_name': assignment.project_name or '',
            'timesheet_collection_method': assignment.timesheet_collection_method or '',
            'order_period_start_ym': assignment.order_period_start_ym or '',
            'order_period_end_ym': assignment.order_period_end_ym or '',
            'notes': assignment.notes or '',
        }
        # 契約情報
        if current_contract:
            initial.update({
                'unit_price': current_contract.unit_price,
                'valid_from': current_contract.valid_from,
                'valid_to': current_contract.valid_to,
                'lower_limit_hour': current_contract.lower_limit_hour,
                'upper_limit_hours': current_contract.upper_limit_hours,
                'deduction_unit_price': current_contract.deduction_unit_price,
                'excess_unit_price': current_contract.excess_unit_price,
            })
        # 上流
        if assignment.upstream_entity and assignment.upstream_entity != assignment.worker_entity:
            initial['upstream_company_name'] = assignment.upstream_entity.name
        if assignment.upstream_contact_person:
            initial['upstream_contact_name'] = assignment.upstream_contact_person.name
            initial['upstream_contact_email'] = assignment.upstream_contact_person.email or ''
            initial['upstream_contact_phone'] = assignment.upstream_contact_person.phone or ''
        # 下流
        if assignment.downstream_entity and assignment.downstream_entity != assignment.worker_entity:
            initial['downstream_company_name'] = assignment.downstream_entity.name
        if assignment.downstream_contact_person:
            initial['downstream_contact_name'] = assignment.downstream_contact_person.name
            initial['downstream_contact_email'] = assignment.downstream_contact_person.email or ''
            initial['downstream_contact_phone'] = assignment.downstream_contact_person.phone or ''

        form = ContactEntityForm(initial=initial)

    return render(request, 'assignment_edit.html', {'form': form, 'assignment': assignment})


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