from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')), #login/logout
    path('', include('core.urls')), # app URLs
    path("", RedirectView.as_view(url="/dashboard/", permanent=False), name="dashboard"),
]