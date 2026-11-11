from django.contrib.auth.models import AbstractUser
from datetime import date
from django.utils import timezone
from django.db import models
from django.db.models import Q
from django.conf import settings
from django.core.validators import MinValueValidator

class Role(models.Model):
    SUPPORTED_ROLES = {"system administrator": ("System Administrator", "Manage accounts, application roles, settings and audit logs.",),
        "hospital admin": ("Hospital Admin","Oversee hospital-level activity and approve purchase orders.",),
        "hospital administrator": ("Hospital Administrator","Oversee hospital-level operations and approve purchase orders.",),
        "pharmacist": ("Pharmacist","Dispense medicines using FEFO and review dispensing alerts and reports.",),
        "store manager": ("Store Manager","Maintain stock batches, monitor expiry and raise procurement recommendations.",),
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
    def portal_url_name(self):
        return self.PORTAL_URLS.get( (self.name or "").strip().casefold(), "")

    @property
    def is_system_administrator(self):
        return (
                (self.name or "").strip().casefold()== "system administrator")
    def __str__(self):
      return self.name

class user(AbstractUser):
    other_name = models.CharField(max_length=150, blank=True)
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, blank=True)
    phone_number = models.CharField(max_length=15, blank=True)
    def __str__(self):
        role_name = self.role.name if self.role else "No role"
        return f"{self.username} - {self.role.name if self.role else 'No Role'}"

class Medicine(models.Model):
    medicine_id = models.CharField(max_length=20,unique=True,null=True,blank=True)
    medicine_name = models.CharField(max_length=255, unique=True)
    generic_name = models.CharField(max_length=255, blank=True)
    category = models.CharField(max_length=100, default="General")
    dosage_form = models.CharField(max_length=50)
    reorder_level = models.IntegerField(default=30)
    safety_stock_days = models.IntegerField(default=30)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.medicine_name

    def get_fefo_batches(self):
        return MedicineBatch.objects.filter(
            medicine=self,
            quantity_available__gt=0,
            expiry_date__gt=date.today(),
            status="Active"
        ).order_by('expiry_date', 'batch_id')

class MedicineBatch(models.Model):
    batch_id = models.CharField(max_length=20,unique=True,null=True,blank=True)
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE)
    batch_number = models.CharField(max_length=100)
    quantity_received = models.IntegerField()
    quantity_available = models.IntegerField()
    received_date = models.DateField()
    expiry_date = models.DateField()
    storage_location = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=50, default="Active")

    class Meta:
        ordering = ['expiry_date','batch_id']
        verbose_name_plural = "Medicine Batches"
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity_available__lte=models.F("quantity_received")),
                name="batch_available_lte_received"
            )
        ]

    # FIXED: Indentation fixed to attach method to class model block cleanly
    def __str__(self):
        return f"{self.medicine.medicine_name} (Batch: {self.batch_number}) - Exp: {self.expiry_date}"

class Supplier(models.Model):
    supplier_id = models.CharField( max_length=20,unique=True,null=True,blank=True)
    supplier_name = models.CharField(max_length=255, unique=True)
    contact_person = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone_number = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    delivery_lead_time_days = models.PositiveIntegerField(
        default=7,
        validators=[MinValueValidator(1)],
        help_text="Expected number of calendar days between placing an order and delivery."
    )

    def __str__(self):
        return self.supplier_name

class DispensingTransaction(models.Model):
    transaction_id = models.CharField(max_length=20,unique=True, null=True,blank=True,)
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, null=True, blank=True)
    batch = models.ForeignKey(MedicineBatch, on_delete=models.CASCADE)
    dispensed_by = models.ForeignKey(user, on_delete=models.SET_NULL, null=True, blank=True)
    quantity_dispensed = models.IntegerField()
    #dispensed_date = models.DateTimeField(auto_now_add=True)
    dispensed_at = models.DateTimeField(default=timezone.now)
    is_override = models.BooleanField(default=False)
    patient_identifier = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    def __str__(self):return f"Transaction {self.transaction_id} - {self.medicine.medicine_name if self.medicine else 'Unknown'}"

class ExpiryAlert(models.Model):
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, null=True, blank=True)
    batch = models.ForeignKey(MedicineBatch, on_delete=models.CASCADE)
    alert_type = models.CharField(max_length=50, choices=[('NEAR', 'Near Expiry'), ('EXPIRED', 'Expired')])
    days_to_expiry = models.IntegerField()
    severity = models.CharField(max_length=50, default="Medium")
    is_resolved = models.BooleanField(default=False)
    is_acknowledged = models.BooleanField(default=False)
    #created_at = models.DateTimeField(auto_now_add=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"Alert ({self.alert_type}) - Batch {self.batch.batch_number}"

class UserAlert(models.Model):
#Specific user receives personalized alert
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="user_alerts")

    # Alert information displayed in the shared alerts page.
    alert_type = models.CharField(max_length=50)
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True)
    severity = models.CharField(max_length=20, default="Medium")

    # Identifies the business record that triggered the alert.
    source_type = models.CharField(max_length=50, blank=True)
    source_id = models.CharField(max_length=20,null=True,blank=True)

    # Each recipient manages their own alert status.
    is_read = models.BooleanField(default=False)
    is_resolved = models.BooleanField(default=False)

    action_url = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "is_read"],name="useralert_recipient_read_idx")]
    def __str__(self):
          return f"{self.title} - {self.recipient.username}"

class DemandForecast(models.Model):
    """
    Stores a demand forecast for a medicine over a defined period.
    Historical consumption is obtained from DispensingTransaction.
    Forecasts are generated by the forecasting service, not by this model.
    """

    class ForecastMethod(models.TextChoices): MOVING_AVERAGE = "MOVING_AVERAGE", "Three-Period Moving Average"

    source_forecast_id = models.CharField(max_length=30, unique=True,null=True,blank=True,editable=False,
                    help_text="Original forecast identifier from the synthetic dataset.")
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
    absolute_error = models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True,
    help_text = "Absolute forecast error against actual demand normalized to a 30-day equivalent."                                )
    generated_at = models.DateTimeField(default=timezone.now)

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
            f"{self.medicine.medicine_name}: "
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

    source_recommendation_id = models.CharField(max_length=30,unique=True, null=True,blank=True,editable=False,
        help_text="Original recommendation identifier from the synthetic dataset.")
    medicine = models.ForeignKey("Medicine",on_delete=models.CASCADE,related_name="procurement_recommendations",)
    forecast = models.ForeignKey(DemandForecast,on_delete=models.SET_NULL,null=True,blank=True,related_name="procurement_recommendations",)
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
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    forecast_demand_quantity = models.PositiveIntegerField(
        default=0,
        help_text="Forecasted demand over the standard 30-day forecast period."
    )

    eligible_stock_quantity = models.PositiveIntegerField(
        default=0,
        help_text="Current stock eligible for dispensing under FEFO rules."
    )

    incoming_stock_quantity = models.PositiveIntegerField(
        default=0,
        help_text="Usable stock expected from outstanding purchase orders."
    )

    projected_stock_position = models.IntegerField(
        default=0,
        help_text="Projected inventory position after accounting for incoming stock and expected demand during lead time."
    )

    lead_time_days = models.PositiveIntegerField(
        default=7,
        validators=[MinValueValidator(1)],
        help_text="Lead-time assumption used when calculating this recommendation."
    )

    target_stock_quantity = models.PositiveIntegerField(
        default=0,
        help_text="Target inventory required for lead time, review period and safety-stock coverage."
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["medicine", "status"],
                name="recommend_med_status_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(recommended_quantity__gte=0),
                name="recommend_qty_nonnegative",
            ),
        ]

    def __str__(self):return (
            f"{self.medicine.medicine_name} - "
            f"{self.recommended_quantity} units ({self.status})"
        )

class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        LEGACY_PENDING = "PENDING", "Legacy Pending"
        PENDING_ADMIN_REVIEW = "Pending Admin Review", "Pending Admin Review"
        APPROVED = "Approved", "Approved"
        REJECTED = "Rejected", "Rejected"
        PLACED_WITH_SUPPLIER = "Placed with Supplier", "Placed with Supplier"

    purchase_order_id = models.CharField(max_length=20,unique=True,null=True,blank=True)
    medicine = models.ForeignKey(Medicine,on_delete=models.CASCADE, null=True,blank=True,)
    supplier = models.ForeignKey(Supplier,on_delete=models.CASCADE,)
    recommendation = models.OneToOneField(ProcurementRecommendation,on_delete=models.SET_NULL,null=True,blank=True,related_name="purchase_order",)
    quantity_ordered = models.IntegerField(default=0)
    #total_amount = models.DecimalField(max_digits=12,decimal_places=2,default=0.00,)
    order_date = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=30,choices=Status.choices,default=Status.PENDING_ADMIN_REVIEW,)
    total_cost = models.DecimalField(max_digits=12,decimal_places=2,default=0.00,)
    raised_by = models.ForeignKey( user,on_delete=models.SET_NULL,null=True,blank=True,)

    def __str__(self): return f"PO-{self.purchase_order_id}"

class GoodsReceipt(models.Model): #Records physical delivery against approved purchase orders that have been placed with the supplier.
        source_goods_receipt_id = models.CharField(max_length=30,unique=True,null=True,blank=True,
           editable=False,help_text="Original goods receipt identifier from the synthetic dataset.")
        purchase_order = models.ForeignKey(PurchaseOrder,on_delete=models.PROTECT, related_name="goods_receipts",)
        received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,null=True,blank=True,
                 related_name="goods_receipts_recorded",)
        delivery_date = models.DateField(default=timezone.localdate)
        received_at = models.DateTimeField(default=timezone.now)
        delivery_reference = models.CharField(max_length=100,blank=True,)
        notes = models.TextField(blank=True)

        class Meta: ordering = ["-received_at"] #holds data about data
        def __str__(self): return f"Receipt for PO-{self.purchase_order_id}"

class GoodsReceiptItem(models.Model):
    # Records individual medicine batches physically verified during a goods receipt.
    class InspectionStatus(models.TextChoices):
        PENDING = "Pending", "Pending Inspection"
        ACCEPTED = "Accepted", "Accepted"
        REJECTED = "Rejected", "Rejected"
        QUARANTINED = "Quarantined", "Quarantined"
    goods_receipt = models.ForeignKey( GoodsReceipt,on_delete=models.PROTECT, related_name="items")
    source_receipt_item_id = models.CharField(max_length=30,unique=True, null=True,blank=True,
        editable=False,help_text="Original receipt item identifier from the synthetic dataset.")
    batch_number = models.CharField(max_length=100)
    quantity_received = models.PositiveIntegerField()
    expiry_date = models.DateField()
    storage_location = models.CharField(max_length=100,blank=True)
    inspection_status = models.CharField(max_length=20, choices=InspectionStatus.choices,default=InspectionStatus.PENDING)

    inspected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True, related_name="goods_receipt_items_inspected")

    inspected_at = models.DateTimeField(null=True,blank=True)
    inspection_notes = models.TextField(blank=True)
    medicine_batch = models.OneToOneField(
        MedicineBatch,on_delete=models.PROTECT,related_name="goods_receipt_item", null = True,blank = True)

    class Meta:
        ordering = ["expiry_date"]
        constraints = [ models.CheckConstraint( condition=models.Q(quantity_received__gt=0),name="goods_receipt_qty_positive"),]

    def __str__(self):
        return f"{self.batch_number} - {self.quantity_received} units"

class SystemSetting(models.Model):
    setting_id = models.CharField(max_length=20,unique=True,null=True,blank=True)
    key = models.CharField(max_length=100, unique=True)
    setting_key = models.CharField(max_length=100, blank=True)
    value = models.CharField(max_length=255)
    setting_value = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.key and not self.setting_key:self.setting_key = self.key
        if self.value and not self.setting_value:self.setting_value = self.value
    def __str__(self):return self.key

import uuid
def generate_audit_log_id():
    return f"AL{uuid.uuid4().hex[:18].upper()}"

class AuditLog(models.Model):
    audit_log_id = models.CharField(max_length=20,unique=True,null=True,blank=True,default=generate_audit_log_id)
    user = models.ForeignKey(user, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=255)
    entity_type = models.CharField(max_length=100, blank=True, default="System")
    created_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.TextField(blank=True)
    def __str__(self):return f"AuditLog {self.audit_log_id}"
