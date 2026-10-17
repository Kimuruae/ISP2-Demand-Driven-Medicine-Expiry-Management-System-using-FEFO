from django.urls import path
from . import views

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
    #Hopital Admin Portal
    path('dashboard/', views.hospital_admin_dashboard_view, name='admin_dashboard'),
    path('dashboard/po/<int:po_id>/<str:action>/', views.hospital_admin_process_po_view, name='admin_process_po'),

    #Pharmacist portal
    path('dispense/', views.dispense_view, name='dispense'),
    path("dispense/reports/",views.dispense_reports_view, name="dispense_reports",),
    path("dispense/alerts/",views.dispense_alerts_view,name="dispense_alerts",),

    #Store Manager Portal
    path('inventory/', views.store_manager_inventory_view, name='inventory'),
    path('inventory/reports/', views.inventory_reports_view, name='inventory_reports'),
    path('inventory/alerts/', views.inventory_alerts_view, name='inventory_alerts'),
    path('inventory/recommendations/', views.store_manager_recommendations_view, name='inventory_recommendations'),

    #Procurement Officer Portal
    path('procurement/', views.procurement_dashboard_view, name='procurement'),
path("procurement/reports/",views.procurement_reports_view, name="procurement_reports",),
    path('procurement/po/<int:po_id>/place/', views.place_supplier_order_view, name='place_supplier_order'),
]