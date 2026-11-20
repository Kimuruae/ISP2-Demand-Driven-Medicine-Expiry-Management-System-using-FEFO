import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from core import models

MODEL_NAMES = [
    "Role",
    "user",
    "Medicine",
    "Supplier",
    "MedicineBatch",
    "DispensingTransaction",
    "DemandForecast",
    "ProcurementRecommendation",
    "PurchaseOrder",
    "GoodsReceipt",
    "GoodsReceiptItem",
]

output = []

def record(value=""):
    output.append(str(value))

for model_name in MODEL_NAMES:
    model = getattr(models, model_name, None)

    record("\n" + "=" * 90)
    record(f"MODEL: {model_name}")
    record("=" * 90)

    if model is None:
        record("MODEL NOT FOUND")
        continue

    record(f"Database table: {model._meta.db_table}")

    for field in model._meta.fields:
        details = [
            f"Field: {field.name}",
            f"Type: {field.get_internal_type()}",
            f"Null: {field.null}",
            f"Blank: {field.blank}",
            f"Unique: {field.unique}",
            f"Primary key: {field.primary_key}",
        ]

        if hasattr(field, "max_length"):
            details.append(f"Max length: {field.max_length}")

        if hasattr(field, "max_digits"):
            details.append(f"Max digits: {field.max_digits}")

        if hasattr(field, "decimal_places"):
            details.append(f"Decimal places: {field.decimal_places}")

        if field.has_default():
            details.append(f"Default: {field.default!r}")

        if getattr(field, "auto_now_add", False):
            details.append("Auto now add: True")

        if getattr(field, "auto_now", False):
            details.append("Auto now: True")

        if field.choices:
            details.append(f"Choices: {list(field.choices)}")

        if field.is_relation and field.related_model:
            details.append(
                f"Related model: {field.related_model.__name__}"
            )

            if hasattr(field.remote_field, "on_delete"):
                details.append(
                    f"On delete: {field.remote_field.on_delete.__name__}"
                )

        record(" | ".join(details))

    record(f"Unique together: {model._meta.unique_together}")

    for constraint in model._meta.constraints:
        record(f"Constraint: {constraint}")

    for index in model._meta.indexes:
        record(f"Index: {index}")

result = "\n".join(output)

print(result)

output_path = (
    PROJECT_ROOT
    / "synthetic_dataset_package"
    / "documentation"
    / "django_schema_audit.txt"
)

output_path.write_text(result, encoding="utf-8")

print(f"\nSchema audit saved to: {output_path}")