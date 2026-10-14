from django.urls import path
from . import views

urlpatterns = [
    # General Gateway Interceptors
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
    path('inventory/recommendations/', views.store_manager_recommendations_view, name='inventory_recommendations'),

    # Supply Chain Procurement Console Lanes
    path('procurement/', views.procurement_dashboard_view, name='procurement'),
    path('procurement/po/<int:po_id>/place/', views.place_supplier_order_view, name='place_supplier_order'),
]