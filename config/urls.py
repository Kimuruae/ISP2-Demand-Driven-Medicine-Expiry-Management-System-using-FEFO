from django.contrib import admin
from django.urls import path, include
from core import views

urlpatterns = [
    #Django admin
    path('admin/', admin.site.urls),
    # Master System Core Admin Panel
    path('system-admin/', views.system_admin_dashboard_view, name='system_admin_dashboard', ),

    #path('', include(core.urls)),

    # Core Public & Onboarding Content Views
    path('', views.home_redirect, name='index'),
    path('about/', views.about, name='about'),
    path('features/', views.features, name='features'),
    path('contact/', views.contact, name='contact'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),

    # Hospital Admin Desk Portals Map
    path('dashboard/', views.hospital_admin_dashboard_view, name='admin_dashboard'),
    path('dashboard/po/<int:po_id>/<str:action>/', views.hospital_admin_process_po_view, name='admin_process_po'),

    # Clinical Pharmacist Workstations
    path('dispense/', views.dispense_view, name='dispense'),

    # Warehouse Logistics Store Manager Lanes
path('inventory/', views.store_manager_inventory_view, name='inventory'),
path('inventory/reports/', views.inventory_reports_view, name='inventory_reports'),
path('inventory/alerts/', views.inventory_alerts_view, name='inventory_alerts'),
path('inventory/recommendations/', views.inventory_recommendations_view, name='inventory_recommendations'),

    # Supply Chain Procurement Console Lanes
    path('procurement/', views.procurement_dashboard_view, name='procurement'),
    path('procurement/po/<int:po_id>/place/', views.place_supplier_order_view, name='place_supplier_order'),
]