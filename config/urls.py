from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls), # Django Administration
    path('', include('core.urls')), # Medicine Expiry Management System
]