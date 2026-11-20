import csv
import os
import django
import sys
from pathlib import Path
from collections import defaultdict
from django.core.exceptions import ValidationError

# --------------------------------------------------
# DJANGO SETUP
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.apps import apps

DATA = PROJECT_ROOT / "synthetic_dataset_package" / "datasets"


# --------------------------------------------------
# CSV COLUMN -> DJANGO MODEL FIELD
# --------------------------------------------------

MAPPINGS = {
    "medicines.csv": {
        "medicine_id": "Medicine.medicine_id",
        "medicine_name": "Medicine.medicine_name",
        "generic_name": "Medicine.generic_name",
        "category": "Medicine.category",
        "dosage_form": "Medicine.dosage_form",
        "reorder_level": "Medicine.reorder_level",
        "safety_stock_days": "Medicine.safety_stock_days",
        "is_active": "Medicine.is_active",
    },

    "suppliers.csv": {
        "supplier_id": "Supplier.supplier_id",
        "supplier_name": "Supplier.supplier_name",
        "contact_person": "Supplier.contact_person",
        "email": "Supplier.email",
        "phone_number": "Supplier.phone_number",
        "address": "Supplier.address",
        "is_active": "Supplier.is_active",
        "delivery_lead_time_days": "Supplier.delivery_lead_time_days",
    },

    "medicine_batches.csv": {
        "batch_id": "MedicineBatch.batch_id",
        "medicine_id": "MedicineBatch.medicine",
        "batch_number": "MedicineBatch.batch_number",
        "quantity_received": "MedicineBatch.quantity_received",
        "quantity_available": "MedicineBatch.quantity_available",
        "received_date": "MedicineBatch.received_date",
        "expiry_date": "MedicineBatch.expiry_date",
        "storage_location": "MedicineBatch.storage_location",
        "status": "MedicineBatch.status",
    },

    "dispensing_transactions.csv": {
        "transaction_id": "DispensingTransaction.transaction_id",
        "medicine_id": "DispensingTransaction.medicine",
        "batch_id": "DispensingTransaction.batch",
        "quantity_dispensed": "DispensingTransaction.quantity_dispensed",
        "dispensed_at": "DispensingTransaction.dispensed_at",
        "is_override": "DispensingTransaction.is_override",
        "patient_identifier": "DispensingTransaction.patient_identifier",
        "notes": "DispensingTransaction.notes",
    },

    "demand_forecasts_evaluation.csv": {
        "forecast_id": "DemandForecast.source_forecast_id",
        "medicine_id": "DemandForecast.medicine",
        "forecast_period_start": "DemandForecast.forecast_period_start",
        "forecast_period_end": "DemandForecast.forecast_period_end",
        "forecasted_demand_quantity": "DemandForecast.forecasted_demand_quantity",
        "moving_avg_3month": "DemandForecast.moving_avg_3month",
        "forecast_method": "DemandForecast.forecast_method",
        "history_start_date": "DemandForecast.history_start_date",
        "history_end_date": "DemandForecast.history_end_date",
        "historical_transaction_count": "DemandForecast.historical_transaction_count",
        "confidence_score": "DemandForecast.confidence_score",
        "actual_demand_quantity": "DemandForecast.actual_demand_quantity",
        "absolute_error": "DemandForecast.absolute_error",
        "generated_at": "DemandForecast.generated_at",
    },

    "demand_forecasts_november_2026.csv": {
        "forecast_id": "DemandForecast.source_forecast_id",
        "medicine_id": "DemandForecast.medicine",
        "forecast_period_start": "DemandForecast.forecast_period_start",
        "forecast_period_end": "DemandForecast.forecast_period_end",
        "forecasted_demand_quantity": "DemandForecast.forecasted_demand_quantity",
        "moving_avg_3month": "DemandForecast.moving_avg_3month",
        "forecast_method": "DemandForecast.forecast_method",
        "history_start_date": "DemandForecast.history_start_date",
        "history_end_date": "DemandForecast.history_end_date",
        "historical_transaction_count": "DemandForecast.historical_transaction_count",
        "confidence_score": "DemandForecast.confidence_score",
        "actual_demand_quantity": "DemandForecast.actual_demand_quantity",
        "absolute_error": "DemandForecast.absolute_error",
        "generated_at": "DemandForecast.generated_at",
    },

    "procurement_recommendations.csv": {
        "recommendation_id": "ProcurementRecommendation.source_recommendation_id",
        "medicine_id": "ProcurementRecommendation.medicine",
        "forecast_id": "ProcurementRecommendation.forecast",
        "recommended_quantity": "ProcurementRecommendation.recommended_quantity",
        "forecast_demand_quantity": "ProcurementRecommendation.forecast_demand_quantity",
        "eligible_stock_quantity": "ProcurementRecommendation.eligible_stock_quantity",
        "incoming_stock_quantity": "ProcurementRecommendation.incoming_stock_quantity",
        "projected_stock_position": "ProcurementRecommendation.projected_stock_position",
        "lead_time_days": "ProcurementRecommendation.lead_time_days",
        "target_stock_quantity": "ProcurementRecommendation.target_stock_quantity",
        "urgency_level": "ProcurementRecommendation.urgency_level",
        "reasoning": "ProcurementRecommendation.reasoning",
        "status": "ProcurementRecommendation.status",
        "is_actioned": "ProcurementRecommendation.is_actioned",
        "created_at": "ProcurementRecommendation.created_at",
        "updated_at": "ProcurementRecommendation.updated_at",
    },

    "purchase_orders.csv": {
        "purchase_order_id": "PurchaseOrder.purchase_order_id",
        "medicine_id": "PurchaseOrder.medicine",
        "supplier_id": "PurchaseOrder.supplier",
        "recommendation_id": "PurchaseOrder.recommendation",
        "quantity_ordered": "PurchaseOrder.quantity_ordered",
        "total_cost": "PurchaseOrder.total_cost",
        "order_date": "PurchaseOrder.order_date",
        "status": "PurchaseOrder.status",
    },

    "goods_receipts.csv": {
        "goods_receipt_id": "GoodsReceipt.source_goods_receipt_id",
        "purchase_order_id": "GoodsReceipt.purchase_order",
        "delivery_date": "GoodsReceipt.delivery_date",
        "received_at": "GoodsReceipt.received_at",
        "delivery_reference": "GoodsReceipt.delivery_reference",
        "notes": "GoodsReceipt.notes",
    },

    "goods_receipt_items.csv": {
        "receipt_item_id": "GoodsReceiptItem.source_receipt_item_id",
        "goods_receipt_id": "GoodsReceiptItem.goods_receipt",
        "medicine_batch_id": "GoodsReceiptItem.medicine_batch",
        "batch_number": "GoodsReceiptItem.batch_number",
        "quantity_received": "GoodsReceiptItem.quantity_received",
        "expiry_date": "GoodsReceiptItem.expiry_date",
        "storage_location": "GoodsReceiptItem.storage_location",
        "inspection_status": "GoodsReceiptItem.inspection_status",
        "inspected_at": "GoodsReceiptItem.inspected_at",
        "inspection_notes": "GoodsReceiptItem.inspection_notes",
    },
}


# --------------------------------------------------
# CSV FOREIGN KEY -> TARGET BUSINESS IDENTIFIER
# --------------------------------------------------

FK_LOOKUPS = {
    ("medicine_batches.csv", "medicine_id"):
        ("Medicine", "medicine_id"),

    ("dispensing_transactions.csv", "medicine_id"):
        ("Medicine", "medicine_id"),

    ("dispensing_transactions.csv", "batch_id"):
        ("MedicineBatch", "batch_id"),

    ("demand_forecasts_evaluation.csv", "medicine_id"):
        ("Medicine", "medicine_id"),

    ("demand_forecasts_november_2026.csv", "medicine_id"):
        ("Medicine", "medicine_id"),

    ("procurement_recommendations.csv", "medicine_id"):
        ("Medicine", "medicine_id"),

    ("procurement_recommendations.csv", "forecast_id"):
        ("DemandForecast", "source_forecast_id"),

    ("purchase_orders.csv", "medicine_id"):
        ("Medicine", "medicine_id"),

    ("purchase_orders.csv", "supplier_id"):
        ("Supplier", "supplier_id"),

    ("purchase_orders.csv", "recommendation_id"):
        ("ProcurementRecommendation", "source_recommendation_id"),

    ("goods_receipts.csv", "purchase_order_id"):
        ("PurchaseOrder", "purchase_order_id"),

    ("goods_receipt_items.csv", "goods_receipt_id"):
        ("GoodsReceipt", "source_goods_receipt_id"),

    ("goods_receipt_items.csv", "medicine_batch_id"):
        ("MedicineBatch", "batch_id"),
}


# --------------------------------------------------
# AUDIT EXECUTION
# --------------------------------------------------

errors = defaultdict(list)
total_records = 0
total_conversions = 0

print("\n========== DJANGO MODEL-FIELD COMPATIBILITY ==========")

for filename, mapping in MAPPINGS.items():

    path = DATA / filename
    print(f"\n--- {filename} ---")

    if not path.exists():
        errors[filename].append("CSV file does not exist")
        print("FILE MISSING")
        continue

    model_names = {
        target.split(".")[0]
        for target in mapping.values()
    }

    if len(model_names) != 1:
        errors[filename].append(
            "Mapping references multiple Django models"
        )
        print("MODEL MAPPING ERROR")
        continue

    model_name = next(iter(model_names))

    try:
        model = apps.get_model("core", model_name)
    except LookupError:
        errors[filename].append(
            f"Django model not found: {model_name}"
        )
        print("MODEL NOT FOUND:", model_name)
        continue

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows = list(reader)

    total_records += len(rows)

    # Resolve mapped Django fields.
    resolved_fields = {}

    for csv_column, target in mapping.items():

        field_name = target.split(".", 1)[1]

        try:
            field = model._meta.get_field(field_name)
            resolved_fields[csv_column] = field

        except Exception:
            errors[filename].append(
                f"Mapped Django field does not exist: {target}"
            )

    # Check required model fields omitted from mapping.
    mapped_model_fields = {
        target.split(".", 1)[1]
        for target in mapping.values()
    }

    omitted_required = []

    for field in model._meta.fields:

        if (
            field.primary_key
            or field.auto_created
            or field.name in mapped_model_fields
            or field.many_to_many
            or field.null
            or field.blank
            or field.has_default()
            or getattr(field, "auto_now", False)
            or getattr(field, "auto_now_add", False)
        ):
            continue

        omitted_required.append(field.name)

    if omitted_required:
        errors[filename].append(
            f"Required model fields omitted from mapping: {omitted_required}"
        )

    # --------------------------------------------------
    # CORRECTED INDIVIDUAL VALUE VALIDATION
    # --------------------------------------------------

    conversion_errors = []

    for row_number, row in enumerate(rows, start=2):

        for csv_column, target in mapping.items():

            if csv_column not in row:
                continue

            field = resolved_fields.get(csv_column)

            if field is None:
                continue

            raw_value = row[csv_column]

            try:

                if raw_value is None:
                    raise ValidationError(
                        "Missing CSV column value"
                    )

                # Skip intentional blanks for nullable fields.
                if raw_value.strip() == "" and field.null:
                    continue

                # Recognise both ForeignKey and OneToOneField.
                if field.is_relation and (
                    field.many_to_one or field.one_to_one
                ):

                    lookup = FK_LOOKUPS.get(
                        (filename, csv_column)
                    )

                    if lookup is None:
                        raise ValidationError(
                            "Foreign-key business lookup not documented"
                        )

                    target_model_name, lookup_field_name = lookup

                    target_model = apps.get_model(
                        "core",
                        target_model_name
                    )

                    lookup_field = target_model._meta.get_field(
                        lookup_field_name
                    )

                    if raw_value.strip() == "":
                        raise ValidationError(
                            "Blank value for non-nullable foreign key"
                        )

                    lookup_field.clean(raw_value, None)

                else:
                    field.clean(raw_value, None)

                total_conversions += 1

            except (
                ValidationError,
                ValueError,
                TypeError
            ) as exc:

                conversion_errors.append({
                    "row": row_number,
                    "column": csv_column,
                    "django_field": target,
                    "value": raw_value,
                    "error": str(exc),
                })

    if conversion_errors:
        errors[filename].extend(
            conversion_errors[:10]
        )

    # File-level results.
    print("Django model:", model_name)
    print("CSV records:", len(rows))
    print("Mapped fields:", len(mapping))
    print("Mapped fields resolved:", len(resolved_fields))
    print("Required fields omitted:", omitted_required)
    print("Value conversion errors:", len(conversion_errors))

    if conversion_errors:
        print("First conversion errors:")

        for item in conversion_errors[:5]:
            print(item)

    print(
        "FILE RESULT:",
        "PASS" if filename not in errors else "REVIEW REQUIRED"
    )


# --------------------------------------------------
# FINAL REPORT
# --------------------------------------------------

print("\n========== FINAL RESULT ==========")

print("Files audited:", len(MAPPINGS))
print("Total records:", total_records)
print("Successful field conversions:", total_conversions)
print("Files with issues:", len(errors))

if errors:

    for filename, issues in errors.items():

        print(f"\n{filename}:")

        for issue in issues:
            print(" -", issue)

print(
    "\nRESULT:",
    "PASS" if not errors else "REVIEW REQUIRED"
)
