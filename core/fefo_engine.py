from django.db import transaction
from django.utils import timezone
from .models import Medicine, MedicineBatch, DispensingTransaction

class FEFOEngine:
    @staticmethod
    def recommend_batch(medicine_id):
        """Return the next eligible batch under the FEFO policy."""
        try:
            medicine = Medicine.objects.get(id=medicine_id)
            return medicine.get_fefo_batches().first()
        except Medicine.DoesNotExist:  return None

    @staticmethod
    @transaction.atomic
    def dispense_medicine(
        medicine_id,
        total_qty_to_dispense,
        user,
        selected_batch_id=None,
        notes="",
    ):
        """
        Dispense medicine using FEFO.
        An explicitly selected batch is treated as a manual override
        when it differs from the recommended FEFO batch.
        """
        if total_qty_to_dispense <= 0: raise ValueError("Quantity to dispense must be greater than zero.")

        medicine = Medicine.objects.get(id=medicine_id)
        remaining_to_dispense = total_qty_to_dispense
        transactions_logged = []

        eligible_batches = medicine.get_fefo_batches()
        optimal_batch = eligible_batches.first()

        if selected_batch_id is not None:
            selected_batch = eligible_batches.filter(
                id=selected_batch_id
            ).first()

            if selected_batch is None:
                raise ValueError(
                    "The selected batch is unavailable, expired, inactive, or has no eligible stock.")

            is_override = ( optimal_batch is None or selected_batch.id != optimal_batch.id )
            batches = [selected_batch]
        else:
            is_override = False
            batches = eligible_batches

        if not batches: raise ValueError( "No active inventory stock pools are available.")

        for batch in batches:
            if remaining_to_dispense <= 0: break
            if batch.quantity_available <= 0: continue

            dispense_amount = min( batch.quantity_available, remaining_to_dispense,)
            batch.quantity_available -= dispense_amount

            if batch.quantity_available == 0:batch.status = "Depleted"
            batch.save()

            tx = DispensingTransaction.objects.create(
                medicine=medicine,
                batch=batch,
                dispensed_by=user,
                quantity_dispensed=dispense_amount,
                is_override=is_override,
                notes=(
                    notes
                    if is_override
                    else "Automated FEFO selection processing."
                ),
            )
            transactions_logged.append(tx)
            remaining_to_dispense -= dispense_amount

        if remaining_to_dispense > 0:
            raise ValueError(
                "Insufficient stock. Could not fulfill the remaining "
                f"{remaining_to_dispense} units."
            )
        return transactions_logged