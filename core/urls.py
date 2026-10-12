from django.urls import path
from . import views

urlpatterns = [
    # 1. Standalone Core Public Facing Landing Viewports
    path('', views.index, name='index'),
    path('about/', views.about, name='about'),
    path('features/', views.features, name='features'),
    path('contact/', views.contact, name='contact'),

    # 2. Secure Operator Authentication State Anchors
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # 3. Dynamic Decision Support & Clinical Workflow Interfaces
    path('dashboard/', views.dashboard, name='dashboard'),
    path('inventory/', views.inventory_view, name='inventory'),
    path('batches/', views.batch_list_view, name='batch_list'),
    path('dispense/', views.dispense_view, name='dispense'),

    # 4. Proactive Expiry Monitoring and 3-Month Moving Average Demand Forecasts
    path('alerts/', views.alerts_view, name='expiry_alerts'),
    path('reports/', views.reports_view, name='reports'),
]