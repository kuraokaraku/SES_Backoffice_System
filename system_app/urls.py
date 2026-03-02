# system_app/urls.py
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.index, name='index'), # トップ画面
    path('menu/', views.menu, name='menu'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('users/', views.user_list, name='user_list'),
    path('users/create/', views.user_create, name='user_create'),
    path('users/edit/<int:pk>/', views.user_edit, name='user_edit'),

    # --- 人材管理（Assignment ベース） ---
    path("party/", views.party_list, name="party_list"),
    path("party/new/", views.contact_entity_create, name="contact_entity_create"),
    path("assignment/<int:pk>/", views.assignment_detail, name="assignment_detail"),
    path("assignment/<int:pk>/edit/", views.assignment_edit, name="assignment_edit"),
    path("assignment/<int:pk>/extend/", views.assignment_extend_contract, name="assignment_extend_contract"),
    path("assignment/<int:pk>/toggle-active/", views.assignment_toggle_active, name="assignment_toggle_active"),
    path("assignment/<int:assignment_id>/estimate-xlsx/", views.estimate_export_xlsx, name="estimate_export_xlsx"),

    
    # --- 個人事業主 ---
    path('freelancers/', views.freelancer_list, name='freelancer_list'),
    path('freelancers/create/', views.freelancer_create, name='freelancer_create'),
    path('freelancers/update/<int:pk>/', views.freelancer_update, name='freelancer_update'),
    path('freelancers/delete/<int:pk>/', views.freelancer_delete, name='freelancer_delete'),
    path("freelancers/<int:pk>/", views.freelancer_detail, name="freelancer_detail"),
    
    # --- 月毎の作業管理 ---
    path('monthly/', views.monthly_list, name='monthly_list'),
    path('monthly/<int:pk>/', views.monthly_detail, name='monthly_detail'),
    path('monthly/create-batch/', views.create_monthly_batch, name='create_monthly_batch'),
    path('task/update/<int:pk>/', views.task_update, name='task_update'),

    # --- 注文書管理 (PurchaseOrder) ---
    # 注文書の一覧表示
    path('purchase-orders/', views.purchase_order_list, name='purchase_order_list'), 
    # 注文書のダウンロード（回数カウント付き）
    path('purchase-orders/download/<int:pk>/', views.purchase_download, name='purchase_download'),
    # 注文書の削除
    path('purchase-orders/delete/<int:pk>/', views.purchase_delete, name='purchase_delete'),
    # メール（またはローカルフォルダ）からの同期実行
    path('purchase-orders/sync/', views.sync_mail_view, name='sync_mail'),
    path('purchase-orders/search/', views.purchase_search_view, name='purchase_search'),
    
    # --- 提携パートナー ---
    path('partners/', views.partner_list, name='partner_list'),
    path('partners/add/', views.partner_detail, name='partner_add'),
    path('partners/<int:pk>/edit/', views.partner_detail, name='partner_edit'),
    path("partners/<int:pk>/", views.partner_detail, name="partner_detail"),

    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    # --- 勤務表回収 ---
    path('timesheets/', views.timesheet_dashboard, name='timesheet_dashboard'),
    path('timesheets/upload/', views.timesheet_upload, name='timesheet_upload'),
    path('timesheets/<int:pk>/', views.timesheet_detail, name='timesheet_detail'),
    path('timesheets/<int:pk>/download/', views.timesheet_download, name='timesheet_download'),
    path('timesheets/<int:pk>/view/', views.timesheet_view_inline, name='timesheet_view_inline'),
    path('timesheets/<int:pk>/generate-invoice/', views.timesheet_generate_invoice, name='timesheet_generate_invoice'),

    # --- 請求管理 ---
    path('invoices/', views.invoice_list, name='invoice_list'),
    path('invoices/upload/', views.invoice_upload, name='invoice_upload'),
    path('invoices/<int:invoice_id>/', views.invoice_detail, name='invoice_detail'),
    path('invoices/<int:invoice_id>/finalize/', views.invoice_finalize_view, name='invoice_finalize'),
    path('invoices/<int:invoice_id>/export-xlsx/', views.invoice_export_xlsx, name='invoice_export_xlsx'),
    path('invoices/<int:invoice_id>/toggle-sent/', views.invoice_toggle_sent, name='invoice_toggle_sent'),

    # --- 入金管理 ---
    path('ar/', views.ar_list, name='ar_list'),
    path('ar/invoices/<int:invoice_id>/payments/', views.ar_payment_create, name='ar_payment_create'),
    path('ar/payments/<int:payment_id>/delete/', views.ar_payment_delete, name='ar_payment_delete'),

    # --- 支払管理 ---
    path('ap/', views.ap_list, name='ap_list'),
    path('ap/payables/<int:payable_id>/payments/', views.ap_payment_create, name='ap_payment_create'),
    path('ap/payments/<int:payment_id>/delete/', views.ap_payment_delete, name='ap_payment_delete'),

    # --- API ---
    path('api/contact-entities/', views.contact_entity_search, name='contact_entity_search'),

    # --- 名刺管理 ---
    path('business-cards/', views.business_card_list, name='business_card_list'),

    # --- 営業管理 ---
    path('sales/', views.sales_board, name='sales_board'),
    path('sales/deals/new/', views.sales_deal_create, name='sales_deal_create'),
    path('sales/deals/<int:pk>/', views.sales_deal_detail, name='sales_deal_detail'),
    path('sales/deals/<int:pk>/edit/', views.sales_deal_edit, name='sales_deal_edit'),
    path('sales/deals/<int:pk>/move/', views.sales_deal_move, name='sales_deal_move'),
    path('sales/deals/<int:pk>/action/', views.sales_deal_action, name='sales_deal_action'),

]