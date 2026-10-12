from django.urls import path
from . import views

urlpatterns = [
#Standalone Core Public Facing Landing Viewports
    path('', views.index, name='index'),
    path('about/', views.about, name='about'),
    path('features/', views.features, name='features'),
    path('contact/', views.contact, name='contact'),

 #Secure Operator Authentication State Anchors
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

#Dynamic Decision Support & Master Administrative Dashboards
    path('dashboard/', views.dashboard, name='dashboard'),
    path('batches/', views.batch_list_view, name='batch_list'),
    path('alerts/', views.alerts_view, name='expiry_alerts'),
    path('reports/', views.reports_view, name='reports'),

    #CLINICAL PHARMACIST WORKFLOWS
    path('dispense/', views.dispense_view, name='dispense'),
    path('dispense/alerts/', views.pharmacist_alerts_view, name='dispense_alerts'),
    path('dispense/reports/', views.pharmacist_reports_view, name='dispense_reports'),

    #LOGISTICS STORE MANAGER WORKFLOWS
    path('inventory/', views.store_manager_inventory_view, name='inventory'),
    path('inventory/alerts/', views.store_manager_alerts_view, name='inventory_alerts'),
    path('inventory/reports/', views.store_manager_reports_view, name='inventory_reports'),
    path('inventory/recommendations/', views.store_manager_recommendations_view, name='inventory_recommendations'),
]