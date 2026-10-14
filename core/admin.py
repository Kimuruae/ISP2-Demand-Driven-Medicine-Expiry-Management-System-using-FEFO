from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    Role, Supplier, Medicine, MedicineBatch, DispensingTransaction,
    ExpiryAlert, DemandForecast, ProcurementRecommendation, PurchaseOrder,
    SystemSetting, AuditLog
)

# Fetch the active customized user model reference safe matrix
User = get_user_model()

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'role', 'is_staff', 'is_active')
    list_filter = ('role', 'is_staff', 'is_active')
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Department Role Details', {'fields': ('role', 'phone_number')}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (('Department Role Details', {'fields': ('role', 'phone_number')}),
    )

# Registering remaining transactional inventory tables cleanly
admin.site.register(Role)
admin.site.register(Supplier)
admin.site.register(Medicine)
admin.site.register(MedicineBatch)
admin.site.register(DispensingTransaction)
admin.site.register(ExpiryAlert)
admin.site.register(DemandForecast)
admin.site.register(ProcurementRecommendation)
admin.site.register(PurchaseOrder)
admin.site.register(SystemSetting)
admin.site.register(AuditLog)