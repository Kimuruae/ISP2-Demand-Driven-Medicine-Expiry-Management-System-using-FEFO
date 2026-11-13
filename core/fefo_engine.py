from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from .models import Medicine, MedicineBatch, DispensingTransaction

class FEFOEngine:
    @staticmethod
    def _validate_positive_integer(value, field_name): #Validate a strictly positive whole-number input.
        if isinstance(value, bool):
            raise ValueError(f"{field_name} must be a positive whole number.")

        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} must be a positive whole number.")

        if str(value).strip() != str(number) or number <= 0:
            raise ValueError(f"{field_name} must be a positive whole number.")
        return number

    @staticmethod
    def _get_eligible_batches(medicine, required_valid_until, lock=False):
    #Return batches that satisfy general stock eligibility and prescription-period validity, ordered using FEFO.
        batches = MedicineBatch.objects.filter(
            medicine=medicine,
            medicine__is_active=True,
            quantity_available__gt=0,
            expiry_date__gt=timezone.localdate(),
            expiry_date__gte=required_valid_until,
            status="Active",
        ).order_by("expiry_date", "id")

        if lock:  batches = batches.select_for_update()
        return batches

    # Recommend the earliest-expiring batch safe for the prescription period.
    @staticmethod
    def recommend_batch(medicine_id, prescription_duration_days):
        duration = FEFOEngine._validate_positive_integer(prescription_duration_days,"Prescription duration",)

        try:
            medicine = Medicine.objects.get(pk=medicine_id,is_active=True,)
        except (Medicine.DoesNotExist, TypeError, ValueError): raise ValueError("The medicine does not exist or is inactive.")

        today = timezone.localdate()
        required_valid_until = today + timedelta(days=duration - 1)
        return FEFOEngine._get_eligible_batches(medicine,required_valid_until,).first()

    @staticmethod
    @transaction.atomic
    def dispense_medicine(
        medicine_id,
        total_qty_to_dispense,
        user,
        prescription_duration_days,
        selected_batch_id=None,
        notes="",
        patient_identifier="",
    ):
        """
        Dispensing medicine using prescription-period-aware FEFO. This is mainly for patient's safety
        Automatic allocation uses the earliest-expiring eligible batches.
        Manual selection is permitted only when the selected batch meets
        the same prescription-period validity requirements.
        """
        quantity = FEFOEngine._validate_positive_integer(total_qty_to_dispense, "Dispensing quantity",)
        duration = FEFOEngine._validate_positive_integer(prescription_duration_days,"Prescription duration",)

        try:
            medicine = Medicine.objects.get( pk=medicine_id,is_active=True,)
        except (Medicine.DoesNotExist, TypeError, ValueError):
            raise ValueError("The medicine does not exist or is inactive.")
        today = timezone.localdate()

        # The dispensing date is counted as day one.
        required_valid_until = today + timedelta(days=duration - 1)

        # Lock eligible batches to reduce concurrent stock deduction.
        eligible_batches = list(FEFOEngine._get_eligible_batches(medicine,required_valid_until, lock=True,))

        if not eligible_batches:
            generally_eligible = MedicineBatch.objects.filter(
                medicine=medicine,
                quantity_available__gt=0,
                expiry_date__gt=today,
                status="Active",
            ).exists()

            if generally_eligible:
                raise ValueError(
                    "Stock exists, but no available batch meets the "
                    "required prescription-period validity date "
                    f"({required_valid_until}). Notify the Store Manager."
                )

            expired_exists = MedicineBatch.objects.filter(
                medicine=medicine,
                quantity_available__gt=0,
                expiry_date__lte=today,
            ).exists()

            if expired_exists:
                raise ValueError(
                    "No eligible stock is available. Existing stock is "
                    "expired or otherwise ineligible. Notify the Store Manager."
                )

            raise ValueError(
                "No eligible stock is available. Check depleted stock "
                "or raise a stock-out alert."
            )

        recommended_batch = eligible_batches[0]
        override = False
        batches_to_use = eligible_batches
        reason = (notes or "").strip()

        # Validate an explicitly selected batch.
        if selected_batch_id not in (None, ""):
            try:
                selected_id = int(selected_batch_id)
            except (TypeError, ValueError):raise ValueError("The selected batch is invalid.")
            selected_batch = next( (batch for batch in eligible_batches if batch.pk == selected_id),None, )

            if selected_batch is None:
                raise ValueError(
                    "The selected batch is unavailable or does not meet the prescription-period validity requirements."
                )
            override = selected_batch.pk != recommended_batch.pk

            if override and not reason:
                raise ValueError("Enter a reason for overriding the FEFO recommendation.")

            # Explicit batch selection remains limited to that batch.
            batches_to_use = [selected_batch]
        total_available = sum( batch.quantity_available for batch in batches_to_use)

        if total_available < quantity:
            raise ValueError(
                f"Insufficient eligible stock. Available: "
                f"{total_available}; requested: {quantity}. "
                "Review inventory and procurement requirements."
            )

        transactions_logged = []
        remaining = quantity

        for batch in batches_to_use:
            if remaining <= 0:break
            amount = min(batch.quantity_available,remaining,)
            batch.quantity_available -= amount

            if batch.quantity_available == 0:batch.status = "Depleted"
            batch.save(update_fields=["quantity_available","status",])

            if override:
                transaction_notes = (
                    f"FEFO override. Reason: {reason}. "
                    f"Prescription duration: {duration} days. "
                    f"Required batch validity through: "
                    f"{required_valid_until}."
                )
            else:
                transaction_notes = (
                    "Automated prescription-period-aware FEFO allocation. "
                    f"Prescription duration: {duration} days. "
                    f"Required batch validity through: "
                    f"{required_valid_until}."
                )

            record = DispensingTransaction.objects.create(
                medicine=medicine,
                batch=batch,
                dispensed_by=user,
                quantity_dispensed=amount,
                is_override=override,
                patient_identifier=(patient_identifier or "").strip(),
                notes=transaction_notes,
            )

            transactions_logged.append(record)
            remaining -= amount
        return transactions_logged