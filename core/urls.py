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

    #Dynamic Decision Support & Clinical Workflow Interfaces
    path('dashboard/', views.dashboard, name='dashboard'),
    path('inventory/', views.inventory_view, name='inventory'),
    path('batches/', views.batch_list_view, name='batch_list'),
    path('dispense/', views.dispense_view, name='dispense'),
    path('dispense/reports/', views.pharmacist_reports_view, name='dispense_reports'),
    path('dispense/alerts/', views.pharmacist_alerts_view, name='dispense_alerts'),

    #Proactive Expiry Monitoring and 3-Month Moving Average Demand Forecasts
    path('alerts/', views.alerts_view, name='expiry_alerts'),
    path('reports/', views.reports_view, name='reports'),
]