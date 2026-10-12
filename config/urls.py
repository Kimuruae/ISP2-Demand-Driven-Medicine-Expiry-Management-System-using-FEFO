from django.contrib import admin
from django.urls import path, include
from core import views  # Pulls functional template views from your core application package

urlpatterns = [
    # 1. Django Administrative Native Site Panel
    path("admin/", admin.site.urls),
    path("", include('core.urls')),
    path("accounts/", include('django.contrib.auth.urls')),

    # 2. Public Facing Marketing / Research Domain Sub-Pages
    path("", views.index, name="index"),
    path("about/", views.about, name="about"),
    path("features/", views.features, name="features"),
    path("contact/", views.contact, name="contact"),

    # 3. Secure Session Access Control Management Gateway Handlers
    path("login/", views.login_view, name='login'),
    path("logout/", views.logout_view, name='logout'),

    # 4. Interactive Analytical Framework Workspace Dashboards
    path("dashboard/", views.dashboard, name='dashboard'),

    # 5. Real-Time Clinical Transaction & Active Warehouse Stock Flow Modules
    path("inventory/", views.inventory_view, name='inventory'),
    path("batches/", views.batch_list_view, name='batch_list'),
    path("dispense/", views.dispense_view, name='dispense'),

    # 6. Proactive Decision Support Alerts & Automated 3-Month Forecasting Reports
    path("alerts/", views.alerts_view, name='expiry_alerts'),
    path("reports/", views.reports_view, name='reports'),
]