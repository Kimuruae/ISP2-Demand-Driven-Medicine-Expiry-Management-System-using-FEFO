from django.urls import path
from . import views
from .views import pharmacist_dashboard_view
from . import receiving_views

urlpatterns = [
    #Public Website landing pages and authentication links
    path('', views.home_redirect, name='index'),
    path('about/', views.about, name='about'),
    path('features/', views.features, name='features'),
    path('contact/', views.contact, name='contact'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),

    # System Administrator and hospital administration
    path("system-admin/",views.system_admin_dashboard_view,name="system_admin_dashboard",),
path("system-admin/users/",views.system_admin_users_view,name="system_admin_users",),
path("system-admin/roles/",views.system_admin_roles_view,name="system_admin_roles",),
path("system-admin/settings/",views.system_admin_settings_view,name="system_admin_settings",),
path("system-admin/audit-logs/",views.system_admin_audit_logs_view,name="system_admin_audit_logs",),
path("system-admin/health/",views.system_admin_health_view,name="system_admin_health",),

path("profile/", views.profile_view, name="profile"),

    #Hopital Admin Portal
    path('dashboard/', views.hospital_admin_dashboard_view, name='admin_dashboard'),
    path('dashboard/po/<int:po_id>/<str:action>/', views.hospital_admin_process_po_view, name='admin_process_po'),

    #Pharmacist portal
    path('dispense/', views.dispense_view, name='dispense'),
    path("pharmacist/dashboard/",pharmacist_dashboard_view,name="pharmacist_dashboard",),
    path("dispense/reports/",views.dispense_reports_view, name="dispense_reports",),
    path("dispense/alerts/",views.dispense_alerts_view,name="dispense_alerts",),

# Store Manager Portal
path(
    'inventory/',
    views.store_manager_inventory_view,
    name='inventory'
),
path(
    'inventory/reports/',
    views.inventory_reports_view,
    name='inventory_reports'
),
path(
    'inventory/alerts/',
    views.inventory_alerts_view,
    name='inventory_alerts'
),
path(
    'inventory/recommendations/',
    views.inventory_recommendations_view,
    name='inventory_recommendations'
),
path(
    'inventory/recommendations/submit/',
    views.store_manager_recommendations_view,
    name='store_manager_recommendations'
),
# Store Manager - Goods Receiving

path(
    "receiving/",
    receiving_views.receiving_dashboard,
    name="receiving_dashboard"
),

path(
    "receiving/receipts/",
    receiving_views.goods_receipt_list,
    name="goods_receipts"
),

path(
    "receiving/receipts/create/",
    receiving_views.goods_receipt_create,
    name="goods_receipt_create"
),

path(
    "receiving/receipts/<int:receipt_id>/",
    receiving_views.goods_receipt_detail,
    name="goods_receipt_detail"
),

path(
    "receiving/receipts/<int:receipt_id>/add-item/",
    receiving_views.goods_receipt_add_item,
    name="goods_receipt_add_item"
),

path(
    "receiving/items/<int:item_id>/inspect/",
    receiving_views.goods_receipt_inspect_item,
    name="goods_receipt_inspect_item"
),

    #Procurement Officer Portal
    path('procurement/', views.procurement_dashboard_view, name='procurement'),
    path("procurement/reports/",views.procurement_reports_view, name="procurement_reports",),
    path('procurement/po/<int:po_id>/place/', views.place_supplier_order_view, name='place_supplier_order'),
]