# system_app/views.py
import json
import os
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import MonthlyProcess, TaskStatus, Freelancer, PurchaseOrder, BusinessPartner, BusinessCard, Assignment, ServiceContract, ContactEntity, ContactEmail, Invoice, InvoiceLine, Timesheet, InvoicePayment, Payable, PayablePayment, SalesProject, SalesDeal, SalesAction, SalesStatusChange
from .forms import FreelancerForm, TaskStatusForm, BusinessPartnerForm, ContactEntityForm, SalesDealCreateForm, SalesDealEditForm, SalesActionForm
from django.utils import timezone

from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.contrib.admin.views.decorators import staff_member_required
from .forms import UserEditForm

from django.urls import reverse
from django.db.models import Q

from django.http import FileResponse, Http404, JsonResponse
from django.views.decorators.http import require_POST
#from .services.email_service import search_and_sync_emails # 検索用サービス
from .services.email_service import search_and_save_to_vps

from django.http import HttpResponseForbidden
from .models import EntityContactPerson


@login_required
def contact_entity_search(request):
    """JSON API: ContactEntity 検索（重複除外済み）"""
    kind = request.GET.get('kind', '').upper()
    if kind not in ('PERSON', 'COMPANY'):
        return JsonResponse({'error': 'kind must be PERSON or COMPANY'}, status=400)

    entities = ContactEntity.objects.filter(kind=kind).order_by('name', 'id')

    if kind == 'PERSON':
        seen = set()
        data = []
        for e in entities:
            key = (e.name, e.worker_type or '', e.email or '')
            if key in seen:
                continue
            seen.add(key)
            data.append({
                'id': e.id,
                'name': e.name,
                'worker_type': e.worker_type or '',
                'email': e.email or '',
                'phone': e.phone or '',
            })
    else:
        seen = set()
        data = []
        for e in entities:
            key = (e.name, e.company_phone or '', e.address or '')
            if key in seen:
                continue
            seen.add(key)
            contact_people = []
            for cp in e.contact_people.all():
                emails = [
                    {'email': ce.email, 'description': ce.description}
                    for ce in cp.extra_emails.all()
                ]
                contact_people.append({
                    'id': cp.id,
                    'name': cp.name,
                    'phone': cp.phone or '',
                    'line_available': cp.line_available,
                    'emails': emails,
                })
            data.append({
                'id': e.id,
                'name': e.name,
                'address': e.address or '',
                'mailing_address': e.mailing_address or '',
                'company_phone': e.company_phone or '',
                'has_invoice_registration': e.has_invoice_registration,
                'contact_people': contact_people,
            })

    return JsonResponse(data, safe=False)


def _save_contact_emails(request, prefix, contact_person):
    """POSTの動的メールフィールドをContactEmailに保存"""
    contact_person.extra_emails.all().delete()
    emails = request.POST.getlist(f'{prefix}_emails[]')
    descs = request.POST.getlist(f'{prefix}_email_descs[]')
    for email, desc in zip(emails, descs):
        email = email.strip()
        if email:
            ContactEmail.objects.create(
                contact_person=contact_person,
                email=email,
                description=desc.strip(),
            )


def index(request):
    return render(request, 'index.html')

@login_required
def menu(request):
    return redirect('dashboard')


def _get_trend_data(end_ym, months=6):
    """end_ym を最終月として過去 months ヶ月分の売上/支払/粗利を返す"""
    from django.db.models import Sum as _S
    from django.db.models.functions import Coalesce as _C
    from django.db.models import Value, DecimalField as _DF

    y, m = int(end_ym[:4]), int(end_ym[4:])
    result = []
    for _ in range(months):
        ym = f"{y}{m:02d}"
        rev = (
            Invoice.objects.filter(billing_ym=ym).exclude(status='cancelled')
            .aggregate(t=_C(_S('total_amount'), Value(0), output_field=_DF()))['t']
        )
        cost = (
            Payable.objects.filter(billing_ym=ym).exclude(status='cancelled')
            .aggregate(t=_C(_S('total_amount'), Value(0), output_field=_DF()))['t']
        )
        profit = rev - cost
        result.append({
            'ym': ym,
            'label': f"{m}月",
            'revenue': int(rev),
            'cost': int(cost),
            'profit': int(profit),
        })
        m -= 1
        if m == 0:
            m = 12
            y -= 1

    result.reverse()
    return result


@login_required
def dashboard(request):
    import json
    from datetime import date, timedelta
    from django.db.models import Q

    today = date.today()
    ym = request.GET.get('ym', '')
    if not ym or len(ym) != 6:
        ym = today.strftime('%Y%m')

    year = int(ym[:4])
    month = int(ym[4:6])

    if month == 1:
        prev_ym = f"{year - 1}12"
    else:
        prev_ym = f"{year}{month - 1:02d}"
    if month == 12:
        next_ym = f"{year + 1}01"
    else:
        next_ym = f"{year}{month + 1:02d}"

    # --- (1) 勤務表：未回収 ---
    active_assignment_ids = set(
        Assignment.objects.filter(is_active=True).values_list('id', flat=True)
    )
    submitted_ids = set(
        Timesheet.objects.filter(billing_ym=ym).values_list('assignment_id', flat=True)
    )
    ts_pending_count = len(active_assignment_ids - submitted_ids)

    # --- (2) 請求：未送付 ---
    inv_unsent_count = Invoice.objects.filter(
        billing_ym=ym, status__in=['draft', 'final']
    ).count()

    # --- (3) 請求：入金待ち ---
    inv_sent_count = Invoice.objects.filter(
        billing_ym=ym, status='sent'
    ).count()

    # --- (3b) 入金：今月支払期日で未入金 ---
    from django.db.models import Sum as _Sum
    from django.db.models.functions import Coalesce as _Coalesce
    ar_unpaid_count = (
        Invoice.objects
        .filter(status='sent', due_date__year=year, due_date__month=month)
        .annotate(
            _paid=_Coalesce(_Sum('payments__amount'), Value(0), output_field=DjDecimalField())
        )
        .filter(_paid__lt=F('total_amount'))
        .count()
    )

    # --- (4)(5) 契約：30日/60日以内に終了 ---
    contracts_end_30 = ServiceContract.objects.filter(
        valid_to__gte=today,
        valid_to__lte=today + timedelta(days=30),
    ).count()
    contracts_end_60 = ServiceContract.objects.filter(
        valid_to__gte=today,
        valid_to__lte=today + timedelta(days=60),
    ).count()

    # --- (6) 営業：停滞商談 ---
    from datetime import datetime
    stagnant_threshold = timezone.now() - timedelta(days=7)
    sales_stagnant_count = SalesDeal.objects.filter(
        status__in=['received', 'working', 'proposed', 'waiting'],
    ).filter(
        Q(last_action_at__isnull=True, created_at__lt=stagnant_threshold) |
        Q(last_action_at__lt=stagnant_threshold)
    ).count()

    # --- (7) キャッシュフロー KPI ---
    from django.db.models import Sum as _Sum2
    monthly_revenue = (
        Invoice.objects
        .filter(billing_ym=ym)
        .exclude(status='cancelled')
        .aggregate(total=_Coalesce(_Sum2('total_amount'), Value(0), output_field=DjDecimalField()))
    )['total']

    monthly_cost = (
        Payable.objects
        .filter(billing_ym=ym)
        .exclude(status='cancelled')
        .aggregate(total=_Coalesce(_Sum2('total_amount'), Value(0), output_field=DjDecimalField()))
    )['total']

    monthly_gross_profit = monthly_revenue - monthly_cost
    monthly_gross_profit_rate = (
        round(monthly_gross_profit / monthly_revenue * 100, 1)
        if monthly_revenue else 0
    )

    ap_unpaid_count = (
        Payable.objects
        .exclude(status='cancelled')
        .filter(due_date__year=year, due_date__month=month)
        .annotate(
            _paid=_Coalesce(_Sum2('payments__amount'), Value(0), output_field=DjDecimalField())
        )
        .filter(_paid__lt=F('total_amount'))
        .count()
    )

    # --- 6ヶ月トレンドデータ ---
    trend_data = _get_trend_data(ym, months=6)

    return render(request, 'dashboard.html', {
        'ym': ym,
        'year': year,
        'month': month,
        'prev_ym': prev_ym,
        'next_ym': next_ym,
        'ts_pending_count': ts_pending_count,
        'inv_unsent_count': inv_unsent_count,
        'inv_sent_count': inv_sent_count,
        'ar_unpaid_count': ar_unpaid_count,
        'contracts_end_30': contracts_end_30,
        'contracts_end_60': contracts_end_60,
        'sales_stagnant_count': sales_stagnant_count,
        'monthly_revenue': monthly_revenue,
        'monthly_cost': monthly_cost,
        'monthly_gross_profit': monthly_gross_profit,
        'monthly_gross_profit_rate': monthly_gross_profit_rate,
        'ap_unpaid_count': ap_unpaid_count,
        'trend_data_json': json.dumps(trend_data),
    })


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
    show_inactive = request.GET.get("show_inactive", "") == "1"

    assignments = Assignment.objects.select_related(
        'worker_entity', 'sales_owner_entity',
        'upstream_entity', 'upstream_contact_person',
        'downstream_entity', 'downstream_contact_person',
    ).prefetch_related('contracts').all()

    # デフォルトは稼働中のみ表示
    if not show_inactive:
        assignments = assignments.filter(is_active=True)

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

        # 契約情報
        unit_price = current_contract.unit_price if current_contract else None
        contract_from = current_contract.valid_from if current_contract else None
        contract_to = current_contract.valid_to if current_contract else None
        is_fixed_fee = current_contract.is_fixed_fee if current_contract else False
        lower_limit = current_contract.lower_limit_hour if current_contract else None
        upper_limit = current_contract.upper_limit_hours if current_contract else None

        # 上位（発注元）
        upstream_name = ""
        if a.upstream_entity and a.upstream_entity != a.worker_entity:
            upstream_name = a.upstream_entity.name
        upstream_contact = ""
        if a.upstream_contact_person:
            upstream_contact = a.upstream_contact_person.name

        # 下位（所属会社）
        downstream_name = ""
        if a.downstream_entity and a.downstream_entity != a.worker_entity:
            downstream_name = a.downstream_entity.name

        # 契約終了間近判定
        contract_ending_soon = False
        if contract_to and (contract_to - today).days <= 30:
            contract_ending_soon = True

        rows.append({
            "id": a.id,
            "name": a.worker_entity.name if a.worker_entity else "-",
            "worker_type": a.worker_entity.worker_type if a.worker_entity else "-",
            "sales_owner": a.sales_owner_entity.name if a.sales_owner_entity else "-",
            "is_active": a.is_active,
            "unit_price": unit_price,
            "is_fixed_fee": is_fixed_fee,
            "lower_limit": lower_limit,
            "upper_limit": upper_limit,
            "project_name": a.project_name or "-",
            "contract_from": contract_from,
            "contract_to": contract_to,
            "contract_ending_soon": contract_ending_soon,
            "upstream_name": upstream_name,
            "upstream_contact": upstream_contact,
            "downstream_name": downstream_name,
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
        "show_inactive": show_inactive,
    })


@login_required
def contact_entity_create(request):
    """新規人材+アサインメント+契約 一括登録"""

    if request.method == 'POST':
        form = ContactEntityForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data

            # 1. 人材（worker）: 既存 or 新規
            existing_worker_id = request.POST.get('existing_worker_id')
            if existing_worker_id:
                worker = get_object_or_404(ContactEntity, pk=existing_worker_id, kind='PERSON')
            else:
                worker = ContactEntity.objects.create(
                    kind='PERSON',
                    name=data['name'],
                    worker_type=data['worker_type'],
                    email=data['email'] or None,
                    phone=data['phone'] or None,
                )

            # 2. 上位会社・担当者: 既存 or 新規
            upstream_entity = None
            upstream_contact = None
            existing_upstream_id = request.POST.get('existing_upstream_id')
            if existing_upstream_id:
                upstream_entity = get_object_or_404(ContactEntity, pk=existing_upstream_id, kind='COMPANY')
                existing_upstream_contact_id = request.POST.get('existing_upstream_contact_id')
                if existing_upstream_contact_id:
                    upstream_contact = get_object_or_404(EntityContactPerson, pk=existing_upstream_contact_id)
                elif data.get('upstream_contact_name'):
                    upstream_contact = EntityContactPerson.objects.create(
                        corporate_entity=upstream_entity,
                        name=data['upstream_contact_name'],
                        phone=data.get('upstream_contact_phone') or None,
                        line_available=data.get('upstream_line_available', False),
                    )
                    _save_contact_emails(request, 'upstream', upstream_contact)
            elif data.get('upstream_company_name'):
                upstream_entity = ContactEntity.objects.create(
                    kind='COMPANY',
                    name=data['upstream_company_name'],
                    address=data.get('upstream_address') or None,
                    mailing_address=data.get('upstream_mailing_address') or None,
                    company_phone=data.get('upstream_company_phone') or None,
                )
                if data.get('upstream_contact_name'):
                    upstream_contact = EntityContactPerson.objects.create(
                        corporate_entity=upstream_entity,
                        name=data['upstream_contact_name'],
                        phone=data.get('upstream_contact_phone') or None,
                        line_available=data.get('upstream_line_available', False),
                    )
                    _save_contact_emails(request, 'upstream', upstream_contact)

            # 3. 下位会社・担当者: 既存 or 新規
            downstream_entity = None
            downstream_contact = None
            existing_downstream_id = request.POST.get('existing_downstream_id')
            if existing_downstream_id:
                downstream_entity = get_object_or_404(ContactEntity, pk=existing_downstream_id, kind='COMPANY')
                existing_downstream_contact_id = request.POST.get('existing_downstream_contact_id')
                if existing_downstream_contact_id:
                    downstream_contact = get_object_or_404(EntityContactPerson, pk=existing_downstream_contact_id)
                elif data.get('downstream_contact_name'):
                    downstream_contact = EntityContactPerson.objects.create(
                        corporate_entity=downstream_entity,
                        name=data['downstream_contact_name'],
                        phone=data.get('downstream_contact_phone') or None,
                        line_available=data.get('downstream_line_available', False),
                    )
                    _save_contact_emails(request, 'downstream', downstream_contact)
            elif data.get('downstream_company_name'):
                downstream_entity = ContactEntity.objects.create(
                    kind='COMPANY',
                    name=data['downstream_company_name'],
                    address=data.get('downstream_address') or None,
                    mailing_address=data.get('downstream_mailing_address') or None,
                    company_phone=data.get('downstream_company_phone') or None,
                    has_invoice_registration=data.get('downstream_has_invoice_registration', False),
                )
                if data.get('downstream_contact_name'):
                    downstream_contact = EntityContactPerson.objects.create(
                        corporate_entity=downstream_entity,
                        name=data['downstream_contact_name'],
                        phone=data.get('downstream_contact_phone') or None,
                        line_available=data.get('downstream_line_available', False),
                    )
                    _save_contact_emails(request, 'downstream', downstream_contact)

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
                notes=data.get('notes') or None,
                is_active=data.get('is_active', True),
            )

            # 6. ServiceContract作成
            is_fixed_fee = data.get('is_fixed_fee', False)
            ds_is_fixed_fee = data.get('downstream_is_fixed_fee', False)
            ServiceContract.objects.create(
                assignment=assignment,
                unit_price=data['unit_price'],
                is_fixed_fee=is_fixed_fee,
                travel_expense_included=data.get('travel_expense_included', False),
                valid_from=data.get('valid_from'),
                valid_to=data.get('valid_to'),
                # 固定報酬の場合は精算系をNullに
                lower_limit_hour=None if is_fixed_fee else data.get('lower_limit_hour'),
                upper_limit_hours=None if is_fixed_fee else data.get('upper_limit_hours'),
                deduction_unit_price=None if is_fixed_fee else data.get('deduction_unit_price'),
                excess_unit_price=None if is_fixed_fee else data.get('excess_unit_price'),
                settlement_unit_minutes=None if is_fixed_fee else data.get('settlement_unit_minutes'),
                upstream_timesheet_collection_method=data.get('upstream_timesheet_collection_method') or None,
                downstream_timesheet_collection_method=data.get('downstream_timesheet_collection_method') or None,
                upstream_payment_terms=data.get('upstream_payment_terms'),
                downstream_payment_terms=data.get('downstream_payment_terms'),
                bank_holiday_handling=data.get('bank_holiday_handling') or None,
                downstream_bank_holiday_handling=data.get('downstream_bank_holiday_handling') or None,
                timesheet_due_date=data.get('timesheet_due_date'),
                downstream_timesheet_due_day=data.get('downstream_timesheet_due_day'),
                # 下位契約条件
                downstream_unit_price=data.get('downstream_unit_price'),
                downstream_is_fixed_fee=ds_is_fixed_fee,
                downstream_lower_limit_hour=None if ds_is_fixed_fee else data.get('downstream_lower_limit_hour'),
                downstream_upper_limit_hours=None if ds_is_fixed_fee else data.get('downstream_upper_limit_hours'),
                downstream_deduction_unit_price=None if ds_is_fixed_fee else data.get('downstream_deduction_unit_price'),
                downstream_excess_unit_price=None if ds_is_fixed_fee else data.get('downstream_excess_unit_price'),
                downstream_settlement_unit_minutes=None if ds_is_fixed_fee else data.get('downstream_settlement_unit_minutes'),
            )

            return redirect('party_list')
    else:
        form = ContactEntityForm()
    return render(request, 'contact_entity_form.html', {'form': form})


@login_required
@require_POST
def assignment_extend_contract(request, pk):
    """契約期間をインライン延長するAPIエンドポイント"""
    import json
    import calendar
    from datetime import date

    assignment = get_object_or_404(Assignment, pk=pk)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    months = data.get('months')
    if months not in (1, 3, 6):
        return JsonResponse({'error': 'months must be 1, 3, or 6'}, status=400)

    today = date.today()
    contract = assignment.contracts.filter(
        Q(valid_to__isnull=False),
        Q(valid_from__isnull=True) | Q(valid_from__lte=today),
        Q(valid_to__gte=today),
    ).first()

    if not contract:
        # valid_to が NULL（無期限）か、有効な契約が見つからない
        has_open = assignment.contracts.filter(valid_to__isnull=True).exists()
        if has_open:
            return JsonResponse({'error': '既に無期限の契約です'}, status=400)
        return JsonResponse({'error': '有効な契約が見つかりません'}, status=404)

    # valid_to に months 分を加算（月末調整）
    old_to = contract.valid_to
    new_month = old_to.month + months
    new_year = old_to.year + (new_month - 1) // 12
    new_month = (new_month - 1) % 12 + 1
    new_day = min(old_to.day, calendar.monthrange(new_year, new_month)[1])
    new_valid_to = date(new_year, new_month, new_day)

    contract.valid_to = new_valid_to
    contract.save(update_fields=['valid_to'])

    return JsonResponse({
        'ok': True,
        'new_valid_to': new_valid_to.isoformat(),
    })


@login_required
@require_POST
def assignment_toggle_active(request, pk):
    """稼働中フラグをトグルする"""
    assignment = get_object_or_404(Assignment, pk=pk)
    assignment.is_active = not assignment.is_active
    assignment.save(update_fields=['is_active'])
    return redirect('assignment_detail', pk=pk)


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

            # 3. 上位更新
            if data.get('upstream_company_name'):
                if assignment.upstream_entity and assignment.upstream_entity != worker:
                    ue = assignment.upstream_entity
                    ue.name = data['upstream_company_name']
                    ue.address = data.get('upstream_address') or None
                    ue.mailing_address = data.get('upstream_mailing_address') or None
                    ue.company_phone = data.get('upstream_company_phone') or None
                    ue.save()
                else:
                    assignment.upstream_entity = ContactEntity.objects.create(
                        kind='COMPANY',
                        name=data['upstream_company_name'],
                        address=data.get('upstream_address') or None,
                        mailing_address=data.get('upstream_mailing_address') or None,
                        company_phone=data.get('upstream_company_phone') or None,
                    )
                if data.get('upstream_contact_name'):
                    if assignment.upstream_contact_person:
                        ucp = assignment.upstream_contact_person
                        ucp.name = data['upstream_contact_name']
                        ucp.phone = data.get('upstream_contact_phone') or None
                        ucp.line_available = data.get('upstream_line_available', False)
                        ucp.save()
                    else:
                        ucp = EntityContactPerson.objects.create(
                            corporate_entity=assignment.upstream_entity,
                            name=data['upstream_contact_name'],
                            phone=data.get('upstream_contact_phone') or None,
                            line_available=data.get('upstream_line_available', False),
                        )
                        assignment.upstream_contact_person = ucp
                    _save_contact_emails(request, 'upstream', ucp)

            # 4. 下位更新
            if data.get('downstream_company_name'):
                if assignment.downstream_entity and assignment.downstream_entity != worker:
                    de = assignment.downstream_entity
                    de.name = data['downstream_company_name']
                    de.address = data.get('downstream_address') or None
                    de.mailing_address = data.get('downstream_mailing_address') or None
                    de.company_phone = data.get('downstream_company_phone') or None
                    de.has_invoice_registration = data.get('downstream_has_invoice_registration', False)
                    de.save()
                else:
                    assignment.downstream_entity = ContactEntity.objects.create(
                        kind='COMPANY',
                        name=data['downstream_company_name'],
                        address=data.get('downstream_address') or None,
                        mailing_address=data.get('downstream_mailing_address') or None,
                        company_phone=data.get('downstream_company_phone') or None,
                        has_invoice_registration=data.get('downstream_has_invoice_registration', False),
                    )
                if data.get('downstream_contact_name'):
                    if assignment.downstream_contact_person:
                        dcp = assignment.downstream_contact_person
                        dcp.name = data['downstream_contact_name']
                        dcp.phone = data.get('downstream_contact_phone') or None
                        dcp.line_available = data.get('downstream_line_available', False)
                        dcp.save()
                    else:
                        dcp = EntityContactPerson.objects.create(
                            corporate_entity=assignment.downstream_entity,
                            name=data['downstream_contact_name'],
                            phone=data.get('downstream_contact_phone') or None,
                            line_available=data.get('downstream_line_available', False),
                        )
                        assignment.downstream_contact_person = dcp
                    _save_contact_emails(request, 'downstream', dcp)

            # 5. Assignment更新
            assignment.project_name = data.get('project_name') or None
            assignment.notes = data.get('notes') or None
            assignment.is_active = data.get('is_active', True)
            assignment.save()

            # 6. 契約更新
            is_fixed_fee = data.get('is_fixed_fee', False)
            ds_is_fixed_fee = data.get('downstream_is_fixed_fee', False)
            contract_fields = dict(
                unit_price=data['unit_price'],
                is_fixed_fee=is_fixed_fee,
                travel_expense_included=data.get('travel_expense_included', False),
                valid_from=data.get('valid_from'),
                valid_to=data.get('valid_to'),
                lower_limit_hour=None if is_fixed_fee else data.get('lower_limit_hour'),
                upper_limit_hours=None if is_fixed_fee else data.get('upper_limit_hours'),
                deduction_unit_price=None if is_fixed_fee else data.get('deduction_unit_price'),
                excess_unit_price=None if is_fixed_fee else data.get('excess_unit_price'),
                settlement_unit_minutes=None if is_fixed_fee else data.get('settlement_unit_minutes'),
                upstream_timesheet_collection_method=data.get('upstream_timesheet_collection_method') or None,
                downstream_timesheet_collection_method=data.get('downstream_timesheet_collection_method') or None,
                upstream_payment_terms=data.get('upstream_payment_terms'),
                downstream_payment_terms=data.get('downstream_payment_terms'),
                bank_holiday_handling=data.get('bank_holiday_handling') or None,
                downstream_bank_holiday_handling=data.get('downstream_bank_holiday_handling') or None,
                timesheet_due_date=data.get('timesheet_due_date'),
                downstream_timesheet_due_day=data.get('downstream_timesheet_due_day'),
                # 下位契約条件
                downstream_unit_price=data.get('downstream_unit_price'),
                downstream_is_fixed_fee=ds_is_fixed_fee,
                downstream_lower_limit_hour=None if ds_is_fixed_fee else data.get('downstream_lower_limit_hour'),
                downstream_upper_limit_hours=None if ds_is_fixed_fee else data.get('downstream_upper_limit_hours'),
                downstream_deduction_unit_price=None if ds_is_fixed_fee else data.get('downstream_deduction_unit_price'),
                downstream_excess_unit_price=None if ds_is_fixed_fee else data.get('downstream_excess_unit_price'),
                downstream_settlement_unit_minutes=None if ds_is_fixed_fee else data.get('downstream_settlement_unit_minutes'),
            )
            if current_contract:
                for k, v in contract_fields.items():
                    setattr(current_contract, k, v)
                current_contract.save()
            else:
                ServiceContract.objects.create(assignment=assignment, **contract_fields)

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
            'notes': assignment.notes or '',
            'is_active': assignment.is_active,
        }
        # 契約情報
        if current_contract:
            initial.update({
                'unit_price': current_contract.unit_price,
                'is_fixed_fee': current_contract.is_fixed_fee,
                'travel_expense_included': current_contract.travel_expense_included,
                'valid_from': current_contract.valid_from,
                'valid_to': current_contract.valid_to,
                'lower_limit_hour': current_contract.lower_limit_hour,
                'upper_limit_hours': current_contract.upper_limit_hours,
                'deduction_unit_price': current_contract.deduction_unit_price,
                'excess_unit_price': current_contract.excess_unit_price,
                'settlement_unit_minutes': current_contract.settlement_unit_minutes,
                'upstream_timesheet_collection_method': current_contract.upstream_timesheet_collection_method or '',
                'downstream_timesheet_collection_method': current_contract.downstream_timesheet_collection_method or '',
                'upstream_payment_terms': current_contract.upstream_payment_terms,
                'downstream_payment_terms': current_contract.downstream_payment_terms,
                'bank_holiday_handling': current_contract.bank_holiday_handling or '',
                'downstream_bank_holiday_handling': current_contract.downstream_bank_holiday_handling or '',
                'timesheet_due_date': current_contract.timesheet_due_date,
                'downstream_timesheet_due_day': current_contract.downstream_timesheet_due_day,
                # 下位契約条件
                'downstream_unit_price': current_contract.downstream_unit_price,
                'downstream_is_fixed_fee': current_contract.downstream_is_fixed_fee,
                'downstream_lower_limit_hour': current_contract.downstream_lower_limit_hour,
                'downstream_upper_limit_hours': current_contract.downstream_upper_limit_hours,
                'downstream_deduction_unit_price': current_contract.downstream_deduction_unit_price,
                'downstream_excess_unit_price': current_contract.downstream_excess_unit_price,
                'downstream_settlement_unit_minutes': current_contract.downstream_settlement_unit_minutes,
            })
        # 上位
        if assignment.upstream_entity and assignment.upstream_entity != assignment.worker_entity:
            ue = assignment.upstream_entity
            initial['upstream_company_name'] = ue.name
            initial['upstream_address'] = ue.address or ''
            initial['upstream_mailing_address'] = ue.mailing_address or ''
            initial['upstream_company_phone'] = ue.company_phone or ''
        if assignment.upstream_contact_person:
            ucp = assignment.upstream_contact_person
            initial['upstream_contact_name'] = ucp.name
            initial['upstream_contact_phone'] = ucp.phone or ''
            initial['upstream_line_available'] = ucp.line_available
            # メールは template の JS で展開
        # 下位
        if assignment.downstream_entity and assignment.downstream_entity != assignment.worker_entity:
            de = assignment.downstream_entity
            initial['downstream_company_name'] = de.name
            initial['downstream_address'] = de.address or ''
            initial['downstream_mailing_address'] = de.mailing_address or ''
            initial['downstream_company_phone'] = de.company_phone or ''
            initial['downstream_has_invoice_registration'] = de.has_invoice_registration
        if assignment.downstream_contact_person:
            dcp = assignment.downstream_contact_person
            initial['downstream_contact_name'] = dcp.name
            initial['downstream_contact_phone'] = dcp.phone or ''
            initial['downstream_line_available'] = dcp.line_available
            # メールは template の JS で展開
            extra = dcp.extra_emails.first()
            if extra:
                initial['downstream_contact_email_2'] = extra.email
                initial['downstream_contact_email_2_desc'] = extra.description

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


# --- 勤務表回収 ---
@login_required
def timesheet_dashboard(request):
    from datetime import date
    from django.db.models import Q

    today = date.today()
    # 月パラメータ（YYYYMM形式）
    ym = request.GET.get('ym', '')
    if not ym or len(ym) != 6:
        ym = today.strftime('%Y%m')

    year = int(ym[:4])
    month = int(ym[4:6])

    # 前月・翌月
    if month == 1:
        prev_ym = f"{year - 1}12"
    else:
        prev_ym = f"{year}{month - 1:02d}"
    if month == 12:
        next_ym = f"{year + 1}01"
    else:
        next_ym = f"{year}{month + 1:02d}"

    # Active Assignments
    assignments = Assignment.objects.filter(is_active=True).select_related(
        'worker_entity', 'upstream_entity'
    ).prefetch_related('contracts', 'timesheets')

    # 該当月のTimesheetをprefetchで取得済み → Python側でマッチ
    timesheets_qs = Timesheet.objects.filter(billing_ym=ym)
    ts_map = {ts.assignment_id: ts for ts in timesheets_qs}

    rows = []
    pending_count = 0
    total_count = 0
    for a in assignments:
        # 現行契約
        contract = a.contracts.filter(
            Q(valid_to__isnull=True) | Q(valid_to__gte=today)
        ).filter(
            Q(valid_from__isnull=True) | Q(valid_from__lte=today)
        ).first()

        due_day = contract.downstream_timesheet_due_day if contract else None
        ts = ts_map.get(a.id)

        # 期限超過判定
        overdue = False
        if due_day and not ts and month < 12:
            due_month = month + 1
            due_year = year
            if due_month > 12:
                due_month = 1
                due_year += 1
            try:
                due_date = date(due_year, due_month, due_day)
                overdue = today > due_date
            except ValueError:
                pass

        total_count += 1
        if not ts:
            pending_count += 1

        rows.append({
            'assignment': a,
            'contract': contract,
            'timesheet': ts,
            'due_day': due_day,
            'overdue': overdue,
        })

    return render(request, 'timesheet_dashboard.html', {
        'rows': rows,
        'ym': ym,
        'year': year,
        'month': month,
        'prev_ym': prev_ym,
        'next_ym': next_ym,
        'pending_count': pending_count,
        'total_count': total_count,
    })


@login_required
def timesheet_upload(request):
    import os
    import tempfile
    from decimal import Decimal
    from django.contrib import messages
    from django.core.files.base import ContentFile

    if request.method != 'POST':
        return redirect('timesheet_dashboard')

    assignment_id = request.POST.get('assignment_id')
    ym = request.POST.get('billing_ym', '').strip()
    uploaded = request.FILES.get('file')

    if not assignment_id or not uploaded or not ym:
        messages.error(request, '案件・ファイル・対象年月は必須です。')
        return redirect('timesheet_dashboard')

    assignment = get_object_or_404(Assignment, pk=int(assignment_id))

    # ファイル内容を先に全部読む（パーサ・保存両方で使う）
    file_bytes = uploaded.read()
    suffix = os.path.splitext(uploaded.name)[1]

    # 一時ファイルに書き出してパーサ実行
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    parsed = {}
    try:
        if suffix.lower() == '.pdf':
            from system_app.services.timesheet_parsers.pdf_generic import parse_timesheet_pdf_generic
            parsed = parse_timesheet_pdf_generic(tmp_path)
        else:
            from system_app.services.timesheet_parsers.xlsx_generic import parse_timesheet_xlsx_generic
            parsed = parse_timesheet_xlsx_generic(tmp_path)
        # AI フォールバック（候補から最適値を選択）
        from system_app.services.timesheet_parsers.ai_fallback import enhance_parsed_result_with_ai
        parsed = enhance_parsed_result_with_ai(parsed)
    except Exception as e:
        messages.warning(request, f'パースに失敗しました（ファイルは保存済み）: {e}')
    finally:
        os.unlink(tmp_path)

    actual_hours = None
    travel_amount = None
    parse_confidence = {}

    is_pdf = suffix.lower() == '.pdf'

    if parsed:
        ah = parsed.get("actual_hours")
        if ah and ah.get("value") is not None:
            actual_hours = Decimal(str(ah["value"]))
            pc_entry = {
                "confidence": ah.get("confidence"),
                "evidence": ah.get("evidence", ah.get("source", "")),
            }
            if is_pdf:
                pc_entry["page_number"] = ah.get("page_number")
                pc_entry["bbox"] = ah.get("bbox")
            else:
                pc_entry["cell"] = ah.get("cell")
                pc_entry["sheet"] = ah.get("sheet")
            parse_confidence["actual_hours"] = pc_entry
        ta = parsed.get("travel_amount")
        if ta and ta.get("value") is not None:
            travel_amount = Decimal(str(ta["value"]))
            pc_entry = {
                "confidence": ta.get("confidence"),
                "evidence": ta.get("evidence", ta.get("source", "")),
            }
            if is_pdf:
                pc_entry["page_number"] = ta.get("page_number")
                pc_entry["bbox"] = ta.get("bbox")
            else:
                pc_entry["cell"] = ta.get("cell")
                pc_entry["sheet"] = ta.get("sheet")
            parse_confidence["travel_amount"] = pc_entry
        bym = parsed.get("billing_ym")
        if bym and bym.get("value") is not None:
            pc_entry = {
                "confidence": bym.get("confidence"),
                "evidence": bym.get("evidence", bym.get("source", "")),
            }
            if is_pdf:
                pc_entry["page_number"] = bym.get("page_number")
                pc_entry["bbox"] = bym.get("bbox")
            else:
                pc_entry["cell"] = bym.get("cell")
                pc_entry["sheet"] = bym.get("sheet")
            parse_confidence["billing_ym"] = pc_entry

        if parsed.get("parse_meta"):
            parse_confidence["parse_meta"] = parsed["parse_meta"]

    # ファイル名変換: {ym}_{worker_name}_{project_name}.{ext}
    worker_name = assignment.worker_entity.name if assignment.worker_entity else "unknown"
    project_name = assignment.project_name or "unknown"
    new_filename = f"{ym}_{worker_name}_{project_name}{suffix}"

    # Timesheet作成/更新
    ts, _created = Timesheet.objects.update_or_create(
        assignment=assignment,
        billing_ym=ym,
        defaults={
            'status': 'received',
            'original_filename': uploaded.name,
            'actual_hours': actual_hours,
            'travel_amount': travel_amount,
            'parse_confidence': parse_confidence or None,
            'invoice': None,
        },
    )

    # ファイルを保存（既存があれば上書き）
    if ts.file:
        ts.file.delete(save=False)
    ts.file.save(new_filename, ContentFile(file_bytes), save=True)

    messages.success(request, f'勤務表を受領しました（{worker_name} / {ym}）')
    return redirect(f"{reverse('timesheet_dashboard')}?ym={ym}")


@login_required
def timesheet_detail(request, pk):
    import os
    from decimal import Decimal
    from django.contrib import messages

    ts = get_object_or_404(
        Timesheet.objects.select_related('assignment', 'assignment__worker_entity', 'invoice'),
        pk=pk,
    )

    if request.method == 'POST':
        actual_hours_raw = request.POST.get('actual_hours', '').strip()
        travel_amount_raw = request.POST.get('travel_amount', '').strip()
        notes = request.POST.get('notes', '').strip()

        if actual_hours_raw:
            ts.actual_hours = Decimal(actual_hours_raw)
        if travel_amount_raw:
            ts.travel_amount = Decimal(travel_amount_raw)
        ts.notes = notes
        ts.save()
        messages.success(request, '勤務表情報を更新しました。')
        return redirect('timesheet_detail', pk=pk)

    # Excel HTML 生成
    excel_sheets = None
    is_excel = False
    is_pdf = False
    pdf_url = None
    pdf_highlights = []

    if ts.file:
        ext = os.path.splitext(ts.file.name)[1].lower()
        is_excel = ext in ('.xlsx', '.xls')
        is_pdf = ext == '.pdf'

        if is_excel:
            try:
                from system_app.services.excel_renderer import render_excel_to_html

                # parse_confidence からハイライト対象セルを抽出（実稼働時間・交通費のみ）
                highlight_cells = {}
                pc = ts.parse_confidence or {}
                for key in ('actual_hours', 'travel_amount'):
                    meta = pc.get(key)
                    if not meta or not isinstance(meta, dict):
                        continue
                    cell_ref = meta.get('cell')
                    sheet_name = meta.get('sheet')
                    if cell_ref and sheet_name:
                        highlight_cells.setdefault(sheet_name, []).append(cell_ref)

                excel_sheets = render_excel_to_html(ts.file.path, highlight_cells)
            except Exception:
                excel_sheets = None

        elif is_pdf:
            pdf_url = reverse('timesheet_view_inline', args=[ts.pk])
            pc = ts.parse_confidence or {}
            for key in ('actual_hours', 'travel_amount'):
                meta = pc.get(key)
                if isinstance(meta, dict) and meta.get('bbox') and meta.get('page_number') is not None:
                    pdf_highlights.append({
                        'page': meta['page_number'],
                        'bbox': meta['bbox'],
                        'label': key,
                    })

    # parse_confidence の表示用データ（新旧形式に対応）
    pc = ts.parse_confidence or {}
    confidence_display = {}
    for key in ('actual_hours', 'travel_amount', 'billing_ym'):
        meta = pc.get(key)
        if meta is None:
            continue
        if isinstance(meta, dict):
            confidence_display[key] = meta
        else:
            # 旧形式: 数値のみ
            confidence_display[key] = {"confidence": meta}

    import json
    return render(request, 'timesheet_detail.html', {
        'ts': ts,
        'excel_sheets': excel_sheets,
        'is_excel': is_excel,
        'is_pdf': is_pdf,
        'pdf_url': pdf_url,
        'pdf_highlights_json': json.dumps(pdf_highlights),
        'confidence_display': confidence_display,
    })


@login_required
def timesheet_download(request, pk):
    ts = get_object_or_404(Timesheet, pk=pk)
    if not ts.file:
        raise Http404("ファイルが見つかりません")
    return FileResponse(
        open(ts.file.path, 'rb'),
        as_attachment=True,
        filename=ts.original_filename or os.path.basename(ts.file.name),
    )


@login_required
def timesheet_view_inline(request, pk):
    ts = get_object_or_404(Timesheet, pk=pk)
    if not ts.file:
        raise Http404
    return FileResponse(open(ts.file.path, 'rb'), content_type='application/pdf')


@login_required
def timesheet_generate_invoice(request, pk):
    from decimal import Decimal
    from django.contrib import messages
    from system_app.services.invoicing import create_or_update_invoice_from_parsed

    if request.method != 'POST':
        return redirect('timesheet_dashboard')

    ts = get_object_or_404(Timesheet, pk=pk)

    if not ts.actual_hours:
        messages.error(request, '実稼働時間が未入力のため請求書を生成できません。')
        return redirect('timesheet_detail', pk=pk)

    # パーサ結果の代わりに Timesheet のデータで parsed dict を構築
    parsed = {
        "billing_ym": {"value": ts.billing_ym, "confidence": 1.0},
        "actual_hours": {"value": ts.actual_hours, "confidence": 1.0},
    }
    if ts.travel_amount:
        parsed["travel_amount"] = {"value": ts.travel_amount, "confidence": 1.0}

    try:
        inv = create_or_update_invoice_from_parsed(
            assignment_id=ts.assignment_id,
            parsed=parsed,
            fallback_travel_amount=Decimal("0"),
        )
        ts.invoice = inv
        ts.status = 'processed'
        ts.save()
        messages.success(
            request,
            f'請求書ドラフトを作成しました（{inv.billing_ym} / 合計 {inv.total_amount:,.0f}円）'
        )
    except Exception as e:
        messages.error(request, f'請求書生成エラー: {e}')
        return redirect('timesheet_detail', pk=pk)

    # --- 買掛（下位支払い）の自動生成 ---
    try:
        from system_app.services.payable_service import create_or_update_payable_from_parsed
        payable = create_or_update_payable_from_parsed(
            assignment_id=ts.assignment_id,
            parsed=parsed,
            fallback_travel_amount=Decimal("0"),
        )
        if payable:
            messages.success(
                request,
                f'買掛ドラフトを作成しました（{payable.billing_ym} / 合計 {payable.total_amount:,.0f}円）'
            )
    except Exception as e:
        messages.warning(request, f'買掛の自動生成に失敗しました: {e}')

    return redirect(f"{reverse('timesheet_dashboard')}?ym={ts.billing_ym}")


# --- 請求管理 ---
@login_required
def invoice_list(request):
    from datetime import date

    today = date.today()
    ym = request.GET.get('ym', '')
    if not ym or len(ym) != 6:
        ym = today.strftime('%Y%m')

    year = int(ym[:4])
    month = int(ym[4:6])

    if month == 1:
        prev_ym = f"{year - 1}12"
    else:
        prev_ym = f"{year}{month - 1:02d}"
    if month == 12:
        next_ym = f"{year + 1}01"
    else:
        next_ym = f"{year}{month + 1:02d}"

    invoices = Invoice.objects.filter(billing_ym=ym).select_related(
        'assignment', 'assignment__upstream_entity', 'assignment__worker_entity'
    ).order_by('assignment__worker_entity__name')

    sent_count = invoices.filter(status='sent').count()
    total_count = invoices.count()

    return render(request, 'invoice_list.html', {
        'invoices': invoices,
        'ym': ym,
        'year': year,
        'month': month,
        'prev_ym': prev_ym,
        'next_ym': next_ym,
        'sent_count': sent_count,
        'total_count': total_count,
    })


@login_required
def invoice_upload(request):
    from decimal import Decimal
    from django.contrib import messages
    import os
    import tempfile
    from system_app.services.timesheet_parsers.xlsx_generic import parse_timesheet_xlsx_generic
    from system_app.services.invoicing import create_or_update_invoice_from_parsed

    if request.method != 'POST':
        return redirect('invoice_list')

    assignment_id = request.POST.get('assignment_id')
    billing_year = request.POST.get('billing_year', '').strip()
    billing_month = request.POST.get('billing_month', '').strip()
    uploaded = request.FILES.get('file')
    actual_hours_input = request.POST.get('actual_hours', '').strip()

    if not assignment_id or not uploaded:
        messages.error(request, '案件とファイルは必須です。')
        return redirect('invoice_list')

    # フォーム入力があればそちら優先、空ならパーサに任せる
    form_billing_ym = f"{billing_year}{billing_month}" if billing_year and billing_month else None
    fallback_hours = Decimal(actual_hours_input) if actual_hours_input else None

    # 一時ファイルに保存してパース
    suffix = os.path.splitext(uploaded.name)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in uploaded.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        if suffix.lower() == '.pdf':
            from system_app.services.timesheet_parsers.pdf_generic import parse_timesheet_pdf_generic
            parsed = parse_timesheet_pdf_generic(tmp_path)
        else:
            parsed = parse_timesheet_xlsx_generic(tmp_path)
        # フォーム入力があればパーサ結果を上書き（フォーム優先）
        if form_billing_ym:
            parsed["billing_ym"] = {"value": form_billing_ym, "confidence": 1.0, "cell": None, "evidence": "フォーム入力"}
        if fallback_hours is not None:
            parsed["actual_hours"] = {"value": fallback_hours, "confidence": 1.0, "cell": None, "evidence": "フォーム入力"}
        inv = create_or_update_invoice_from_parsed(
            assignment_id=int(assignment_id),
            parsed=parsed,
            fallback_travel_amount=Decimal("0"),
        )
        messages.success(
            request,
            f'請求書ドラフトを作成しました（{inv.billing_ym} / 合計 {inv.total_amount:,.0f}円）'
        )
    except Exception as e:
        messages.error(request, f'エラー: {e}')
    finally:
        os.unlink(tmp_path)

    return redirect('invoice_list')


@login_required
def invoice_detail(request, invoice_id):
    from datetime import date
    from decimal import Decimal
    from django.contrib import messages
    from system_app.services.contracts import get_active_contract
    from system_app.services.invoice_calculator import (
        calculate_invoice_lines,
        default_due_date,
        generate_invoice_number,
        recalculate_totals,
    )

    invoice = get_object_or_404(
        Invoice.objects.select_related('assignment', 'assignment__upstream_entity'),
        id=invoice_id,
    )
    lines = invoice.lines.all().order_by('display_order')

    # 該当契約を取得
    try:
        contract = get_active_contract(invoice.assignment, invoice.billing_ym)
    except Exception:
        contract = None

    # 表示用デフォルト値（DBには書き込まない）
    display_invoice_number = invoice.invoice_number or generate_invoice_number(
        invoice.billing_ym, exclude_invoice_id=invoice.id
    )
    display_issue_date = invoice.issue_date or date.today()
    display_due_date = invoice.due_date
    if not display_due_date and contract:
        display_due_date = default_due_date(invoice.billing_ym, contract.upstream_payment_terms)
    display_actual_hours = invoice.actual_hours
    if not display_actual_hours and contract:
        excess_line = invoice.lines.filter(kind='excess').first()
        deduction_line = invoice.lines.filter(kind='deduction').first()
        if excess_line and contract.upper_limit_hours:
            display_actual_hours = contract.upper_limit_hours + excess_line.quantity
        elif deduction_line and contract.lower_limit_hour:
            display_actual_hours = contract.lower_limit_hour - deduction_line.quantity
        elif contract.upper_limit_hours and contract.lower_limit_hour:
            display_actual_hours = contract.upper_limit_hours

    if request.method == 'POST':
        # ヘッダ情報の更新
        header_invoice_number = request.POST.get('header_invoice_number', '').strip()
        header_issue_date = request.POST.get('header_issue_date', '').strip()
        header_due_date = request.POST.get('header_due_date', '').strip()

        invoice.invoice_number = header_invoice_number or None
        invoice.issue_date = header_issue_date or None
        invoice.due_date = header_due_date or None

        # 契約情報の更新
        if contract:
            def _post_int(name):
                v = request.POST.get(name, '').strip()
                return int(v) if v else None
            def _post_dec(name):
                v = request.POST.get(name, '').strip()
                return Decimal(v) if v else None

            contract.unit_price = _post_int('ct_unit_price') or contract.unit_price
            contract.lower_limit_hour = _post_dec('ct_lower_limit_hour')
            contract.upper_limit_hours = _post_dec('ct_upper_limit_hours')
            contract.deduction_unit_price = _post_int('ct_deduction_unit_price')
            contract.excess_unit_price = _post_int('ct_excess_unit_price')
            contract.settlement_unit_minutes = _post_int('ct_settlement_unit_minutes')
            contract.upstream_payment_terms = _post_int('ct_upstream_payment_terms')
            contract.save()

        # 明細行の更新
        def _strip_comma(v):
            return v.replace(',', '').strip() if v else v

        for line in lines:
            prefix = f"line_{line.id}"
            item_name = request.POST.get(f"{prefix}_item_name")
            quantity = request.POST.get(f"{prefix}_quantity")
            unit_price = _strip_comma(request.POST.get(f"{prefix}_unit_price"))
            amount = _strip_comma(request.POST.get(f"{prefix}_amount"))

            if item_name is not None:
                line.item_name = item_name
                line.quantity = Decimal(quantity) if quantity else line.quantity
                line.unit_price = Decimal(unit_price) if unit_price else line.unit_price
                line.amount = Decimal(amount) if amount else line.amount
                line.save()

        # 交通費の更新（0なら削除、値があれば作成/更新）
        expense_raw = _strip_comma(request.POST.get('expense_amount', ''))
        expense_val = Decimal(expense_raw) if expense_raw else Decimal("0")
        expense_line = invoice.lines.filter(kind='expense').first()
        if expense_val > 0:
            if expense_line:
                expense_line.amount = expense_val
                expense_line.unit_price = expense_val
                expense_line.save()
            else:
                InvoiceLine.objects.create(
                    invoice=invoice,
                    kind='expense',
                    display_order=40,
                    item_name='交通費（実費）',
                    quantity=Decimal("1"),
                    unit_price=expense_val,
                    amount=expense_val,
                )
        elif expense_line:
            expense_line.delete()

        # 集計再計算
        invoice.save()
        recalculate_totals(invoice)

        action = request.POST.get('action', 'save')

        if action == 'recalc' and contract:
            actual_h = request.POST.get('header_actual_hours', '').strip()
            if actual_h:
                invoice.actual_hours = Decimal(actual_h)
            if invoice.actual_hours:
                travel_line = invoice.lines.filter(kind='expense').first()
                travel_amount = travel_line.amount if travel_line else Decimal("0")

                line_dicts = calculate_invoice_lines(
                    assignment=invoice.assignment,
                    contract=contract,
                    billing_ym=invoice.billing_ym,
                    actual_hours=invoice.actual_hours,
                    travel_amount=travel_amount,
                )
                invoice.lines.all().delete()
                for ld in line_dicts:
                    InvoiceLine.objects.create(invoice=invoice, **ld)

                invoice.save()
                recalculate_totals(invoice)
                messages.success(request, '契約条件から明細を再計算しました。')
            else:
                messages.warning(request, '実稼働時間が未入力のため再計算できません。')
            return redirect('invoice_detail', invoice_id=invoice.id)

        if action == 'export':
            from system_app.services.invoice_exporters.excel import export_invoice_to_template_xlsx
            result = export_invoice_to_template_xlsx(invoice.id)
            return FileResponse(
                open(result["file_path"], "rb"),
                content_type=result["content_type"],
                as_attachment=True,
                filename=result["file_name"],
            )

        messages.success(request, '下書きを保存しました。')
        return redirect('invoice_detail', invoice_id=invoice.id)

    expense_line = invoice.lines.filter(kind='expense').first()
    expense_amount = expense_line.amount if expense_line else Decimal("0")

    return render(request, 'invoice_detail.html', {
        'invoice': invoice,
        'lines': lines,
        'contract': contract,
        'subtotal_with_tax': invoice.subtotal_amount + invoice.tax_amount,
        'expense_amount': expense_amount,
        'display_invoice_number': display_invoice_number,
        'display_issue_date': display_issue_date,
        'display_due_date': display_due_date,
        'display_actual_hours': display_actual_hours,
    })


@login_required
def invoice_finalize_view(request, invoice_id):
    from django.contrib import messages
    from system_app.services.invoice_finalize import finalize_invoice

    if request.method != 'POST':
        return redirect('invoice_list')

    try:
        inv = finalize_invoice(invoice_id)
        messages.success(
            request,
            f'請求書を確定しました（{inv.invoice_number} / 支払期日 {inv.due_date}）'
        )
    except Exception as e:
        messages.error(request, f'確定エラー: {e}')

    return redirect('invoice_list')


@login_required
def invoice_toggle_sent(request, invoice_id):
    invoice = get_object_or_404(Invoice, id=invoice_id)
    if invoice.status == 'sent':
        invoice.status = 'draft'
    else:
        invoice.status = 'sent'
    invoice.save()
    next_url = request.POST.get('next', '')
    if next_url:
        return redirect(f"{reverse('invoice_list')}{next_url}")
    return redirect('invoice_list')


@login_required
def invoice_export_xlsx(request, invoice_id):
    from django.http import FileResponse
    from system_app.services.invoice_exporters.excel import export_invoice_to_template_xlsx
    result = export_invoice_to_template_xlsx(invoice_id)
    return FileResponse(
        open(result["file_path"], "rb"),
        content_type=result["content_type"],
        as_attachment=True,
        filename=result["file_name"],
    )


# =====================================================================
# 入金管理（AR: Accounts Receivable）
# =====================================================================

from django.db.models import Sum, Value, DecimalField as DjDecimalField, F
from django.db.models.functions import Coalesce
from decimal import Decimal
from datetime import date
from django.db import transaction


@login_required
def ar_list(request):
    """入金管理 メイン画面（月ベース）"""
    today = date.today()

    # --- 月パラメータ（YYYYMM形式、勤務表と統一） ---
    ym = request.GET.get("ym", "")
    if not ym or len(ym) != 6:
        ym = today.strftime("%Y%m")

    year = int(ym[:4])
    month = int(ym[4:6])

    # 前月・翌月
    if month == 1:
        prev_ym = f"{year - 1}12"
    else:
        prev_ym = f"{year}{month - 1:02d}"
    if month == 12:
        next_ym = f"{year + 1}01"
    else:
        next_ym = f"{year}{month + 1:02d}"

    # --- フィルタパラメータ ---
    customer_id = request.GET.get("customer", "")
    status_filter = request.GET.get("status", "")
    selected_invoice_id = request.GET.get("selected", "")

    # --- 請求書一覧 (sent のみ、当月 due_date) ---
    qs = (
        Invoice.objects
        .filter(status="sent", due_date__year=year, due_date__month=month)
        .select_related("assignment__upstream_entity", "assignment__worker_entity")
        .annotate(
            paid_sum=Coalesce(
                Sum("payments__amount"),
                Value(0),
                output_field=DjDecimalField(),
            )
        )
    )

    # 取引先フィルタ
    if customer_id:
        qs = qs.filter(assignment__upstream_entity_id=customer_id)

    # 状態フィルタ
    if status_filter == "paid":
        qs = qs.filter(paid_sum__gte=F("total_amount"))
    elif status_filter == "partial":
        qs = qs.filter(paid_sum__gt=0, paid_sum__lt=F("total_amount"))
    elif status_filter == "unpaid":
        qs = qs.filter(paid_sum=0)
    elif status_filter == "overdue":
        qs = qs.filter(paid_sum__lt=F("total_amount"), due_date__lt=today)

    qs = qs.order_by("due_date", "id")

    # --- 各行に remain / display_status を付与 + サマリ集計 ---
    invoices = []
    summary_total = Decimal("0")
    summary_paid = Decimal("0")
    summary_remain = Decimal("0")
    count_paid = 0

    for inv in qs:
        paid = inv.paid_sum or Decimal("0")
        remain = inv.total_amount - paid
        if remain <= 0:
            ds = "paid"
            count_paid += 1
        elif paid > 0:
            ds = "partial"
        else:
            ds = "unpaid"
        overdue = inv.due_date and inv.due_date < today and remain > 0
        invoices.append({
            "obj": inv,
            "paid_sum": paid,
            "remain": remain,
            "display_status": ds,
            "overdue": overdue,
        })
        summary_total += inv.total_amount
        summary_paid += paid
        summary_remain += max(remain, Decimal("0"))

    # --- 選択中の請求書 ---
    selected_invoice = None
    payments = []
    if selected_invoice_id:
        try:
            selected_invoice = (
                Invoice.objects
                .select_related("assignment__upstream_entity", "assignment__worker_entity")
                .annotate(
                    paid_sum=Coalesce(
                        Sum("payments__amount"),
                        Value(0),
                        output_field=DjDecimalField(),
                    )
                )
                .get(id=selected_invoice_id)
            )
            payments = selected_invoice.payments.select_related("created_by").all()
        except Invoice.DoesNotExist:
            pass

    # --- 取引先リスト（フィルタ用） ---
    customers = (
        ContactEntity.objects
        .filter(kind="COMPANY", assignments_as_upstream__invoices__status="sent")
        .distinct()
        .order_by("name")
    )

    # 選択中の請求書の残額を計算
    remain_amount = Decimal("0")
    if selected_invoice:
        paid = selected_invoice.paid_sum or Decimal("0")
        remain_amount = selected_invoice.total_amount - paid

    ctx = {
        "invoices": invoices,
        "selected_invoice": selected_invoice,
        "payments": payments,
        "remain_amount": remain_amount,
        "remain_amount_raw": int(remain_amount),
        "ym": ym,
        "year": year,
        "month": month,
        "prev_ym": prev_ym,
        "next_ym": next_ym,
        "filter_customer": customer_id,
        "filter_status": status_filter,
        "customers": customers,
        "today": today,
        "summary_total": summary_total,
        "summary_paid": summary_paid,
        "summary_remain": summary_remain,
        "count_total": len(invoices),
        "count_paid": count_paid,
    }
    return render(request, "ar_list.html", ctx)


@login_required
@transaction.atomic
def ar_payment_create(request, invoice_id):
    """入金登録（消込）"""
    if request.method != "POST":
        return redirect("ar_list")

    invoice = get_object_or_404(Invoice, id=invoice_id)
    ym = request.POST.get("ym", "")

    paid_date_str = request.POST.get("paid_date", "")
    amount_str = request.POST.get("amount", "").replace(",", "")
    note = request.POST.get("note", "")

    redirect_url = f"{reverse('ar_list')}?ym={ym}&selected={invoice_id}"

    # バリデーション
    errors = []
    try:
        paid_date = date.fromisoformat(paid_date_str)
    except (ValueError, TypeError):
        errors.append("入金日を正しく入力してください。")
        paid_date = None

    try:
        amount = Decimal(amount_str)
    except Exception:
        errors.append("入金額を正しく入力してください。")
        amount = None

    if amount is not None and amount <= 0:
        errors.append("入金額は0より大きい値を入力してください。")

    if amount is not None and amount > 0:
        paid_total = invoice.payments.aggregate(
            total=Coalesce(Sum("amount"), Value(0), output_field=DjDecimalField())
        )["total"]
        remain = invoice.total_amount - paid_total
        if amount > remain:
            errors.append(f"入金額が残額（¥{remain:,.0f}）を超えています。")

    if errors:
        from django.contrib import messages
        for e in errors:
            messages.error(request, e)
        return redirect(redirect_url)

    InvoicePayment.objects.create(
        invoice=invoice,
        paid_date=paid_date,
        amount=amount,
        note=note,
        created_by=request.user,
    )

    from django.contrib import messages
    messages.success(request, f"¥{amount:,.0f} の入金を登録しました。")
    return redirect(redirect_url)


@login_required
@transaction.atomic
def ar_payment_delete(request, payment_id):
    """入金削除（取消）"""
    if request.method != "POST":
        return redirect("ar_list")

    payment = get_object_or_404(InvoicePayment, id=payment_id)
    invoice_id = payment.invoice_id
    ym = request.POST.get("ym", "")

    from django.contrib import messages
    messages.success(request, f"¥{payment.amount:,.0f} の入金を取り消しました。")
    payment.delete()

    return redirect(f"{reverse('ar_list')}?ym={ym}&selected={invoice_id}")


# =====================================================================
# 支払管理（AP: Accounts Payable）
# =====================================================================


@login_required
def ap_list(request):
    """支払管理 メイン画面（月ベース）"""
    today = date.today()

    ym = request.GET.get("ym", "")
    if not ym or len(ym) != 6:
        ym = today.strftime("%Y%m")

    year = int(ym[:4])
    month = int(ym[4:6])

    if month == 1:
        prev_ym = f"{year - 1}12"
    else:
        prev_ym = f"{year}{month - 1:02d}"
    if month == 12:
        next_ym = f"{year + 1}01"
    else:
        next_ym = f"{year}{month + 1:02d}"

    # --- フィルタパラメータ ---
    vendor_id = request.GET.get("vendor", "")
    status_filter = request.GET.get("status", "")
    selected_payable_id = request.GET.get("selected", "")

    # --- 買掛一覧 (cancelled 以外、当月 due_date) ---
    qs = (
        Payable.objects
        .exclude(status="cancelled")
        .filter(due_date__year=year, due_date__month=month)
        .select_related("assignment__downstream_entity", "assignment__worker_entity")
        .annotate(
            paid_sum=Coalesce(
                Sum("payments__amount"),
                Value(0),
                output_field=DjDecimalField(),
            )
        )
    )

    if vendor_id:
        qs = qs.filter(assignment__downstream_entity_id=vendor_id)

    if status_filter == "paid":
        qs = qs.filter(paid_sum__gte=F("total_amount"))
    elif status_filter == "partial":
        qs = qs.filter(paid_sum__gt=0, paid_sum__lt=F("total_amount"))
    elif status_filter == "unpaid":
        qs = qs.filter(paid_sum=0)
    elif status_filter == "overdue":
        qs = qs.filter(paid_sum__lt=F("total_amount"), due_date__lt=today)

    qs = qs.order_by("due_date", "id")

    # --- 各行に remain / display_status を付与 + サマリ集計 ---
    payables = []
    summary_total = Decimal("0")
    summary_paid = Decimal("0")
    summary_remain = Decimal("0")
    count_paid = 0

    for p in qs:
        paid = p.paid_sum or Decimal("0")
        remain = p.total_amount - paid
        if remain <= 0:
            ds = "paid"
            count_paid += 1
        elif paid > 0:
            ds = "partial"
        else:
            ds = "unpaid"
        overdue = p.due_date and p.due_date < today and remain > 0
        payables.append({
            "obj": p,
            "paid_sum": paid,
            "remain": remain,
            "display_status": ds,
            "overdue": overdue,
        })
        summary_total += p.total_amount
        summary_paid += paid
        summary_remain += max(remain, Decimal("0"))

    # --- 選択中の買掛 ---
    selected_payable = None
    payments = []
    if selected_payable_id:
        try:
            selected_payable = (
                Payable.objects
                .select_related("assignment__downstream_entity", "assignment__worker_entity")
                .annotate(
                    paid_sum=Coalesce(
                        Sum("payments__amount"),
                        Value(0),
                        output_field=DjDecimalField(),
                    )
                )
                .get(id=selected_payable_id)
            )
            payments = selected_payable.payments.select_related("created_by").all()
        except Payable.DoesNotExist:
            pass

    # --- 支払先リスト（フィルタ用） ---
    vendors = (
        ContactEntity.objects
        .filter(kind="COMPANY", assignments_as_downstream__payables__isnull=False)
        .exclude(assignments_as_downstream__payables__status="cancelled")
        .distinct()
        .order_by("name")
    )

    remain_amount = Decimal("0")
    if selected_payable:
        paid = selected_payable.paid_sum or Decimal("0")
        remain_amount = selected_payable.total_amount - paid

    ctx = {
        "payables": payables,
        "selected_payable": selected_payable,
        "payments": payments,
        "remain_amount": remain_amount,
        "remain_amount_raw": int(remain_amount),
        "ym": ym,
        "year": year,
        "month": month,
        "prev_ym": prev_ym,
        "next_ym": next_ym,
        "filter_vendor": vendor_id,
        "filter_status": status_filter,
        "vendors": vendors,
        "today": today,
        "summary_total": summary_total,
        "summary_paid": summary_paid,
        "summary_remain": summary_remain,
        "count_total": len(payables),
        "count_paid": count_paid,
    }
    return render(request, "ap_list.html", ctx)


@login_required
@transaction.atomic
def ap_payment_create(request, payable_id):
    """支払登録（消込）"""
    if request.method != "POST":
        return redirect("ap_list")

    payable = get_object_or_404(Payable, id=payable_id)
    ym = request.POST.get("ym", "")

    paid_date_str = request.POST.get("paid_date", "")
    amount_str = request.POST.get("amount", "").replace(",", "")
    note = request.POST.get("note", "")

    redirect_url = f"{reverse('ap_list')}?ym={ym}&selected={payable_id}"

    errors = []
    try:
        paid_date = date.fromisoformat(paid_date_str)
    except (ValueError, TypeError):
        errors.append("支払日を正しく入力してください。")
        paid_date = None

    try:
        amount = Decimal(amount_str)
    except Exception:
        errors.append("支払額を正しく入力してください。")
        amount = None

    if amount is not None and amount <= 0:
        errors.append("支払額は0より大きい値を入力してください。")

    if amount is not None and amount > 0:
        paid_total = payable.payments.aggregate(
            total=Coalesce(Sum("amount"), Value(0), output_field=DjDecimalField())
        )["total"]
        remain = payable.total_amount - paid_total
        if amount > remain:
            errors.append(f"支払額が残額（¥{remain:,.0f}）を超えています。")

    if errors:
        from django.contrib import messages
        for e in errors:
            messages.error(request, e)
        return redirect(redirect_url)

    PayablePayment.objects.create(
        payable=payable,
        paid_date=paid_date,
        amount=amount,
        note=note,
        created_by=request.user,
    )

    from django.contrib import messages
    messages.success(request, f"¥{amount:,.0f} の支払を登録しました。")
    return redirect(redirect_url)


@login_required
@transaction.atomic
def ap_payment_delete(request, payment_id):
    """支払削除（取消）"""
    if request.method != "POST":
        return redirect("ap_list")

    payment = get_object_or_404(PayablePayment, id=payment_id)
    payable_id = payment.payable_id
    ym = request.POST.get("ym", "")

    from django.contrib import messages
    messages.success(request, f"¥{payment.amount:,.0f} の支払を取り消しました。")
    payment.delete()

    return redirect(f"{reverse('ap_list')}?ym={ym}&selected={payable_id}")


# =====================================================================
# 見積書エクスポート
# =====================================================================

@login_required
def estimate_export_xlsx(request, assignment_id):
    """見積書Excelダウンロード"""
    from django.http import FileResponse
    from system_app.services.estimate_exporter import export_estimate_xlsx

    contract_id = request.GET.get("contract_id")
    result = export_estimate_xlsx(assignment_id, contract_id=contract_id)
    return FileResponse(
        open(result["file_path"], "rb"),
        content_type=result["content_type"],
        as_attachment=True,
        filename=result["file_name"],
    )


# =====================================================================
# 営業管理（カンバンボード）
# =====================================================================

@login_required
def sales_board(request):
    """カンバンボード表示"""
    stagnant_only = request.GET.get('stagnant_only', '') == '1'

    qs = SalesDeal.objects.select_related('owner', 'project', 'candidate_entity')

    if stagnant_only:
        from datetime import timedelta
        threshold = timezone.now() - timedelta(days=7)
        qs = qs.filter(
            status__in=['received', 'working', 'proposed', 'waiting'],
        ).filter(
            Q(last_action_at__isnull=True, created_at__lt=threshold) |
            Q(last_action_at__lt=threshold)
        )

    columns = [
        ('received', '受信', '#64748b'),
        ('working', '対応中', '#3b82f6'),
        ('proposed', '提案済', '#8b5cf6'),
        ('waiting', '待ち', '#f59e0b'),
        ('won', '成約', '#10b981'),
        ('lost', '失注', '#6b7280'),
    ]

    board = []
    for status_val, label, color in columns:
        cards = [c for c in qs if c.status == status_val]
        cards.sort(key=lambda c: (c.display_order, -c.created_at.timestamp()))
        board.append({
            'status': status_val,
            'label': label,
            'color': color,
            'cards': cards,
        })

    return render(request, 'sales_board.html', {
        'board': board,
        'stagnant_only': stagnant_only,
    })


@login_required
def sales_deal_create(request):
    """商談（案件+人材マッチング）新規作成"""
    existing_project_id = request.GET.get('existing_project')
    initial = {}
    if existing_project_id:
        initial['existing_project'] = existing_project_id

    if request.method == 'POST':
        form = SalesDealCreateForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            project = data.get('existing_project')
            if not project:
                project = SalesProject.objects.create(
                    company_name=data['company_name'],
                    title=data['title'],
                    required_skills=data.get('required_skills', ''),
                    budget_range=data.get('budget_range', ''),
                    memo=data.get('project_memo', ''),
                )
            deal = SalesDeal.objects.create(
                project=project,
                candidate_name=data.get('candidate_name', ''),
                candidate_entity=data.get('candidate_entity'),
                status='received',
                owner=request.user,
                next_action_due=data.get('next_action_due'),
                memo=data.get('memo', ''),
            )
            return redirect('sales_board')
    else:
        form = SalesDealCreateForm(initial=initial)

    return render(request, 'sales_deal_form.html', {'form': form, 'is_edit': False})


@login_required
def sales_deal_detail(request, pk):
    """商談詳細 + アクション記録 + ステータス変更"""
    deal = get_object_or_404(
        SalesDeal.objects.select_related('owner', 'project', 'candidate_entity', 'assignment'),
        pk=pk,
    )
    actions = deal.actions.select_related('actor').all()
    status_changes = deal.status_changes.select_related('actor').all()
    action_form = SalesActionForm(initial={'acted_at': timezone.now()})

    if request.method == 'POST':
        new_status = request.POST.get('new_status')
        if new_status and new_status != deal.status:
            SalesStatusChange.objects.create(
                deal=deal,
                actor=request.user,
                from_status=deal.status,
                to_status=new_status,
            )
            deal.status = new_status
            deal.save()
            return redirect('sales_deal_detail', pk=pk)

    status_choices = SalesDeal.STATUS_CHOICES

    return render(request, 'sales_deal_detail.html', {
        'deal': deal,
        'actions': actions,
        'status_changes': status_changes,
        'action_form': action_form,
        'status_choices': status_choices,
    })


@login_required
def sales_deal_edit(request, pk):
    """商談編集"""
    deal = get_object_or_404(SalesDeal.objects.select_related('project'), pk=pk)
    if request.method == 'POST':
        form = SalesDealEditForm(request.POST, instance=deal)
        if form.is_valid():
            form.save()
            return redirect('sales_deal_detail', pk=pk)
    else:
        form = SalesDealEditForm(instance=deal)
    return render(request, 'sales_deal_form.html', {'form': form, 'is_edit': True, 'deal': deal})


@login_required
@require_POST
def sales_deal_move(request, pk):
    """ドラッグ&ドロップ用AJAX"""
    deal = get_object_or_404(SalesDeal, pk=pk)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    new_status = data.get('new_status')
    valid_statuses = [s[0] for s in SalesDeal.STATUS_CHOICES]
    if new_status not in valid_statuses:
        return JsonResponse({'error': 'Invalid status'}, status=400)

    if new_status != deal.status:
        SalesStatusChange.objects.create(
            deal=deal,
            actor=request.user,
            from_status=deal.status,
            to_status=new_status,
        )
        deal.status = new_status
        deal.save()

    return JsonResponse({'ok': True, 'new_status': new_status})


@login_required
@require_POST
def sales_deal_action(request, pk):
    """アクション追加"""
    deal = get_object_or_404(SalesDeal, pk=pk)
    form = SalesActionForm(request.POST)
    if form.is_valid():
        action = form.save(commit=False)
        action.deal = deal
        action.actor = request.user
        action.save()
        deal.last_action_at = action.acted_at
        deal.save()
        return redirect('sales_deal_detail', pk=pk)
    return redirect('sales_deal_detail', pk=pk)
