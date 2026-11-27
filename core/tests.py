from datetime import timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.urls import reverse
from core.models import Role

from django.test import TestCase
from django.utils import timezone

from core.models import (Medicine,MedicineBatch,DispensingTransaction,DemandForecast,ProcurementRecommendation,ExpiryAlert,)
from core.fefo_engine import FEFOEngine
from core.forecasting_engine import ForecastingEngine


class FEFOEngineTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()

        self.medicine = Medicine.objects.create(
            medicine_name="Test Paracetamol",
            generic_name="Paracetamol",
            category="Analgesic",
            dosage_form="Tablet",
            reorder_level=30,
            safety_stock_days=30,
            is_active=True,
        )

    def create_batch(self, batch_number, quantity, expiry_days):
        return MedicineBatch.objects.create(
            medicine=self.medicine,
            batch_number=batch_number,
            quantity_received=quantity,
            quantity_available=quantity,
            received_date=self.today,
            expiry_date=self.today + timedelta(days=expiry_days),
            storage_location="Test Store",
            status="Active",
        )

    def test_recommend_batch_selects_earliest_prescription_valid_batch(self):
        self.create_batch("BATCH-001", 20, 10)
        later_batch = self.create_batch("BATCH-002", 30, 60)
        recommended = FEFOEngine.recommend_batch(self.medicine.id, prescription_duration_days=30,)
        self.assertEqual(recommended, later_batch)

    def test_dispensing_splits_quantity_across_batches_in_fefo_order(self):
        first_batch = self.create_batch("BATCH-003", 10, 60)
        second_batch = self.create_batch("BATCH-004", 20, 90)
        transactions = FEFOEngine.dispense_medicine(
            medicine_id=self.medicine.id,
            total_qty_to_dispense=15,user=None,
            prescription_duration_days=30,
        )

        self.assertEqual(len(transactions), 2)
        self.assertEqual(transactions[0].batch, first_batch)
        self.assertEqual(transactions[0].quantity_dispensed, 10)
        self.assertEqual(transactions[1].batch, second_batch)
        self.assertEqual(transactions[1].quantity_dispensed, 5)

        first_batch.refresh_from_db()
        second_batch.refresh_from_db()

        self.assertEqual(first_batch.quantity_available, 0)
        self.assertEqual(first_batch.status, "Depleted")
        self.assertEqual(second_batch.quantity_available, 15)
        self.assertEqual(DispensingTransaction.objects.filter(medicine=self.medicine).count(),2,)

    def test_dispensing_rejects_batch_that_expires_before_prescription_ends(self):
        self.create_batch("BATCH-005", 50, 10)

        with self.assertRaisesMessage(ValueError,"prescription-period validity",
        ):
            FEFOEngine.dispense_medicine(
                medicine_id=self.medicine.id,
                total_qty_to_dispense=5,
                user=None,
                prescription_duration_days=30,
            )

        self.assertEqual(DispensingTransaction.objects.filter(medicine=self.medicine).count(),0,)

    def test_manual_later_batch_override_requires_and_records_reason(self):
        first_batch = self.create_batch("BATCH-006", 30, 60)
        later_batch = self.create_batch("BATCH-007", 30, 90)

        transactions = FEFOEngine.dispense_medicine(
            medicine_id=self.medicine.id,
            total_qty_to_dispense=5,
            user=None,
            prescription_duration_days=30,
            selected_batch_id=later_batch.id,
            notes="Urgent stock rotation decision",
        )

        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].batch, later_batch)
        self.assertTrue(transactions[0].is_override)
        self.assertIn("Urgent stock rotation decision",transactions[0].notes,)

        first_batch.refresh_from_db()
        later_batch.refresh_from_db()

        self.assertEqual(first_batch.quantity_available, 30)
        self.assertEqual(later_batch.quantity_available, 25)

    def test_manual_later_batch_override_without_reason_is_rejected(self):
        self.create_batch("BATCH-008", 30, 60)
        later_batch = self.create_batch("BATCH-009", 30, 90)

        with self.assertRaisesMessage(
            ValueError,"Enter a reason for overriding the FEFO recommendation.",
        ):
            FEFOEngine.dispense_medicine(
                medicine_id=self.medicine.id,
                total_qty_to_dispense=5,
                user=None,
                prescription_duration_days=30,
                selected_batch_id=later_batch.id,
            )

        later_batch.refresh_from_db()

        self.assertEqual(later_batch.quantity_available, 30)
        self.assertEqual(DispensingTransaction.objects.filter(medicine=self.medicine).count(),0,)

    def test_manual_selection_rejects_batch_invalid_for_prescription_period(self):
        early_batch = self.create_batch("BATCH-010", 30, 10)
        self.create_batch("BATCH-011", 30, 60)

        with self.assertRaisesMessage(
            ValueError,"does not meet the prescription-period validity requirements",
        ):
            FEFOEngine.dispense_medicine(
                medicine_id=self.medicine.id,
                total_qty_to_dispense=5,
                user=None,
                prescription_duration_days=30,
                selected_batch_id=early_batch.id,
                notes="Attempted manual selection",
            )

        early_batch.refresh_from_db()

        self.assertEqual(early_batch.quantity_available, 30)
        self.assertEqual(DispensingTransaction.objects.filter(medicine=self.medicine).count(),0,)

    def test_insufficient_eligible_stock_does_not_partially_deduct_inventory(self):
        first_batch = self.create_batch("BATCH-012", 5, 60)
        second_batch = self.create_batch("BATCH-013", 5, 90)

        with self.assertRaisesMessage(ValueError,"Insufficient eligible stock.",
        ):
            FEFOEngine.dispense_medicine(
                medicine_id=self.medicine.id,
                total_qty_to_dispense=15,
                user=None,
                prescription_duration_days=30,
            )

        first_batch.refresh_from_db()
        second_batch.refresh_from_db()

        self.assertEqual(first_batch.quantity_available, 5)
        self.assertEqual(second_batch.quantity_available, 5)
        self.assertEqual(DispensingTransaction.objects.filter(medicine=self.medicine).count(),0,)

class ForecastingEngineTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.medicine = Medicine.objects.create(
            medicine_name="Test Amoxicillin",
            generic_name="Amoxicillin",
            category="Antibiotic",
            dosage_form="Capsule",
            reorder_level=30,
            safety_stock_days=0,
            is_active=True,
        )

        self.batch = MedicineBatch.objects.create(
            medicine=self.medicine,
            batch_number="FORECAST-BATCH-001",
            quantity_received=10,
            quantity_available=10,
            received_date=self.today,
            expiry_date=self.today + timedelta(days=180),
            storage_location="Test Store",
            status="Active",
        )

    def test_three_period_moving_average_and_recommendation(self):
        now = timezone.now()
        historical_consumption = [
            (15, 30),
            (45, 60),
            (75, 90),
        ]

        for days_ago, quantity in historical_consumption:
            DispensingTransaction.objects.create(
                medicine=self.medicine,
                batch=self.batch,
                dispensed_by=None,
                quantity_dispensed=quantity,
                dispensed_at=now - timedelta(days=days_ago),
            )

        forecast = ForecastingEngine.calculate_3_month_forecast(self.medicine.id)

        # Expected moving average: (30 + 60 + 90) / 3 = 60.
        self.assertEqual(forecast.forecasted_demand_quantity, 60)
        self.assertEqual(forecast.moving_avg_3month, 60)
        self.assertEqual(forecast.historical_transaction_count,3,)
        self.assertEqual(forecast.forecast_method,DemandForecast.ForecastMethod.MOVING_AVERAGE,)

        # Consistency score: 100 * (1 - (90 - 30) / 90).
        self.assertEqual(forecast.confidence_score,Decimal("33.33"),)

        recommendation = ProcurementRecommendation.objects.get(medicine=self.medicine,forecast=forecast,)

        # Target stock = 60; eligible stock = 10.
        # Recommended quantity = 60 - 10 = 50.

        self.assertEqual(recommendation.recommended_quantity, 50)
        self.assertEqual(recommendation.forecast_demand_quantity, 60)
        self.assertEqual(recommendation.eligible_stock_quantity, 10)
        self.assertEqual(recommendation.incoming_stock_quantity, 0)
        self.assertEqual(recommendation.target_stock_quantity, 60)
        self.assertEqual(recommendation.projected_stock_position, -50)
        self.assertEqual(recommendation.lead_time_days, 7)
        self.assertEqual(recommendation.status, "Pending")

    def test_forecast_is_recorded_when_no_historical_transactions_exist(self):
        forecast = ForecastingEngine.calculate_3_month_forecast(self.medicine.id)
        self.assertEqual(forecast.forecasted_demand_quantity, 0)
        self.assertEqual(forecast.historical_transaction_count, 0)

        self.assertTrue(DemandForecast.objects.filter(medicine=self.medicine).exists())
        self.assertFalse(ProcurementRecommendation.objects.filter(medicine=self.medicine).exists())

#Inventory Tests
class InventoryTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.store_manager_role = Role.objects.create(name="Store Manager")

        user = get_user_model()
        self.store_manager = user.objects.create_user(
            username="inventory_manager",
            password="TestPassword123!",
            role=self.store_manager_role,
        )

        self.client.login(
            username="inventory_manager",
            password="TestPassword123!",
        )

        self.medicine = Medicine.objects.create(
            medicine_name="Inventory Test Paracetamol",
            generic_name="Paracetamol",
            category="Analgesic",
            dosage_form="Tablet",
            reorder_level=30,
            safety_stock_days=30,
            is_active=True,
        )

    def create_batch(
        self,
        batch_number,
        quantity,
        expiry_days,
        status="Active",
        medicine=None,
    ):
        return MedicineBatch.objects.create(
            medicine=medicine or self.medicine,
            batch_number=batch_number,
            quantity_received=max(quantity, 1),
            quantity_available=quantity,
            received_date=self.today,
            expiry_date=self.today + timedelta(days=expiry_days),
            storage_location="Test Store",
            status=status,
        )

    def test_inventory_displays_only_eligible_stock(self):
        eligible = self.create_batch("INV-001", 50, 60)
        self.create_batch("INV-002", 20, -5 )
        self.create_batch("INV-003", 0, 60)
        self.create_batch("INV-004", 20, 60, status="Inactive")

        inactive_medicine = Medicine.objects.create(
            medicine_name="Inactive Test Medicine",
            generic_name="Inactive Medicine",
            category="General",
            dosage_form="Tablet",
            is_active=False,
        )

        self.create_batch(
            "INV-005",
            20,
            60,
            medicine=inactive_medicine,
        )

        response = self.client.get(
            reverse("inventory")
        )

        self.assertEqual(response.status_code, 200)

        displayed_batches = list(
            response.context["batches"]
        )

        self.assertEqual(displayed_batches, [eligible])

    def test_inventory_reports_calculate_stock_totals(self):
        self.create_batch("REP-001", 50, 60)
        self.create_batch("REP-002", 20, -5)
        self.create_batch("REP-003", 10, 15)
        self.create_batch("REP-004", 0, 60)

        response = self.client.get(
            reverse("inventory_reports")
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.context["total_batches"],
            4,
        )

        self.assertEqual(
            response.context["total_units"],
            80,
        )

        self.assertEqual(
            response.context["expired_batches"],
            1,
        )

        self.assertEqual(
            response.context["expiring_soon"],
            1,
        )

    def test_inventory_alerts_classify_batches_correctly(self):
        self.create_batch("ALT-001", 20, -2)
        self.create_batch("ALT-002", 30, 10)
        self.create_batch("ALT-003", 0, 60)
        self.create_batch("ALT-004", 40, 90)

        response = self.client.get(
            reverse("inventory_alerts")
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.context["expired_batches"].count(),
            1,
        )

        self.assertEqual(
            response.context["expiring_batches"].count(),
            1,
        )

        self.assertEqual(
            response.context["out_of_stock_batches"].count(),
            1,
        )

    def test_non_store_manager_cannot_access_inventory(self):
        Role.objects.create(name="Pharmacist")
        user = get_user_model()
        pharmacist = user.objects.create_user(
            username="inventory_pharmacist",
            password="TestPassword123!",
            role=Role.objects.get(name="Pharmacist"),
        )
        self.client.force_login(pharmacist)

        response = self.client.get(
            reverse("inventory")
        )
        self.assertEqual(response.status_code, 403)

# PROCUREMENT, RECEIVING AND INTEGRATION TESTS
from core.models import (
    Supplier,
    PurchaseOrder,
    GoodsReceipt,
    GoodsReceiptItem,
    AuditLog,
)


class ProcurementTests(TestCase):
    def setUp(self):
        user = get_user_model()

        self.store_role = Role.objects.create(name="Store Manager")
        self.procurement_role = Role.objects.create(name="Procurement Officer")
        self.admin_role = Role.objects.create(name="Hospital Admin")

        self.store_manager = user.objects.create_user(
            username="procurement_store_manager",
            password="TestPassword123!",
            role=self.store_role,
        )

        self.procurement_officer = user.objects.create_user(
            username="procurement_officer",
            password="TestPassword123!",
            role=self.procurement_role,
        )

        self.hospital_admin = user.objects.create_user(
            username="procurement_hospital_admin",
            password="TestPassword123!",
            role=self.admin_role,
        )

        self.medicine = Medicine.objects.create(
            medicine_name="Procurement Test Paracetamol",
            generic_name="Paracetamol",
            category="Analgesic",
            dosage_form="Tablet",
            reorder_level=30,
            safety_stock_days=30,
            is_active=True,
        )

        self.supplier = Supplier.objects.create(
            supplier_name="Test Medical Supplier",
        )

    def create_recommendation(self):
        return ProcurementRecommendation.objects.create(
            medicine=self.medicine,
            recommended_quantity=100,
            urgency_level="HIGH",
            reasoning="Stock has fallen below the reorder threshold.",
            status=ProcurementRecommendation.Status.PENDING,
            raised_by=self.store_manager,
        )

    def test_store_manager_can_raise_procurement_recommendation(self):
        self.client.force_login(self.store_manager)

        response = self.client.post(
            reverse("store_manager_recommendations"),
            {
                "medicine_id": self.medicine.pk,
                "recommended_quantity": 100,
                "urgency_level": "HIGH",
                "justification": "Stock is below the reorder threshold.",
            },
        )
        self.assertEqual(response.status_code, 302)
        recommendation = ProcurementRecommendation.objects.get(medicine=self.medicine)

        self.assertEqual(recommendation.recommended_quantity, 100)
        self.assertEqual(recommendation.raised_by, self.store_manager)
        self.assertEqual(
            recommendation.status,
            ProcurementRecommendation.Status.PENDING,
        )

        self.assertTrue(
            AuditLog.objects.filter(
                action="Procurement recommendation raised"
            ).exists()
        )

    def test_store_manager_cannot_raise_recommendation_with_invalid_quantity(self):
        self.client.force_login(self.store_manager)
        response = self.client.post(
            reverse("store_manager_recommendations"),
            {
                "medicine_id": self.medicine.pk,
                "recommended_quantity": 0,
                "urgency_level": "HIGH",
                "justification": "Invalid quantity test.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            ProcurementRecommendation.objects.filter(
                medicine=self.medicine
            ).exists()
        )

    def test_procurement_officer_can_view_pending_recommendations(self):
        recommendation = self.create_recommendation()
        self.client.force_login(self.procurement_officer)

        response = self.client.get(reverse("procurement"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.medicine.medicine_name)
        self.assertContains(response, str(recommendation.recommended_quantity))

    def test_procurement_officer_can_create_purchase_order(self):
        recommendation = self.create_recommendation()
        self.client.force_login(self.procurement_officer)

        response = self.client.post(
            reverse("procurement"),
            {
                "medicine_id": self.medicine.pk,
                "quantity": 100,
                "supplier_name": self.supplier.supplier_name,
                "recommendation_id": recommendation.pk,
            },
        )

        self.assertEqual(response.status_code, 302)

        purchase_order = PurchaseOrder.objects.get(
            recommendation=recommendation
        )

        self.assertEqual(purchase_order.medicine, self.medicine)
        self.assertEqual(purchase_order.supplier, self.supplier)
        self.assertEqual(purchase_order.quantity_ordered, 100)
        self.assertEqual(
            purchase_order.status,
            PurchaseOrder.Status.PENDING_ADMIN_REVIEW,
        )

    def test_hospital_admin_can_approve_purchase_order(self):
        recommendation = self.create_recommendation()

        purchase_order = PurchaseOrder.objects.create(
            medicine=self.medicine,
            supplier=self.supplier,
            recommendation=recommendation,
            quantity_ordered=100,
            raised_by=self.procurement_officer,
            status=PurchaseOrder.Status.PENDING_ADMIN_REVIEW,
        )

        self.client.force_login(self.hospital_admin)

        response = self.client.post(
            reverse(
                "admin_process_po",
                kwargs={
                    "po_id": purchase_order.pk,
                    "action": "approve",
                },
            )
        )

        self.assertEqual(response.status_code, 302)

        purchase_order.refresh_from_db()
        recommendation.refresh_from_db()

        self.assertEqual(
            purchase_order.status,
            PurchaseOrder.Status.APPROVED,
        )
        self.assertEqual(
            recommendation.status,
            ProcurementRecommendation.Status.ACTIONED,
        )
        self.assertTrue(recommendation.is_actioned)
        self.assertEqual(recommendation.reviewed_by, self.hospital_admin)

    def test_hospital_admin_can_reject_purchase_order(self):
        recommendation = self.create_recommendation()

        purchase_order = PurchaseOrder.objects.create(
            medicine=self.medicine,
            supplier=self.supplier,
            recommendation=recommendation,
            quantity_ordered=100,
            raised_by=self.procurement_officer,
            status=PurchaseOrder.Status.PENDING_ADMIN_REVIEW,
        )

        self.client.force_login(self.hospital_admin)

        response = self.client.post(
            reverse(
                "admin_process_po",
                kwargs={
                    "po_id": purchase_order.pk,
                    "action": "reject",
                },
            )
        )

        self.assertEqual(response.status_code, 302)

        purchase_order.refresh_from_db()
        recommendation.refresh_from_db()

        self.assertEqual(
            purchase_order.status,
            PurchaseOrder.Status.REJECTED,
        )
        self.assertEqual(
            recommendation.status,
            ProcurementRecommendation.Status.REJECTED,
        )
        self.assertFalse(recommendation.is_actioned)

    def test_non_procurement_user_cannot_access_procurement_dashboard(self):
        self.client.force_login(self.store_manager)

        response = self.client.get(reverse("procurement"))

        self.assertIn(response.status_code, (302, 403))


class ReceivingTests(TestCase):

    def setUp(self):
        user = get_user_model()

        self.store_role = Role.objects.create(name="Store Manager")
        self.procurement_role = Role.objects.create(name="Procurement Officer")

        self.store_manager = user.objects.create_user(
            username="receiving_store_manager",
            password="TestPassword123!",
            role=self.store_role,
        )

        self.procurement_officer = user.objects.create_user(
            username="receiving_procurement_officer",
            password="TestPassword123!",
            role=self.procurement_role,
        )

        self.medicine = Medicine.objects.create(
            medicine_name="Receiving Test Paracetamol",
            generic_name="Paracetamol",
            category="Analgesic",
            dosage_form="Tablet",
            reorder_level=30,
            safety_stock_days=30,
            is_active=True,
        )

        self.supplier = Supplier.objects.create(
            supplier_name="Receiving Test Supplier",
        )

        self.purchase_order = PurchaseOrder.objects.create(
            medicine=self.medicine,
            supplier=self.supplier,
            quantity_ordered=100,
            raised_by=self.procurement_officer,
            status=PurchaseOrder.Status.PLACED_WITH_SUPPLIER,
        )

    def create_receipt(self):
        return GoodsReceipt.objects.create(
            purchase_order=self.purchase_order,
            received_by=self.store_manager,
            delivery_date=timezone.localdate(),
            delivery_reference="DELIVERY-TEST-001",
        )

    def create_receipt_item(self, receipt, batch_number="RECEIVED-BATCH-001"):
        return GoodsReceiptItem.objects.create(
            goods_receipt=receipt,
            batch_number=batch_number,
            quantity_received=25,
            expiry_date=timezone.localdate() + timedelta(days=180),
            storage_location="Test Store",
        )

    def test_store_manager_can_create_goods_receipt(self):
        self.client.force_login(self.store_manager)

        response = self.client.post(
            reverse("goods_receipt_create"),
            {
                "purchase_order_id": self.purchase_order.pk,
                "delivery_date": timezone.localdate().isoformat(),
                "delivery_reference": "DELIVERY-TEST-001",
                "notes": "Test delivery.",
            },
        )

        self.assertEqual(response.status_code, 302)

        receipt = GoodsReceipt.objects.get(
            purchase_order=self.purchase_order
        )

        self.assertEqual(receipt.received_by, self.store_manager)
        self.assertTrue(
            AuditLog.objects.filter(
                action="Goods receipt created"
            ).exists()
        )

    def test_goods_receipt_rejects_unplaced_purchase_order(self):
        self.purchase_order.status = PurchaseOrder.Status.APPROVED
        self.purchase_order.save()

        self.client.force_login(self.store_manager)

        response = self.client.post(
            reverse("goods_receipt_create"),
            {
                "purchase_order_id": self.purchase_order.pk,
                "delivery_date": timezone.localdate().isoformat(),
                "delivery_reference": "INVALID-DELIVERY",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            GoodsReceipt.objects.filter(
                purchase_order=self.purchase_order
            ).exists()
        )

    def test_store_manager_can_record_delivered_batch_for_inspection(self):
        receipt = self.create_receipt()
        self.client.force_login(self.store_manager)

        response = self.client.post(
            reverse(
                "goods_receipt_add_item",
                kwargs={"receipt_id": receipt.pk},
            ),
            {
                "batch_number": "NEW-BATCH-001",
                "quantity_received": 25,
                "expiry_date": (
                    timezone.localdate() + timedelta(days=180)
                ).isoformat(),
                "storage_location": "Main Store",
            },
        )

        self.assertEqual(response.status_code, 302)

        item = GoodsReceiptItem.objects.get(
            goods_receipt=receipt,
            batch_number="NEW-BATCH-001",
        )

        self.assertEqual(
            item.inspection_status,
            GoodsReceiptItem.InspectionStatus.PENDING,
        )

        self.assertFalse(
            MedicineBatch.objects.filter(
                medicine=self.medicine,
                batch_number="NEW-BATCH-001",
            ).exists()
        )

    def test_accepting_inspection_creates_usable_medicine_batch(self):
        receipt = self.create_receipt()
        item = self.create_receipt_item(receipt)

        self.client.force_login(self.store_manager)

        response = self.client.post(
            reverse(
                "goods_receipt_inspect_item",
                kwargs={"item_id": item.pk},
            ),
            {
                "decision": GoodsReceiptItem.InspectionStatus.ACCEPTED,
                "inspection_notes": "Batch passed inspection.",
            },
        )

        self.assertEqual(response.status_code, 302)

        item.refresh_from_db()

        self.assertEqual(
            item.inspection_status,
            GoodsReceiptItem.InspectionStatus.ACCEPTED,
        )

        self.assertIsNotNone(item.medicine_batch)

        batch = item.medicine_batch

        self.assertEqual(batch.medicine, self.medicine)
        self.assertEqual(batch.quantity_available, 25)
        self.assertEqual(batch.status, "Active")

    def test_rejected_batch_does_not_enter_usable_inventory(self):
        receipt = self.create_receipt()
        item = self.create_receipt_item(
            receipt,
            batch_number="REJECTED-BATCH-001",
        )

        self.client.force_login(self.store_manager)

        response = self.client.post(
            reverse(
                "goods_receipt_inspect_item",
                kwargs={"item_id": item.pk},
            ),
            {
                "decision": GoodsReceiptItem.InspectionStatus.REJECTED,
                "inspection_notes": "Batch failed inspection.",
            },
        )

        self.assertEqual(response.status_code, 302)

        item.refresh_from_db()

        self.assertEqual(
            item.inspection_status,
            GoodsReceiptItem.InspectionStatus.REJECTED,
        )
        self.assertIsNone(item.medicine_batch)

        self.assertFalse(
            MedicineBatch.objects.filter(
                medicine=self.medicine,
                batch_number="REJECTED-BATCH-001",
            ).exists()
        )

    def test_quarantined_batch_does_not_enter_usable_inventory(self):
        receipt = self.create_receipt()
        item = self.create_receipt_item(
            receipt,
            batch_number="QUARANTINED-BATCH-001",
        )

        self.client.force_login(self.store_manager)

        response = self.client.post(
            reverse(
                "goods_receipt_inspect_item",
                kwargs={"item_id": item.pk},
            ),
            {
                "decision": GoodsReceiptItem.InspectionStatus.QUARANTINED,
                "inspection_notes": "Batch requires further investigation.",
            },
        )

        self.assertEqual(response.status_code, 302)

        item.refresh_from_db()

        self.assertEqual(
            item.inspection_status,
            GoodsReceiptItem.InspectionStatus.QUARANTINED,
        )
        self.assertIsNone(item.medicine_batch)

    def test_receipt_cannot_exceed_purchase_order_quantity(self):
        receipt = self.create_receipt()

        self.client.force_login(self.store_manager)

        response = self.client.post(
            reverse(
                "goods_receipt_add_item",
                kwargs={"receipt_id": receipt.pk},
            ),
            {
                "batch_number": "OVERSUPPLY-BATCH",
                "quantity_received": 101,
                "expiry_date": (
                    timezone.localdate() + timedelta(days=180)
                ).isoformat(),
                "storage_location": "Main Store",
            },
        )

        self.assertEqual(response.status_code, 302)

        self.assertFalse(
            GoodsReceiptItem.objects.filter(
                goods_receipt=receipt,
                batch_number="OVERSUPPLY-BATCH",
            ).exists()
        )

    def test_inspection_decision_cannot_be_overwritten(self):
        receipt = self.create_receipt()
        item = self.create_receipt_item(
            receipt,
            batch_number="INSPECTION-ONCE-001",
        )

        self.client.force_login(self.store_manager)

        self.client.post(
            reverse(
                "goods_receipt_inspect_item",
                kwargs={"item_id": item.pk},
            ),
            {
                "decision": GoodsReceiptItem.InspectionStatus.REJECTED,
                "inspection_notes": "Rejected.",
            },
        )

        response = self.client.post(
            reverse(
                "goods_receipt_inspect_item",
                kwargs={"item_id": item.pk},
            ),
            {
                "decision": GoodsReceiptItem.InspectionStatus.ACCEPTED,
                "inspection_notes": "Attempted overwrite.",
            },
        )

        self.assertEqual(response.status_code, 302)

        item.refresh_from_db()

        self.assertEqual(
            item.inspection_status,
            GoodsReceiptItem.InspectionStatus.REJECTED,
        )
        self.assertIsNone(item.medicine_batch)


class IntegrationTests(TestCase):

    def setUp(self):
        user = get_user_model()

        self.store_role = Role.objects.create(name="Store Manager")
        self.procurement_role = Role.objects.create(name="Procurement Officer")
        self.admin_role = Role.objects.create(name="Hospital Admin")

        self.store_manager = user.objects.create_user(
            username="integration_store_manager",
            password="TestPassword123!",
            role=self.store_role,
        )

        self.procurement_officer = user.objects.create_user(
            username="integration_procurement_officer",
            password="TestPassword123!",
            role=self.procurement_role,
        )

        self.hospital_admin = user.objects.create_user(
            username="integration_hospital_admin",
            password="TestPassword123!",
            role=self.admin_role,
        )

        self.medicine = Medicine.objects.create(
            medicine_name="Integration Test Paracetamol",
            generic_name="Paracetamol",
            category="Analgesic",
            dosage_form="Tablet",
            reorder_level=30,
            safety_stock_days=30,
            is_active=True,
        )

        self.supplier = Supplier.objects.create(
            supplier_name="Integration Test Supplier",
        )

    def test_recommendation_to_accepted_inventory_workflow(self):
        # 1. Store Manager raises a procurement recommendation.
        recommendation = ProcurementRecommendation.objects.create(
            medicine=self.medicine,
            recommended_quantity=100,
            urgency_level="HIGH",
            reasoning="Insufficient usable inventory.",
            status=ProcurementRecommendation.Status.PENDING,
            raised_by=self.store_manager,
        )

        # 2. Procurement Officer creates a purchase order.
        self.client.force_login(self.procurement_officer)

        response = self.client.post(
            reverse("procurement"),
            {
                "medicine_id": self.medicine.pk,
                "quantity": 100,
                "supplier_name": self.supplier.supplier_name,
                "recommendation_id": recommendation.pk,
            },
        )

        self.assertEqual(response.status_code, 302)

        purchase_order = PurchaseOrder.objects.get(
            recommendation=recommendation
        )

        self.assertEqual(
            purchase_order.status,
            PurchaseOrder.Status.PENDING_ADMIN_REVIEW,
        )

        # 3. Hospital Admin approves the purchase order.
        self.client.force_login(self.hospital_admin)

        response = self.client.post(
            reverse(
                "admin_process_po",
                kwargs={
                    "po_id": purchase_order.pk,
                    "action": "approve",
                },
            )
        )

        self.assertEqual(response.status_code, 302)

        purchase_order.refresh_from_db()
        recommendation.refresh_from_db()

        self.assertEqual(
            purchase_order.status,
            PurchaseOrder.Status.APPROVED,
        )
        self.assertEqual(
            recommendation.status,
            ProcurementRecommendation.Status.ACTIONED,
        )

        # 4. Procurement Officer places the approved order.
        self.client.force_login(self.procurement_officer)

        response = self.client.post(
            reverse(
                "place_supplier_order",
                kwargs={"po_id": purchase_order.pk},
            )
        )

        self.assertEqual(response.status_code, 302)

        purchase_order.refresh_from_db()

        self.assertEqual(
            purchase_order.status,
            PurchaseOrder.Status.PLACED_WITH_SUPPLIER,
        )

        # 5. Store Manager records the delivery.
        self.client.force_login(self.store_manager)

        response = self.client.post(
            reverse("goods_receipt_create"),
            {
                "purchase_order_id": purchase_order.pk,
                "delivery_date": timezone.localdate().isoformat(),
                "delivery_reference": "INTEGRATION-DELIVERY-001",
                "notes": "Integration workflow delivery.",
            },
        )

        self.assertEqual(response.status_code, 302)

        receipt = GoodsReceipt.objects.get(
            purchase_order=purchase_order
        )

        # 6. Store Manager records a delivered batch.
        response = self.client.post(
            reverse(
                "goods_receipt_add_item",
                kwargs={"receipt_id": receipt.pk},
            ),
            {
                "batch_number": "INTEGRATION-BATCH-001",
                "quantity_received": 100,
                "expiry_date": (
                    timezone.localdate() + timedelta(days=180)
                ).isoformat(),
                "storage_location": "Main Store",
            },
        )

        self.assertEqual(response.status_code, 302)

        item = GoodsReceiptItem.objects.get(
            goods_receipt=receipt,
            batch_number="INTEGRATION-BATCH-001",
        )

        # 7. Batch remains unavailable until inspection.
        self.assertEqual(
            item.inspection_status,
            GoodsReceiptItem.InspectionStatus.PENDING,
        )

        self.assertFalse(
            MedicineBatch.objects.filter(
                medicine=self.medicine,
                batch_number="INTEGRATION-BATCH-001",
            ).exists()
        )

        # 8. Inspection accepts the batch into usable inventory.
        response = self.client.post(
            reverse(
                "goods_receipt_inspect_item",
                kwargs={"item_id": item.pk},
            ),
            {
                "decision": GoodsReceiptItem.InspectionStatus.ACCEPTED,
                "inspection_notes": "Integration test acceptance.",
            },
        )

        self.assertEqual(response.status_code, 302)

        item.refresh_from_db()

        self.assertEqual(
            item.inspection_status,
            GoodsReceiptItem.InspectionStatus.ACCEPTED,
        )

        self.assertIsNotNone(item.medicine_batch)

        self.assertEqual(
            item.medicine_batch.quantity_available,
            100,
        )

        self.assertEqual(
            MedicineBatch.objects.filter(
                medicine=self.medicine,
                quantity_available__gt=0,
                expiry_date__gte=timezone.localdate(),
                status="Active",
            ).count(),
            1,
        )


class SharedAlertsTests(TestCase):

    def setUp(self):
        self.today = timezone.localdate()
        self.role = Role.objects.create(name="Store Manager")
        self.user = get_user_model().objects.create_user(username="alerts_manager", password="TestPassword123!",role=self.role,)
        self.client.login( username="alerts_manager",password="TestPassword123!",)
        self.medicine = Medicine.objects.create(
            medicine_name="Alerts Test Paracetamol",
            generic_name="Paracetamol",
            category="Analgesic",
            dosage_form="Tablet",
            reorder_level=30,
            safety_stock_days=30,
            is_active=True,
        )

    def create_batch(self, batch_number, quantity, expiry_days):
        return MedicineBatch.objects.create(
            medicine=self.medicine,
            batch_number=batch_number,
            quantity_received=max(quantity, 1),
            quantity_available=quantity,
            received_date=self.today,
            expiry_date=self.today + timedelta(days=expiry_days),
            storage_location="Test Store",
            status="Active",
        )

    def test_persistent_expiry_alert_uses_generated_timestamp(self):
        batch = self.create_batch("PERSIST-001", 20, -5)
        expiry_alert = ExpiryAlert.objects.create(
            medicine=self.medicine,batch=batch,alert_type="EXPIRED",days_to_expiry=-5,severity="Critical",)
        response = self.client.get(reverse("alerts"))
        self.assertEqual(response.status_code, 200)

        matching_alerts = [
            alert for alert in response.context["alerts"]
            if alert["source_type"] == "expiry"
            and alert["source_id"] == expiry_alert.pk
        ]
        self.assertEqual(len(matching_alerts), 1)
        self.assertEqual(matching_alerts[0]["created_at"],expiry_alert.generated_at,)

    def test_resolved_persistent_expiry_alert_remains_resolved(self):
        batch = self.create_batch("PERSIST-002", 20, 10)
        expiry_alert = ExpiryAlert.objects.create(
            medicine=self.medicine,batch=batch, alert_type="NEAR", days_to_expiry=10,severity="High",is_resolved=True,)
        response = self.client.get(reverse("alerts"))
        self.assertEqual(response.status_code, 200)
        matching_alerts = [
            alert for alert in response.context["alerts"]
            if alert["source_type"] == "expiry"
            and alert["source_id"] == expiry_alert.pk
        ]

        self.assertEqual(len(matching_alerts), 1)
        self.assertEqual(matching_alerts[0]["status"], "Resolved")

    def test_generated_near_expiry_warning_is_not_saved_as_persistent_alert(self):
        self.create_batch("GENERATED-001", 20, 15)

        first_response = self.client.get(reverse("alerts"))
        second_response = self.client.get(reverse("alerts"))

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(ExpiryAlert.objects.count(), 0)

        for response in (first_response, second_response):
            matching_alerts = [
                alert for alert in response.context["alerts"]
                if alert["source_type"] == "batch"
                and alert["alert_type"] == "NEAR"
            ]
            self.assertEqual(len(matching_alerts), 1)

    def test_persistent_and_generated_warning_for_same_batch_are_deduplicated(self):
        batch = self.create_batch("DUPLICATE-001", 20, 15)
        ExpiryAlert.objects.create(medicine=self.medicine,batch=batch,alert_type="NEAR", days_to_expiry=15,severity="Medium",)
        response = self.client.get(reverse("alerts"))
        self.assertEqual(response.status_code, 200)

        matching_alerts = [
            alert for alert in response.context["alerts"]
            if alert["batch"]
            and alert["batch"]["batch_number"] == "DUPLICATE-001"
            and alert["alert_type"] == "NEAR"
        ]
        self.assertEqual(len(matching_alerts), 1)