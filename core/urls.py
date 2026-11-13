from django.urls import path
from . import views
from django.contrib.auth import views as auth_views
from .views import pharmacist_dashboard_view
from . import receiving_views

urlpatterns = [
#Public Website landing pages and authentication links
path('', views.home_redirect, name='index'),
path('about/', views.about, name='about'),
path('features/', views.features, name='features'),
path('contact/', views.contact, name='contact'),
path('login/', views.login_view, name='login'),

path("activate/<uidb64>/<token>/",views.activate_account_view,name="activate_account",),
path('logout/', views.logout_view, name='logout'),

# Password Recovery
path("password-reset/",
    auth_views.PasswordResetView.as_view(
        template_name="public/password_reset.html",
        email_template_name="public/password_reset_email.html",
        subject_template_name="public/password_reset_subject.txt",
        success_url="/password-reset/done/",
        extra_context={"stage": "request"},
    ),
    name="password_reset",
),

path("password-reset/done/",
    auth_views.PasswordResetDoneView.as_view(template_name="public/password_reset.html",extra_context={"stage": "sent"},),
    name="password_reset_done",
),

path("reset/<uidb64>/<token>/",
    auth_views.PasswordResetConfirmView.as_view(
        template_name="public/password_reset.html",
        success_url="/reset/done/",
        extra_context={"stage": "confirm"},
    ),
    name="password_reset_confirm",
),

path("reset/done/",auth_views.PasswordResetCompleteView.as_view(template_name="public/password_reset.html",extra_context={"stage": "complete"},),
    name="password_reset_complete",),

#System Administrator
 path("system-admin/",views.system_admin_dashboard_view,name="system_admin_dashboard",),
path("system-admin/users/",views.system_admin_users_view,name="system_admin_users",),
path("system-admin/roles/",views.system_admin_roles_view,name="system_admin_roles",),
path("system-admin/settings/",views.system_admin_settings_view,name="system_admin_settings",),
path("system-admin/audit-logs/",views.system_admin_audit_logs_view,name="system_admin_audit_logs",),
path("system-admin/health/",views.system_admin_health_view,name="system_admin_health",),


#Hopital Admin Portal
path('hospital_admin/dashboard/', views.hospital_admin_dashboard_view, name='admin_dashboard'),
path('hospital_admin/dashboard/po/<int:po_id>/<str:action>/', views.hospital_admin_process_po_view, name='admin_process_po'),
path("hospital-admin/analytics/",views.hospital_admin_analytics_view,name="hospital_admin_analytics"),

#Pharmacist portal
path('pharmacist/dispense/', views.dispense_view, name='dispense'),
path("pharmacist/dashboard/",pharmacist_dashboard_view,name="pharmacist_dashboard",),
path("dispense/reports/",views.dispense_reports_view, name="dispense_reports",),
path("alerts/",views.alerts_view,name="alerts",),

# Store Manager Portal
path('inventory/',views.store_manager_inventory_view,name='inventory'),
path('inventory/reports/',views.inventory_reports_view,name='inventory_reports'),
path('inventory/alerts/',views.inventory_alerts_view,name='inventory_alerts'),
path('inventory/recommendations/',views.inventory_recommendations_view,name='inventory_recommendations'),
path('inventory/recommendations/submit/',views.store_manager_recommendations_view,name='store_manager_recommendations'),

#Store Manager - Goods Receiving
path("receiving/",receiving_views.receiving_dashboard,name="receiving_dashboard"),
path("receiving/receipts/",receiving_views.goods_receipt_list,name="goods_receipts"),
path("receiving/receipts/create/",receiving_views.goods_receipt_create,name="goods_receipt_create"),
path("receiving/receipts/<int:receipt_id>/",receiving_views.goods_receipt_detail,name="goods_receipt_detail"),
path("receiving/receipts/<int:receipt_id>/add-item/",receiving_views.goods_receipt_add_item,name="goods_receipt_add_item"),
path("receiving/items/<int:item_id>/inspect/",receiving_views.goods_receipt_inspect_item,name="goods_receipt_inspect_item"),

#Procurement Officer Portal
path('procurement/', views.procurement_dashboard_view, name='procurement'),
path("procurement/reports/",views.procurement_reports_view, name="procurement_reports",),
path('procurement/po/<int:po_id>/place/', views.place_supplier_order_view, name='place_supplier_order'),

path("alerts/", views.alerts_view, name="alerts"),
path("alerts/<int:alert_id>/acknowledge/",views.acknowledge_user_alert,name="acknowledge_user_alert"),
path("alerts/<int:alert_id>/resolve/",views.resolve_user_alert,name="resolve_user_alert"),

path("profile/", views.profile_view, name="profile"),
]