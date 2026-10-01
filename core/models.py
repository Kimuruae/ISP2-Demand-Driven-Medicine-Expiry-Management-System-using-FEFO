from django.contrib.auth.models import AbstractUser
from django.db import models

class Role(models.Model):
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name

class User(AbstractUser):
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, blank=True)
    phone_number = models.CharField(max_length=15, blank=True)

    def __str__(self):
        return f"{self.username} - {self.role.name if self.role else 'No Role'}"

class Medicine(models.Model):
    name = models.CharField(max_length=255)
    medicine_name = models.CharField(max_length=255, blank=True) # Linked to admin panel field
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

    def __str__(self):
        return self.name

class MedicineBatch(models.Model):
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE)
    batch_number = models.CharField(max_length=100)
    quantity_received = models.IntegerField()
    quantity_available = models.IntegerField()
    received_date = models.DateField()
    expiry_date = models.DateField()
    storage_location = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=50, default="Active")

    def __str__(self):
        return f"{self.medicine.name} - {self.batch_number}"

class Supplier(models.Model):
    supplier_name = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255, blank=True)
    contact_person = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone_number = models.CharField(max_length=15, blank=True)
    phone = models.CharField(max_length=15, blank=True) # Linked to admin list_display[2]
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True) # Linked to admin list_display[3]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.supplier_name and not self.name:
            self.name = self.supplier_name
        if self.phone_number and not self.phone:
            self.phone = self.phone_number

    def __str__(self):
        return self.supplier_name

class DispensingTransaction(models.Model):
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, null=True, blank=True)
    batch = models.ForeignKey(MedicineBatch, on_delete=models.CASCADE)
    dispensed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    quantity_dispensed = models.IntegerField()
    dispensed_date = models.DateTimeField(auto_now_add=True)
    dispensed_at = models.DateTimeField(auto_now_add=True)
    is_override = models.BooleanField(default=False)
    patient_identifier = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"Transaction {self.id}"

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

    def __str__(self):
        return f"Alert for {self.batch.batch_number}"

Alert = ExpiryAlert

class DemandForecast(models.Model):
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE)
    forecasted_demand_quantity = models.IntegerField()
    forecast_period_start = models.DateField()
    forecast_period_end = models.DateField()
    period_start = models.DateField(null=True, blank=True)
    moving_avg_3month = models.IntegerField(default=0)
    confidence_score = models.DecimalField(max_digits=5, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Forecast - {self.medicine.name}"

class ProcurementRecommendation(models.Model):
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE)
    recommended_quantity = models.IntegerField()
    urgency_level = models.CharField(max_length=20)
    reasoning = models.TextField(blank=True)
    status = models.CharField(max_length=50, default="Pending")
    is_actioned = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"Recommendation - {self.medicine.name}"

class PurchaseOrder(models.Model):
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, null=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE)
    quantity_ordered = models.IntegerField(default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    order_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, default='PENDING')
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    def __str__(self):
        return f"PO-{self.id}"

class SystemSetting(models.Model):
    key = models.CharField(max_length=100, unique=True)
    setting_key = models.CharField(max_length=100, blank=True) # Linked to admin list_display[0]
    value = models.CharField(max_length=255)
    setting_value = models.CharField(max_length=255, blank=True) # Linked to admin list_display[1]
    description = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True) # Linked to admin list_display[2]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.key and not self.setting_key:
            self.setting_key = self.key
        if self.value and not self.setting_value:
            self.setting_value = self.value

    def __str__(self):
        return self.key

class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=255)
    entity_type = models.CharField(max_length=100, blank=True, default="System")
    timestamp = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.TextField(blank=True)

    def __str__(self):
        return f"AuditLog {self.id}"
