from django.db import transaction
from django.utils import timezone
from .models import Medicine, MedicineBatch, DispensingTransaction

class FEFOEngine:
    @staticmethod
    def recommend_batch(medicine_id):
        """Return the earliest-expiring eligible batch."""
        return (
            MedicineBatch.objects.filter(
                medicine_id=medicine_id,
                medicine__is_active=True,
                quantity_available__gt=0,
                expiry_date__gt=timezone.localdate(),
                status="Active",
            ).order_by("expiry_date", "id").first()
        )

    @staticmethod
    @transaction.atomic
    def dispense_medicine(medicine_id,total_qty_to_dispense,user,selected_batch_id=None,notes="",patient_identifier="",):
        """Dispense stock under FEFO, recording any justified override."""
        # Validate the quantity before accessing or changing stock.
        try:
            quantity = int(total_qty_to_dispense)
        except (TypeError, ValueError): raise ValueError("Enter a valid whole-number quantity.")

        if isinstance(total_qty_to_dispense, bool): raise ValueError("Quantity must be a positive whole number.")
        if str(total_qty_to_dispense).strip() != str(quantity) or quantity <= 0:
            raise ValueError("Quantity must be a positive whole number.")

        try:
            medicine = Medicine.objects.get(pk=medicine_id,is_active=True,)
        except (Medicine.DoesNotExist, TypeError, ValueError):
            raise ValueError("The medicine does not exist or is inactive.")
        today = timezone.localdate()

        # Lock eligible rows to reduce the risk of concurrent overselling.
        eligible_batches = list(
            MedicineBatch.objects.select_for_update()
            .filter(medicine=medicine,quantity_available__gt=0,expiry_date__gt=today,status="Active",)
            .order_by("expiry_date", "id")
        )

        if not eligible_batches:
            expired_exists = MedicineBatch.objects.filter(medicine=medicine,quantity_available__gt=0,expiry_date__lte=today,).exists()
            if expired_exists:
                raise ValueError("No eligible stock is available. Existing stock is expired or otherwise ineligible; notify the Store Manager.")
            raise ValueError("No eligible stock is available. Check for depleted stock or raise a stock-out alert.")

        recommended_batch = eligible_batches[0]
        override = False
        batches_to_use = eligible_batches
        reason = (notes or "").strip()

        if selected_batch_id not in (None, ""):
            try:
                selected_id = int(selected_batch_id)
            except (TypeError, ValueError):raise ValueError("The selected batch is invalid.")

            selected_batch = next((b for b in eligible_batches if b.pk == selected_id), None,)
            if selected_batch is None: raise ValueError(
                    "The selected batch is expired, depleted, inactive or unavailable for this medicine.")

            override = selected_batch.pk != recommended_batch.pk
            if override and not reason: raise ValueError( "Enter a reason before overriding the FEFO recommendation.")
            batches_to_use = [selected_batch]
        total_available = sum( batch.quantity_available for batch in batches_to_use)

        if total_available < quantity:
            raise ValueError(
                f"Insufficient stock in the selected FEFO route. "
                f"Available: {total_available}; requested: {quantity}.")

        transactions_logged = []
        remaining = quantity

        for batch in batches_to_use:
            if remaining <= 0: break
            amount = min(batch.quantity_available, remaining)
            batch.quantity_available -= amount
            if batch.quantity_available == 0: batch.status = "Depleted"
            batch.save(update_fields=["quantity_available", "status"])

            record = DispensingTransaction.objects.create(
                medicine=medicine,
                batch=batch,
                dispensed_by=user,
                quantity_dispensed=amount,
                is_override=override,
                patient_identifier=(patient_identifier or "").strip(),
                notes=(f"FEFO override. Reason: {reason}" if override
                    else "Automated FEFO selection processing."
                ),
            )

            transactions_logged.append(record)
            remaining -= amount
        return transactions_logged