from django.db import transaction
from django.utils import timezone
from .models import Medicine, MedicineBatch, DispensingTransaction

class FEFOEngine:
 @staticmethod
def recommend_batch(medicine_id): #Retrieves the exact optimal batch that should be used for next checkout.
 try:
     medicine = Medicine.objects.get(id=medicine_id)
     return medicine.get_fefo_batches().first()
     except Medicine.DoesNotExist: return None

def dispense_medicine(medicine_id, total_qty_to_dispense, user, selected_batch_id=None, notes=""):
    with transaction.atomic():
        medicine = Medicine.objects.get(id=medicine_id)
        remaining_to_dispense = total_qty_to_dispense
        transactions_logged = []

        # Check for explicitly selected batch (Pharmacist Manual Override)
        if selected_batch_id:
            optimal_batch = medicine.get_fefo_batches().first()
            is_override = int(selected_batch_id) != optimal_batch.id if optimal_batch else True
            batches = MedicineBatch.objects.filter(id=selected_batch_id)

            else:is_override = False
            batches = medicine.get_fefo_batches()
            if not batches.exists(): raise ValueError("No active inventory stock pools available for selection.")
            for batch in batches:
                if remaining_to_dispense <= 0: break
                if batch.quantity_available <= 0:continue
                dispense_amount = min(batch.quantity_available, remaining_to_dispense)
                batch.quantity_available -= dispense_amount # Transaction State Mutations

                if batch.quantity_available == 0:
                    batch.status = "Depleted"
                batch.save()

                tx = DispensingTransaction.objects.create(
                    medicine=medicine,
                    batch=batch,
                    dispensed_by=user,
                    quantity_dispensed=dispense_amount,
                    is_override=is_override,
                    notes=notes if is_override else "Automated FEFO selection processing."
                )
                transactions_logged.append(tx)
                remaining_to_dispense -= dispense_amount

            if remaining_to_dispense > 0: raise ValueError(f"Insufficient total stock. Could not fulfill remaining {remaining_to_dispense} units.")
            return transactions_logged