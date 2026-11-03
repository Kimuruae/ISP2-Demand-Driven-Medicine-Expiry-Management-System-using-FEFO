from django.contrib.auth.models import AbstractUser
from datetime import date
from django.db import models
from django.db.models import Q
from django.conf import settings

class Role(models.Model):
    SUPPORTED_ROLES = {"system administrator": ("System Administrator", "Manage accounts, application roles, settings and audit logs.",),
        "hospital admin": (
            "Hospital Admin",
            "Oversee hospital-level activity and approve purchase orders.",
        ),
        "hospital administrator": (
            "Hospital Administrator",
            "Oversee hospital-level activity and approve purchase orders.",
        ),
        "pharmacist": (
            "Pharmacist",
            "Dispense medicines using FEFO and review dispensing alerts and reports.",
        ),
        "store manager": (
            "Store Manager",
            "Maintain stock batches, monitor expiry and raise procurement recommendations.",
        ),
        "procurement officer": ("Procurement Officer","Review forecasts, recommendations and purchase orders.",),
    }
    PORTAL_URLS = {
        "system administrator": "system_admin_dashboard",
        "hospital admin": "admin_dashboard",
        "hospital administrator": "admin_dashboard",
        "pharmacist": "dispense",
        "store manager": "inventory",
        "procurement officer": "procurement",
    }
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)

@property
def portal_url_name(self): return self.PORTAL_URLS.get( (self.name or "").strip().casefold(), "")

@property
def is_system_administrator(self): return ((self.name or "").strip().casefold()== "system administrator")
def __str__(self): return self.name

class user(AbstractUser):
    other_name = models.CharField(max_length=150, blank=True)
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, blank=True)
    phone_number = models.CharField(max_length=15, blank=True)
    def __str__(self):
        role_name = self.role.name if self.role else "No role"
        return f"{self.username} - {self.role.name if self.role else 'No Role'}"

class Medicine(models.Model):
    id: int
    name = models.CharField(max_length=255)
    medicine_name = models.CharField(max_length=255, blank=True)
    generic_name = models.CharField(max_length=255, blank=True)
    category = models.CharField(max_length=100, default="General")
    dosage_form = models.CharField(max_length=50)
    reorder_level = models.IntegerField(default=30)
    safety_stock_days = models.IntegerField(default=30)
    is_active = models.BooleanField(default=True)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.name and not self.medicine_name:
            self.medicine_name = self.name

    # FIXED: Indentation shifted fully outside __init__ structure boundaries
    def __str__(self):return self.name

    def get_fefo_batches(self):
        return MedicineBatch.objects.filter(
            medicine=self,
            quantity_available__gt=0,
            expiry_date__gt=date.today(),
            status="Active"
        ).order_by('expiry_date')

class MedicineBatch(models.Model):
    id: int
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE)
    batch_number = models.CharField(max_length=100)
    quantity_received = models.IntegerField()
    quantity_available = models.IntegerField()
    received_date = models.DateField()
    expiry_date = models.DateField()
    storage_location = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=50, default="Active")

    class Meta:
        ordering = ['expiry_date']
        verbose_name_plural = "Medicine Batches"

    # FIXED: Indentation fixed to attach method to class model block cleanly
    def __str__(self):return f"{self.medicine.name} (Batch: {self.batch_number}) - Exp: {self.expiry_date}"

class Supplier(models.Model):
    supplier_name = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255, blank=True)
    contact_person = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone_number = models.CharField(max_length=15, blank=True)
    phone = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.supplier_name and not self.name:
            self.name = self.supplier_name
        if self.phone_number and not self.phone:
            self.phone = self.phone_number

    def __str__(self):return self.supplier_name

class DispensingTransaction(models.Model):
    id: int
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, null=True, blank=True)
    batch = models.ForeignKey(MedicineBatch, on_delete=models.CASCADE)
    dispensed_by = models.ForeignKey(user, on_delete=models.SET_NULL, null=True)
    quantity_dispensed = models.IntegerField()
    dispensed_date = models.DateTimeField(auto_now_add=True)
    dispensed_at = models.DateTimeField(auto_now_add=True)
    is_override = models.BooleanField(default=False)
    patient_identifier = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    def __str__(self):return f"Transaction {self.id} - {self.medicine.name if self.medicine else 'Unknown'}"

class ExpiryAlert(models.Model):
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, null=True, blank=True)
    batch = models.ForeignKey(MedicineBatch, on_delete=models.CASCADE)
    alert_type = models.CharField(max_length=50, choices=[('NEAR', 'Near Expiry'), ('EXPIRED', 'Expired')])
    days_to_expiry = models.IntegerField()
    severity = models.CharField(max_length=50, default="Medium")
    is_resolved = models.BooleanField(default=False)
    is_acknowledged = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):return f"Alert ({self.alert_type}) - Batch {self.batch.batch_number}"

class DemandForecast(models.Model):
    """
    Stores a demand forecast for a medicine over a defined period.
    Historical consumption is obtained from DispensingTransaction.
    Forecasts are generated by the forecasting service, not by this model.
    """

    class ForecastMethod(models.TextChoices): MOVING_AVERAGE = "MOVING_AVERAGE", "Three-Period Moving Average"
    medicine = models.ForeignKey("Medicine",on_delete=models.CASCADE,related_name="demand_forecasts",)

    # The period for which demand is being predicted.
    forecast_period_start = models.DateField()
    forecast_period_end = models.DateField()
    forecasted_demand_quantity = models.PositiveIntegerField()
    moving_avg_3month = models.PositiveIntegerField(default=0)

    # Method used to produce the forecast.
    forecast_method = models.CharField(max_length=30,choices=ForecastMethod.choices,default=ForecastMethod.MOVING_AVERAGE,)

    # Historical window used to calculate the forecast.
    history_start_date = models.DateField(null=True, blank=True)
    history_end_date = models.DateField(null=True, blank=True)

    # Number of actual dispensing transactions in the historical window.
    historical_transaction_count = models.PositiveIntegerField(default=0)
    confidence_score = models.DecimalField(max_digits=5,decimal_places=2,default=0,)

    # Optional error metrics, populated only after comparing a forecast
    # against actual consumption for the same forecast period.
    actual_demand_quantity = models.PositiveIntegerField(null=True,blank=True,)
    absolute_error = models.PositiveIntegerField(null=True,blank=True,)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-generated_at"]
        indexes = [
            models.Index(
                fields=["medicine", "forecast_period_start"],
                name="forecast_med_start_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(forecast_period_end__gte=models.F("forecast_period_start")),
                name="forecast_end_after_start",
            ),
            models.CheckConstraint(
                condition=Q(confidence_score__gte=0)
                & Q(confidence_score__lte=100),
                name="forecast_score_0_100",
            ),
        ]

    def __str__(self):
        return (
            f"{self.medicine.name}: "
            f"{self.forecasted_demand_quantity} units "
            f"({self.forecast_period_start} to {self.forecast_period_end})"
        )

class ProcurementRecommendation(models.Model):
    """
    Stores a proposed replenishment quantity based on forecast demand,
    usable inventory and outstanding procurement commitments.
    A recommendation is decision support. It does not place an order.
    """

    class Status(models.TextChoices):
        PENDING = "Pending", "Pending Review"
        APPROVED = "Approved", "Approved"
        REJECTED = "Rejected", "Rejected"
        ACTIONED = "Actioned", "Actioned"
        CANCELLED = "Cancelled", "Cancelled"

    class Urgency(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"

    medicine = models.ForeignKey("Medicine",on_delete=models.CASCADE,related_name="procurement_recommendations",)
    forecast = models.ForeignKey(
        DemandForecast,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="procurement_recommendations",
    )

    recommended_quantity = models.PositiveIntegerField()
    urgency_level = models.CharField(max_length=20,choices=Urgency.choices,default=Urgency.MEDIUM,)

    # Explain the forecast, stock position and reason for replenishment.
    reasoning = models.TextField(blank=True)
    status = models.CharField(max_length=20,choices=Status.choices,default=Status.PENDING,db_index=True,)
    is_actioned = models.BooleanField(default=False)

    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="procurement_recommendations_raised",
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="procurement_recommendations_reviewed",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index( fields=["medicine", "status"],name="recommend_med_status_idx",),]
        constraints = [models.CheckConstraint(condition=Q(recommended_quantity__gte=0),name="recommend_qty_nonnegative",),]

    def __str__(self):return (
            f"{self.medicine.name} - "
            f"{self.recommended_quantity} units ({self.status})"
        )

class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        LEGACY_PENDING = "PENDING", "Legacy Pending"
        PENDING_ADMIN_REVIEW = "Pending Admin Review", "Pending Admin Review"
        APPROVED = "Approved", "Approved"
        REJECTED = "Rejected", "Rejected"
        PLACED_WITH_SUPPLIER = "Placed with Supplier", "Placed with Supplier"

    id: int
    medicine = models.ForeignKey(Medicine,on_delete=models.CASCADE, null=True,blank=True,)
    supplier = models.ForeignKey(Supplier,on_delete=models.CASCADE,)
    recommendation = models.OneToOneField(ProcurementRecommendation,on_delete=models.SET_NULL,null=True,blank=True,related_name="purchase_order",)
    quantity_ordered = models.IntegerField(default=0)
    total_amount = models.DecimalField(max_digits=12,decimal_places=2,default=0.00,)
    order_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=30,choices=Status.choices,default=Status.PENDING_ADMIN_REVIEW,)
    total_cost = models.DecimalField(max_digits=12,decimal_places=2,default=0.00,)
    raised_by = models.ForeignKey( user,on_delete=models.SET_NULL,null=True,blank=True,)

    def __str__(self): return f"PO-{self.id}"

class SystemSetting(models.Model):
    key = models.CharField(max_length=100, unique=True)
    setting_key = models.CharField(max_length=100, blank=True)
    value = models.CharField(max_length=255)
    setting_value = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.key and not self.setting_key:
            self.setting_key = self.key
        if self.value and not self.setting_value:
            self.setting_value = self.value
    def __str__(self):return self.key

class AuditLog(models.Model):
    id: int
    user = models.ForeignKey(user, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=255)
    entity_type = models.CharField(max_length=100, blank=True, default="System")
    created_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.TextField(blank=True)
    def __str__(self):return f"AuditLog {self.id}"