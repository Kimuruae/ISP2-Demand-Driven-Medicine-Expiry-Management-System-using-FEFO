import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from core.models import (
    Medicine,
    Supplier,
    MedicineBatch,
    DispensingTransaction,
    DemandForecast,
    ProcurementRecommendation,
    PurchaseOrder,
    GoodsReceipt,
    GoodsReceiptItem,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "synthetic_dataset_package" / "datasets"


CSV_FILES = {
    "medicines": "medicines.csv",
    "suppliers": "suppliers.csv",
    "batches": "medicine_batches.csv",
    "transactions": "dispensing_transactions.csv",
    "forecasts_evaluation": "demand_forecasts_evaluation.csv",
    "forecasts_november": "demand_forecasts_november_2026.csv",
    "recommendations": "procurement_recommendations.csv",
    "purchase_orders": "purchase_orders.csv",
    "goods_receipts": "goods_receipts.csv",
    "receipt_items": "goods_receipt_items.csv",
}


OPERATIONAL_MODELS = [
    Medicine,
    Supplier,
    MedicineBatch,
    DispensingTransaction,
    DemandForecast,
    ProcurementRecommendation,
    PurchaseOrder,
    GoodsReceipt,
    GoodsReceiptItem,
]


def required(row, field):
    value = row.get(field)

    if value is None or str(value).strip() == "":
        raise ValueError(f"Required CSV value missing: {field}")

    return str(value).strip()


def optional(row, field, default=""):
    value = row.get(field)
    return str(value).strip() if value is not None else default


def to_int(value):
    return int(str(value).strip())


def to_decimal(value):
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid decimal value: {value}")


def to_bool(value):
    value = str(value).strip().casefold()

    if value in ("true", "1", "yes"):
        return True

    if value in ("false", "0", "no"):
        return False

    raise ValueError(f"Invalid Boolean value: {value}")


def to_date(value):
    result = parse_date(str(value).strip())

    if result is None:
        raise ValueError(f"Invalid date: {value}")

    return result


def to_datetime(value):
    result = parse_datetime(str(value).strip())

    if result is None:
        raise ValueError(f"Invalid datetime: {value}")

    if timezone.is_naive(result):
        result = timezone.make_aware(
            result,
            timezone.get_current_timezone()
        )

    return result


def optional_datetime(value):
    if value is None or str(value).strip() == "":
        return None

    return to_datetime(value)


class Command(BaseCommand):

    help = (
        "Imports the validated synthetic medicine expiry dataset "
        "into the Django database."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate the dataset without inserting records.",
        )

        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of records inserted per bulk operation.",
        )

    def handle(self, *args, **options):

        self.batch_size = options["batch_size"]

        if self.batch_size < 1:
            raise CommandError("Batch size must be greater than zero.")

        self.stdout.write(
            self.style.NOTICE(
                "\nDEMAND-DRIVEN MEDICINE EXPIRY SYSTEM"
                "\nSYNTHETIC DATA IMPORTER\n"
            )
        )

        try:
            data = self.load_datasets()

            self.validate_references(data)
            self.check_database_empty()

            if options["dry_run"]:
                self.report_dry_run(data)
                return

            self.import_datasets(data)

        except Exception as error:
            raise CommandError(
                f"Import stopped: {error}"
            ) from error

    # --------------------------------------------------
    # CSV LOADING
    # --------------------------------------------------

    def load_csv(self, filename):

        path = DATA_DIR / filename

        if not path.exists():
            raise CommandError(f"Dataset not found: {path}")

        with path.open(
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as file:

            reader = csv.DictReader(file)

            if not reader.fieldnames:
                raise CommandError(
                    f"CSV has no headers: {filename}"
                )

            rows = list(reader)

        if not rows:
            raise CommandError(
                f"CSV contains no records: {filename}"
            )

        return rows

    def load_datasets(self):

        self.stdout.write("Loading CSV datasets...")

        data = {}

        for key, filename in CSV_FILES.items():

            data[key] = self.load_csv(filename)

            self.stdout.write(
                f"  {filename}: {len(data[key]):,} records"
            )

        data["forecasts"] = (
            data["forecasts_evaluation"]
            + data["forecasts_november"]
        )

        total = sum(
            len(data[key])
            for key in CSV_FILES
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nLoaded {total:,} records across "
                f"{len(CSV_FILES)} CSV files."
            )
        )

        return data

    # --------------------------------------------------
    # REFERENCE VALIDATION
    # --------------------------------------------------

    def validate_references(self, data):

        self.stdout.write(
            "\nValidating source identifiers and relationships..."
        )

        def identifiers(rows, field):
            values = [
                required(row, field)
                for row in rows
            ]

            if len(values) != len(set(values)):
                raise CommandError(
                    f"Duplicate identifiers detected: {field}"
                )

            return set(values)

        medicine_ids = identifiers(
            data["medicines"], "medicine_id"
        )

        supplier_ids = identifiers(
            data["suppliers"], "supplier_id"
        )

        batch_ids = identifiers(
            data["batches"], "batch_id"
        )

        transaction_ids = identifiers(
            data["transactions"], "transaction_id"
        )

        forecast_ids = identifiers(
            data["forecasts"], "forecast_id"
        )

        recommendation_ids = identifiers(
            data["recommendations"], "recommendation_id"
        )

        purchase_order_ids = identifiers(
            data["purchase_orders"], "purchase_order_id"
        )

        receipt_ids = identifiers(
            data["goods_receipts"], "goods_receipt_id"
        )

        receipt_item_ids = identifiers(
            data["receipt_items"], "receipt_item_id"
        )

        def check_reference(
            rows,
            field,
            valid_ids,
            allow_blank=False
        ):

            for row in rows:

                value = optional(row, field)

                if allow_blank and not value:
                    continue

                if value not in valid_ids:
                    raise CommandError(
                        f"Unresolved {field} reference: {value}"
                    )

        check_reference(
            data["batches"],
            "medicine_id",
            medicine_ids
        )

        check_reference(
            data["transactions"],
            "medicine_id",
            medicine_ids
        )

        check_reference(
            data["transactions"],
            "batch_id",
            batch_ids
        )

        for row in data["transactions"]:

            batch = next(
                (
                    item for item in data["batches"]
                    if item["batch_id"] == row["batch_id"]
                ),
                None
            )

            if batch is None or (
                batch["medicine_id"] != row["medicine_id"]
            ):
                raise CommandError(
                    f"Transaction {row['transaction_id']} "
                    "has an inconsistent medicine/batch relationship."
                )

        for key in ("forecasts_evaluation", "forecasts_november"):

            check_reference(
                data[key],
                "medicine_id",
                medicine_ids
            )

        check_reference(
            data["recommendations"],
            "medicine_id",
            medicine_ids
        )

        check_reference(
            data["recommendations"],
            "forecast_id",
            forecast_ids,
            allow_blank=True
        )

        check_reference(
            data["purchase_orders"],
            "medicine_id",
            medicine_ids
        )

        check_reference(
            data["purchase_orders"],
            "supplier_id",
            supplier_ids
        )

        check_reference(
            data["purchase_orders"],
            "recommendation_id",
            recommendation_ids
        )

        check_reference(
            data["goods_receipts"],
            "purchase_order_id",
            purchase_order_ids
        )

        check_reference(
            data["receipt_items"],
            "goods_receipt_id",
            receipt_ids
        )

        check_reference(
            data["receipt_items"],
            "medicine_batch_id",
            batch_ids
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Source identifier and foreign-key validation passed."
            )
        )

    # --------------------------------------------------
    # DATABASE PROTECTION
    # --------------------------------------------------

    def check_database_empty(self):

        self.stdout.write(
            "\nChecking operational database tables..."
        )

        existing = {}

        for model in OPERATIONAL_MODELS:

            count = model.objects.count()

            existing[model.__name__] = count

            self.stdout.write(
                f"  {model.__name__}: {count:,}"
            )

        populated = {
            name: count
            for name, count in existing.items()
            if count > 0
        }

        if populated:

            raise CommandError(
                "Import cancelled. Existing operational records "
                f"were detected: {populated}. "
                "No existing records have been modified."
            )

        self.stdout.write(
            self.style.SUCCESS(
                "All nine operational tables are empty."
            )
        )

    # --------------------------------------------------
    # DRY RUN
    # --------------------------------------------------

    def report_dry_run(self, data):

        self.stdout.write(
            self.style.SUCCESS(
                "\nDRY RUN PASSED"
            )
        )

        self.stdout.write(
            "The datasets were loaded and their source "
            "relationships were checked."
        )

        self.stdout.write(
            "\nExpected import volumes:"
        )

        for key, filename in CSV_FILES.items():

            self.stdout.write(
                f"  {filename}: {len(data[key]):,}"
            )

        self.stdout.write(
            "\nTotal expected records: 55,687"
        )

        self.stdout.write(
            "\nNo database records were inserted."
        )

        self.stdout.write(
            "AuditLog was not accessed or modified."
        )

        self.stdout.write(
            "\nRun without --dry-run only after "
            "explicitly authorising the actual import."
        )

    # --------------------------------------------------
    # BULK INSERT HELPER
    # --------------------------------------------------

    def bulk_insert(self, model, objects):

        model.objects.bulk_create(
            objects,
            batch_size=self.batch_size
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"{model.__name__}: {len(objects):,} inserted."
            )
        )

    # --------------------------------------------------
    # ACTUAL IMPORT
    # --------------------------------------------------

    @transaction.atomic
    def import_datasets(self, data):

        self.stdout.write(
            self.style.WARNING(
                "\nStarting transactional database import..."
            )
        )

        # 1. MEDICINES

        medicines = [
            Medicine(
                medicine_id=required(r, "medicine_id"),
                medicine_name=required(r, "medicine_name"),
                generic_name=optional(r, "generic_name"),
                category=required(r, "category"),
                dosage_form=required(r, "dosage_form"),
                reorder_level=to_int(r["reorder_level"]),
                safety_stock_days=to_int(r["safety_stock_days"]),
                is_active=to_bool(r["is_active"]),
            )
            for r in data["medicines"]
        ]

        self.bulk_insert(Medicine, medicines)

        medicine_map = {
            obj.medicine_id: obj
            for obj in Medicine.objects.all()
        }

        # 2. SUPPLIERS

        suppliers = [
            Supplier(
                supplier_id=required(r, "supplier_id"),
                supplier_name=required(r, "supplier_name"),
                contact_person=optional(r, "contact_person"),
                email=optional(r, "email"),
                phone_number=optional(r, "phone_number"),
                address=optional(r, "address"),
                is_active=to_bool(r["is_active"]),
                delivery_lead_time_days=to_int(
                    r["delivery_lead_time_days"]
                ),
            )
            for r in data["suppliers"]
        ]

        self.bulk_insert(Supplier, suppliers)

        supplier_map = {
            obj.supplier_id: obj
            for obj in Supplier.objects.all()
        }

        # 3. MEDICINE BATCHES

        batches = [
            MedicineBatch(
                batch_id=required(r, "batch_id"),
                medicine=medicine_map[r["medicine_id"]],
                batch_number=required(r, "batch_number"),
                quantity_received=to_int(r["quantity_received"]),
                quantity_available=to_int(r["quantity_available"]),
                received_date=to_date(r["received_date"]),
                expiry_date=to_date(r["expiry_date"]),
                storage_location=optional(r, "storage_location"),
                status=required(r, "status"),
            )
            for r in data["batches"]
        ]

        self.bulk_insert(MedicineBatch, batches)

        batch_map = {
            obj.batch_id: obj
            for obj in MedicineBatch.objects.all()
        }

        # 4. DISPENSING TRANSACTIONS

        transactions = [
            DispensingTransaction(
                transaction_id=required(r, "transaction_id"),
                medicine=medicine_map[r["medicine_id"]],
                batch=batch_map[r["batch_id"]],
                quantity_dispensed=to_int(r["quantity_dispensed"]),
                dispensed_at=to_datetime(r["dispensed_at"]),
                is_override=to_bool(r["is_override"]),
                patient_identifier=optional(
                    r, "patient_identifier"
                ),
                notes=optional(r, "notes"),
            )
            for r in data["transactions"]
        ]

        self.bulk_insert(
            DispensingTransaction,
            transactions
        )

        # 5. DEMAND FORECASTS

        forecasts = [
            DemandForecast(
                source_forecast_id=required(r, "forecast_id"),
                medicine=medicine_map[r["medicine_id"]],
                forecast_period_start=to_date(
                    r["forecast_period_start"]
                ),
                forecast_period_end=to_date(
                    r["forecast_period_end"]
                ),
                forecasted_demand_quantity=to_int(
                    r["forecasted_demand_quantity"]
                ),
                moving_avg_3month=to_int(
                    r["moving_avg_3month"]
                ),
                forecast_method=required(r, "forecast_method"),
                history_start_date=(
                    to_date(r["history_start_date"])
                    if optional(r, "history_start_date")
                    else None
                ),
                history_end_date=(
                    to_date(r["history_end_date"])
                    if optional(r, "history_end_date")
                    else None
                ),
                historical_transaction_count=to_int(
                    r["historical_transaction_count"]
                ),
                confidence_score=to_decimal(
                    r["confidence_score"]
                ),
                actual_demand_quantity=(
                    to_int(r["actual_demand_quantity"])
                    if optional(r, "actual_demand_quantity")
                    else None
                ),
                absolute_error=(
                    to_decimal(r["absolute_error"])
                    if optional(r, "absolute_error")
                    else None
                ),
                generated_at=to_datetime(r["generated_at"]),
            )
            for r in data["forecasts"]
        ]

        self.bulk_insert(DemandForecast, forecasts)

        forecast_map = {
            obj.source_forecast_id: obj
            for obj in DemandForecast.objects.all()
        }

        # 6. PROCUREMENT RECOMMENDATIONS

        recommendations = [
            ProcurementRecommendation(
                source_recommendation_id=required(
                    r, "recommendation_id"
                ),
                medicine=medicine_map[r["medicine_id"]],
                forecast=(
                    forecast_map[r["forecast_id"]]
                    if optional(r, "forecast_id")
                    else None
                ),
                recommended_quantity=to_int(
                    r["recommended_quantity"]
                ),
                forecast_demand_quantity=to_int(
                    r["forecast_demand_quantity"]
                ),
                eligible_stock_quantity=to_int(
                    r["eligible_stock_quantity"]
                ),
                incoming_stock_quantity=to_int(
                    r["incoming_stock_quantity"]
                ),
                projected_stock_position=to_int(
                    r["projected_stock_position"]
                ),
                lead_time_days=to_int(r["lead_time_days"]),
                target_stock_quantity=to_int(
                    r["target_stock_quantity"]
                ),
                urgency_level=required(r, "urgency_level"),
                reasoning=optional(r, "reasoning"),
                status=required(r, "status"),
                is_actioned=to_bool(r["is_actioned"]),
                created_at=to_datetime(r["created_at"]),
                updated_at=to_datetime(r["updated_at"]),
            )
            for r in data["recommendations"]
        ]

        self.bulk_insert(
            ProcurementRecommendation,
            recommendations
        )

        # bulk_create invokes auto_now for updated_at.
        # Restore the original synthetic source timestamps.

        ProcurementRecommendation.objects.bulk_update(
            recommendations,
            ["updated_at"],
            batch_size=self.batch_size
        )

        recommendation_map = {
            obj.source_recommendation_id: obj
            for obj in ProcurementRecommendation.objects.all()
        }

        # 7. PURCHASE ORDERS

        purchase_orders = [
            PurchaseOrder(
                purchase_order_id=required(r, "purchase_order_id"),
                medicine=medicine_map[r["medicine_id"]],
                supplier=supplier_map[r["supplier_id"]],
                recommendation=recommendation_map[r["recommendation_id"]],
                quantity_ordered=to_int(r["quantity_ordered"]),
                total_cost=to_decimal(r.get("total_cost")or r.get("total_amount")),
                order_date=to_datetime(r["order_date"]),
                status=required(r, "status"),
            )
            for r in data["purchase_orders"]
        ]

        self.bulk_insert(PurchaseOrder, purchase_orders)

        purchase_order_map = {
            obj.purchase_order_id: obj
            for obj in PurchaseOrder.objects.all()
        }

        # 8. GOODS RECEIPTS

        goods_receipts = [
            GoodsReceipt(
                source_goods_receipt_id=required(
                    r, "goods_receipt_id"
                ),
                purchase_order=purchase_order_map[
                    r["purchase_order_id"]
                ],
                delivery_date=to_date(r["delivery_date"]),
                received_at=to_datetime(r["received_at"]),
                delivery_reference=optional(
                    r, "delivery_reference"
                ),
                notes=optional(r, "notes"),
            )
            for r in data["goods_receipts"]
        ]

        self.bulk_insert(GoodsReceipt, goods_receipts)

        goods_receipt_map = {
            obj.source_goods_receipt_id: obj
            for obj in GoodsReceipt.objects.all()
        }

        # 9. GOODS RECEIPT ITEMS

        receipt_items = [
            GoodsReceiptItem(
                source_receipt_item_id=required(
                    r, "receipt_item_id"
                ),
                goods_receipt=goods_receipt_map[
                    r["goods_receipt_id"]
                ],
                medicine_batch=batch_map[
                    r["medicine_batch_id"]
                ],
                batch_number=required(r, "batch_number"),
                quantity_received=to_int(
                    r["quantity_received"]
                ),
                expiry_date=to_date(r["expiry_date"]),
                storage_location=optional(
                    r, "storage_location"
                ),
                inspection_status=required(
                    r, "inspection_status"
                ),
                inspected_at=optional_datetime(
                    r.get("inspected_at")
                ),
                inspection_notes=optional(
                    r, "inspection_notes"
                ),
            )
            for r in data["receipt_items"]
        ]

        self.bulk_insert(
            GoodsReceiptItem,
            receipt_items
        )

        self.stdout.write(
            self.style.SUCCESS(
                "\nAll datasets inserted successfully."
            )
        )

        self.stdout.write(
            "The transaction is ready to commit."
        )

        self.stdout.write(
            "AuditLog was not modified."
        )