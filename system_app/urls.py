# system_app/urls.py
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.index, name='index'), # トップ画面
    path('menu/', views.menu, name='menu'),
    path('users/', views.user_list, name='user_list'),
    path('users/create/', views.user_create, name='user_create'),
    path('users/edit/<int:pk>/', views.user_edit, name='user_edit'),

    # --- 統合一覧 ---
    path("party/", views.party_list, name="party_list"),

    
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

    # --- 名刺管理 ---
    path('business-cards/', views.business_card_list, name='business_card_list'),

]