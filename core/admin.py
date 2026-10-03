from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (Role, User, Supplier, Medicine, MedicineBatch, DispensingTransaction,
    ExpiryAlert, DemandForecast, ProcurementRecommendation, PurchaseOrder,
    SystemSetting, AuditLog,)

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'is_staff', 'is_active')
    fieldsets = UserAdmin.fieldsets + (("Role", {"fields": ("role", "phone_number", "department")}),)
    list_filter = ("role", "is_active")


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("supplier_name", "contact_person", "phone", "is_active")
    search_fields = ("supplier_name",)

@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')

@admin.register(Medicine)
class MedicineAdmin(admin.ModelAdmin):
    list_display = ("medicine_name", "category",'dosage_form', "reorder_level", "safety_stock_days", "is_active")
    search_fields = ("medicine_name", "generic_name")
    list_filter = ("category", "is_active")


@admin.register(MedicineBatch)
class MedicineBatchAdmin(admin.ModelAdmin):
    list_display = ("medicine", "batch_number", "quantity_available", "expiry_date", "status")
    list_filter = ("status","expiry_date")
    search_fields = ("batch_number", "medicine__medicine_name")
    ordering = ("expiry_date",)

@admin.register(DispensingTransaction)
class DispensingTransactionAdmin(admin.ModelAdmin):
    list_display = ("medicine", "batch", "quantity_dispensed", "dispensed_by", "is_override", "dispensed_at")
    list_filter = ("is_override","dispensed_at")


@admin.register(ExpiryAlert)
class ExpiryAlertAdmin(admin.ModelAdmin):
    list_display = ("medicine", "batch", "alert_type", "severity", "is_acknowledged", "generated_at")
    list_filter = ("alert_type", "severity", "is_acknowledged")


@admin.register(DemandForecast)
class DemandForecastAdmin(admin.ModelAdmin):
    list_display = ("medicine", "period_start", "moving_avg_3month", "generated_at")


@admin.register(ProcurementRecommendation)
class ProcurementRecommendationAdmin(admin.ModelAdmin):
    list_display = ("medicine", "recommended_quantity", "status", "generated_at", "reviewed_by")
    list_filter = ("status",)


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ("medicine", "supplier", "quantity_ordered", "total_amount", "status", "order_date")
    list_filter = ("status",)


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ("setting_key", "setting_value", "updated_at")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "user", "entity_type", "created_at")
    list_filter = ("action",)
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False  # audit logs are written by the system, not created manually