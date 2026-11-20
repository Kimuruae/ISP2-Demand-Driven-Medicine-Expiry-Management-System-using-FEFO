"""
Synthetic dataset generator for:
Web-Based Demand-Driven Medicine Expiry Management System
using the First Expiry First Out (FEFO) Approach.

This script:
- Generates ten related CSV datasets.
- Uses a fixed random seed for reproducibility.
- Simulates 24 months of historical demand and stock movements.
- Allocates dispensing transactions using date-aware FEFO.
- Simulates procurement, purchase orders and goods receipts.
- Generates six-month forecast evaluation data.
- Generates November 2026 forward forecasts.
- Produces a generation summary.

It does NOT connect to Django or import data into the database.
"""

from __future__ import annotations

import calendar
import json
import math
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker


# ============================================================
# 1. CONFIGURATION
# ============================================================

SEED = 20261109

random.seed(SEED)
np.random.seed(SEED)

fake = Faker()
Faker.seed(SEED)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = PROJECT_ROOT / "synthetic_dataset_package"
DATASET_DIR = PACKAGE_DIR / "datasets"
REPORT_DIR = PACKAGE_DIR / "reports"

DATASET_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

HISTORY_START = date(2024, 11, 1)
HISTORY_END = date(2026, 10, 31)

SNAPSHOT_DATE = date(2026, 11, 9)
FORWARD_FORECAST_START = date(2026, 11, 1)
FORWARD_FORECAST_END = date(2026, 11, 30)

TRAINING_MONTHS = 18
EVALUATION_MONTHS = 6

PERIOD_DAYS = 30
HISTORY_PERIODS = 3
MAX_PRESCRIPTION_DAYS = 14

MEDICINE_COUNT = 100
SUPPLIER_COUNT = 15

# Fixed historical evaluation origins.
EVALUATION_ORIGINS = [
    date(2026, month, 1)
    for month in range(5, 11)
]

# All generated IDs are external dataset identifiers.
# They are NOT Django primary keys.


# ============================================================
# 2. MEDICINE AND SUPPLIER MASTER DATA
# ============================================================

MEDICINE_CATALOGUE = [
    ("Paracetamol", "Analgesic"),
    ("Ibuprofen", "Analgesic"),
    ("Diclofenac", "Analgesic"),
    ("Amoxicillin", "Antibiotic"),
    ("Azithromycin", "Antibiotic"),
    ("Ciprofloxacin", "Antibiotic"),
    ("Metronidazole", "Antibiotic"),
    ("Doxycycline", "Antibiotic"),
    ("Metformin", "Antidiabetic"),
    ("Glibenclamide", "Antidiabetic"),
    ("Amlodipine", "Cardiovascular"),
    ("Losartan", "Cardiovascular"),
    ("Atenolol", "Cardiovascular"),
    ("Enalapril", "Cardiovascular"),
    ("Hydrochlorothiazide", "Cardiovascular"),
    ("Omeprazole", "Gastrointestinal"),
    ("Ranitidine", "Gastrointestinal"),
    ("Loperamide", "Gastrointestinal"),
    ("Cetirizine", "Antihistamine"),
    ("Loratadine", "Antihistamine"),
    ("Salbutamol", "Respiratory"),
    ("Prednisolone", "Corticosteroid"),
    ("Ferrous Sulphate", "Supplement"),
    ("Folic Acid", "Supplement"),
    ("Vitamin C", "Supplement"),
]

DOSAGE_FORMS = [
    "Tablet",
    "Capsule",
    "Oral Suspension",
    "Injection",
]

STORAGE_LOCATIONS = [
    "Main Store A-01",
    "Main Store A-02",
    "Main Store B-01",
    "Main Store B-02",
    "Pharmacy Shelf P-01",
    "Pharmacy Shelf P-02",
    "Pharmacy Shelf P-03",
    "Cold Storage C-01",
]

def generate_medicines():
    rows = []
    medicine_number = 1

    for generic_name, category in MEDICINE_CATALOGUE:
        for dosage_form in DOSAGE_FORMS:
            if medicine_number > MEDICINE_COUNT:
                break

            medicine_id = f"MED{medicine_number:03d}"
            medicine_name = f"{generic_name} {dosage_form}s"

            rows.append({
                "medicine_id": medicine_id,
                "name": medicine_name,
                "medicine_name": medicine_name,
                "generic_name": generic_name,
                "category": category,
                "dosage_form": dosage_form,
                "reorder_level": random.choice([20, 30, 40, 50]),
                "safety_stock_days": random.choice([15, 30, 45]),
                "is_active": True,
            })

            medicine_number += 1

        if medicine_number > MEDICINE_COUNT:
            break

    return rows


def generate_suppliers():
    rows = []

    for number in range(1, SUPPLIER_COUNT + 1):
        supplier_id = f"SUP{number:03d}"
        supplier_name = f"Fictional {fake.unique.company()} Medical Supplies Ltd"

        phone_number = f"+2547{random.randint(10000000, 99999999)}"

        rows.append({
            "supplier_id": supplier_id,
            "supplier_name": supplier_name,
            "name": supplier_name,
            "contact_person": fake.name(),
            "email": f"supplier{number:02d}@example.test",
            "phone_number": phone_number,
            "phone": phone_number,
            "address": f"Fictional Business Centre, Nairobi, Kenya",
            "is_active": True,
        })

    return rows


# ============================================================
# 3. GENERAL HELPERS
# ============================================================

def iso_date(value: date) -> str:
    return value.isoformat()


def iso_datetime(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def round_half_up(value) -> int:
    return int(
        Decimal(str(value)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP
        )
    )


def month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def next_month_start(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def month_end(value: date) -> date:
    last_day = calendar.monthrange(value.year, value.month)[1]
    return date(value.year, value.month, last_day)


def datetime_at(value: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(value, time(hour, minute))


def write_csv(filename: str, rows: list[dict], columns: list[str]):
    path = DATASET_DIR / filename
    dataframe = pd.DataFrame(rows, columns=columns)
    dataframe.to_csv(path, index=False, encoding="utf-8")
    return dataframe


# ============================================================
# 4. DEMAND GENERATION
# ============================================================

def generate_medicine_demand(medicine):
    """
    Generate monthly demand for one medicine.

    Demand is synthetic and does not represent actual hospital
    consumption or clinical prescribing guidance.
    """

    baseline = random.randint(15, 140)
    monthly_demand = {}

    for month_index in range(24):
        current_month = (
            date(2024, 11, 1)
            + timedelta(days=month_index * 30)
        )

        # Use actual calendar month boundaries.
        year = current_month.year
        month = current_month.month
        start = date(year, month, 1)
        end = month_end(start)

        days = (end - start).days + 1

        # Mild seasonal variation, deliberately not extreme.
        seasonal_factor = 1.0

        if month in [3, 4, 5]:
            seasonal_factor = 1.08
        elif month in [11, 12]:
            seasonal_factor = 1.05

        noise = random.uniform(0.82, 1.18)

        demand = round_half_up(
            baseline * (days / 30) * seasonal_factor * noise
        )

        monthly_demand[(year, month)] = max(0, demand)

    return monthly_demand


# ============================================================
# 5. INVENTORY AND FEFO SIMULATION
# ============================================================

def eligible_stock(batches, medicine_id, required_valid_until):
    return sum(
        batch["quantity_available"]
        for batch in batches
        if batch["medicine_id"] == medicine_id
        and batch["status"] == "Active"
        and batch["quantity_available"] > 0
        and date.fromisoformat(batch["expiry_date"]) >= required_valid_until
    )


def eligible_batches(batches, medicine_id, dispensing_date, duration):
    required_valid_until = (
        dispensing_date + timedelta(days=duration - 1)
    )

    candidates = [
        batch for batch in batches
        if batch["medicine_id"] == medicine_id
        and batch["status"] == "Active"
        and batch["quantity_available"] > 0
        and date.fromisoformat(batch["expiry_date"]) >= required_valid_until
    ]

    return sorted(
        candidates,
        key=lambda batch: (
            batch["expiry_date"],
            batch["batch_id"]
        )
    )


def allocate_fefo(
    batches,
    medicine_id,
    dispensing_date,
    quantity,
    duration,
    patient_identifier,
    timestamp,
    transaction_rows,
    transaction_counter,
):
    """
    Allocate a dispensing event across one or more batches.

    Each transaction row references exactly one batch.
    If a dispensing event spans multiple batches, it is split
    into multiple rows with the same patient identifier and time.

    A small number of documented overrides select a later
    eligible batch. Expiry and prescription-validity checks
    are never bypassed.
    """

    candidates = eligible_batches(
        batches,
        medicine_id,
        dispensing_date,
        duration
    )

    available = sum(
        batch["quantity_available"]
        for batch in candidates
    )

    if available < quantity:
        raise RuntimeError(
            f"Stock shortfall for {medicine_id} on {dispensing_date}. "
            f"Required={quantity}, eligible={available}"
        )

    remaining = quantity
    first_row = True

    # Rare controlled override: choose a later eligible batch.
    use_override = (
        len(candidates) > 1
        and random.random() < 0.005
    )

    allocation_order = list(candidates)

    if use_override:
        allocation_order = [candidates[1]] + [
            batch for batch in candidates
            if batch["batch_id"] != candidates[1]["batch_id"]
        ]

    for batch in allocation_order:
        if remaining <= 0:
            break

        allocated = min(
            remaining,
            batch["quantity_available"]
        )

        if allocated <= 0:
            continue

        batch["quantity_available"] -= allocated

        if batch["quantity_available"] == 0:
            batch["status"] = "Depleted"

        is_override = use_override and first_row

        if is_override:
            notes = (
                "Synthetic documented operational override. "
                f"Prescription duration: {duration} days."
            )
        else:
            notes = (
                f"Synthetic dispensing record. "
                f"Prescription duration: {duration} days."
            )

        transaction_counter += 1

        transaction_rows.append({
            "transaction_id": f"TXN{transaction_counter:07d}",
            "medicine_id": medicine_id,
            "batch_id": batch["batch_id"],
            "quantity_dispensed": allocated,
            "dispensed_date": iso_datetime(timestamp),
            "dispensed_at": iso_datetime(timestamp),
            "is_override": is_override,
            "patient_identifier": patient_identifier,
            "notes": notes,
        })

        remaining -= allocated
        first_row = False

    if remaining != 0:
        raise RuntimeError(
            f"FEFO allocation did not complete for {medicine_id}"
        )

    return transaction_counter


# ============================================================
# 6. PROCUREMENT AND RECEIVING SIMULATION
# ============================================================

def add_replenishment(
    medicine,
    quantity,
    order_date,
    delivery_date,
    medicines_batches,
    recommendations,
    purchase_orders,
    goods_receipts,
    goods_receipt_items,
    counters,
    suppliers,
):
    """
    Create a complete historical replenishment chain:

    ProcurementRecommendation
        -> PurchaseOrder
        -> GoodsReceipt
        -> GoodsReceiptItem
        -> MedicineBatch
    """

    medicine_id = medicine["medicine_id"]

    counters["recommendation"] += 1
    counters["purchase_order"] += 1
    counters["goods_receipt"] += 1
    counters["receipt_item"] += 1
    counters["batch"] += 1

    recommendation_id = f"REC{counters['recommendation']:06d}"
    purchase_order_id = f"PO{counters['purchase_order']:06d}"
    receipt_id = f"GR{counters['goods_receipt']:06d}"
    receipt_item_id = f"GRI{counters['receipt_item']:06d}"
    batch_id = f"BAT{counters['batch']:06d}"

    supplier = random.choice(suppliers)

    unit_cost = Decimal(str(round(random.uniform(8, 900), 2)))
    total_cost = (unit_cost * quantity).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )

    expiry_date = delivery_date + timedelta(
        days=random.randint(540, 900)
    )

    urgency = "HIGH" if quantity > 100 else "MEDIUM"

    recommendations.append({
        "recommendation_id": recommendation_id,
        "medicine_id": medicine_id,
        "forecast_id": "",
        "recommended_quantity": quantity,
        "urgency_level": urgency,
        "reasoning": (
            "Synthetic replenishment generated to maintain "
            "eligible stock coverage for historical demand."
        ),
        "status": "Actioned",
        "is_actioned": True,
        "created_at": iso_datetime(datetime_at(order_date, 9)),
        "updated_at": iso_datetime(datetime_at(delivery_date, 10)),
    })

    purchase_orders.append({
        "purchase_order_id": purchase_order_id,
        "medicine_id": medicine_id,
        "supplier_id": supplier["supplier_id"],
        "recommendation_id": recommendation_id,
        "quantity_ordered": quantity,
        "total_amount": str(total_cost),
        "total_cost": str(total_cost),
        "order_date": iso_datetime(datetime_at(order_date, 9)),
        "status": "Placed with Supplier",
    })

    goods_receipts.append({
        "goods_receipt_id": receipt_id,
        "purchase_order_id": purchase_order_id,
        "delivery_date": iso_date(delivery_date),
        "received_at": iso_datetime(datetime_at(delivery_date, 10)),
        "delivery_reference": f"DEL-{receipt_id}",
        "notes": "Synthetic historical goods receipt.",
    })

    batch = {
        "batch_id": batch_id,
        "medicine_id": medicine_id,
        "batch_number": (
            f"{medicine_id}-{delivery_date.strftime('%Y%m%d')}-"
            f"{counters['batch']:04d}"
        ),
        "quantity_received": quantity,
        "quantity_available": quantity,
        "received_date": iso_date(delivery_date),
        "expiry_date": iso_date(expiry_date),
        "storage_location": random.choice(STORAGE_LOCATIONS),
        "status": "Active",
    }

    medicines_batches.append(batch)

    goods_receipt_items.append({
        "receipt_item_id": receipt_item_id,
        "goods_receipt_id": receipt_id,
        "medicine_batch_id": batch_id,
        "batch_number": batch["batch_number"],
        "quantity_received": quantity,
        "expiry_date": iso_date(expiry_date),
        "storage_location": batch["storage_location"],
        "inspection_status": "Accepted",
        "inspected_at": iso_datetime(
            datetime_at(delivery_date, 11)
        ),
        "inspection_notes": (
            "Synthetic inspection record; accepted for inventory."
        ),
    })


# ============================================================
# 7. HISTORICAL STOCK AND DISPENSING GENERATION
# ============================================================

def generate_historical_operations(medicines, suppliers):
    batches = []
    transactions = []
    recommendations = []
    purchase_orders = []
    goods_receipts = []
    goods_receipt_items = []

    counters = {
        "recommendation": 0,
        "purchase_order": 0,
        "goods_receipt": 0,
        "receipt_item": 0,
        "batch": 0,
        "transaction": 0,
    }

    demand_by_medicine = {}

    # Initial stock received before the historical period.
    for medicine in medicines:
        medicine_id = medicine["medicine_id"]
        demand = generate_medicine_demand(medicine)
        demand_by_medicine[medicine_id] = demand

        initial_batch_quantity = max(
            20,
            round_half_up(
                np.mean(list(demand.values())) * 1.5
            )
        )

        counters["batch"] += 1
        initial_batch_id = f"BAT{counters['batch']:06d}"

        initial_expiry = date(
            2026,
            random.choice([6, 7, 8, 9, 10, 11, 12]),
            random.choice([10, 15, 20, 25])
        )

        batches.append({
            "batch_id": initial_batch_id,
            "medicine_id": medicine_id,
            "batch_number": f"{medicine_id}-INITIAL-001",
            "quantity_received": initial_batch_quantity,
            "quantity_available": initial_batch_quantity,
            "received_date": "2024-10-15",
            "expiry_date": iso_date(initial_expiry),
            "storage_location": random.choice(STORAGE_LOCATIONS),
            "status": "Active",
        })

    # Simulate monthly dispensing from November 2024 to October 2026.
    transaction_counter = 0

    for medicine in medicines:
        medicine_id = medicine["medicine_id"]
        demand = demand_by_medicine[medicine_id]

        for year in [2024, 2025, 2026]:
            months = (
                range(11, 13) if year == 2024
                else range(1, 13) if year == 2025
                else range(1, 11)
            )

            for month in months:
                start = date(year, month, 1)
                end = month_end(start)
                total_demand = demand[(year, month)]

                # Maintain stock that remains valid through the
                # end of the month plus the maximum prescription period.
                required_valid_until = (
                    end + timedelta(days=MAX_PRESCRIPTION_DAYS - 1)
                )

                stock = eligible_stock(
                    batches,
                    medicine_id,
                    required_valid_until
                )

                reserve = max(
                    10,
                    round_half_up(
                        np.mean(list(demand.values()))
                    )
                )

                target_stock = total_demand + reserve
                shortfall = max(0, target_stock - stock)

                if shortfall > 0:
                    order_date = start - timedelta(days=10)
                    delivery_date = start - timedelta(days=3)

                    add_replenishment(
                        medicine=medicine,
                        quantity=shortfall,
                        order_date=order_date,
                        delivery_date=delivery_date,
                        medicines_batches=batches,
                        recommendations=recommendations,
                        purchase_orders=purchase_orders,
                        goods_receipts=goods_receipts,
                        goods_receipt_items=goods_receipt_items,
                        counters=counters,
                        suppliers=suppliers,
                    )

                if total_demand == 0:
                    continue

                transaction_count = min(
                    total_demand,
                    max(1, round(total_demand / 5))
                )

                quantities = np.random.multinomial(
                    total_demand,
                    np.ones(transaction_count) / transaction_count
                )

                events = []

                for quantity in quantities:
                    if quantity <= 0:
                        continue

                    day_offset = random.randint(
                        0,
                        (end - start).days
                    )

                    dispensing_date = start + timedelta(days=day_offset)
                    duration = random.randint(
                        1,
                        MAX_PRESCRIPTION_DAYS
                    )

                    hour = random.randint(8, 16)
                    minute = random.randint(0, 59)

                    timestamp = datetime_at(
                        dispensing_date,
                        hour,
                        minute
                    )

                    events.append({
                        "date": dispensing_date,
                        "timestamp": timestamp,
                        "quantity": int(quantity),
                        "duration": duration,
                    })

                events.sort(key=lambda event: event["timestamp"])

                for event in events:
                    transaction_counter = allocate_fefo(
                        batches=batches,
                        medicine_id=medicine_id,
                        dispensing_date=event["date"],
                        quantity=event["quantity"],
                        duration=event["duration"],
                        patient_identifier=(
                            f"PAT{transaction_counter + 1:07d}"
                        ),
                        timestamp=event["timestamp"],
                        transaction_rows=transactions,
                        transaction_counter=transaction_counter,
                    )

    counters["transaction"] = transaction_counter

    return {
        "batches": batches,
        "transactions": transactions,
        "recommendations": recommendations,
        "purchase_orders": purchase_orders,
        "goods_receipts": goods_receipts,
        "goods_receipt_items": goods_receipt_items,
        "demand_by_medicine": demand_by_medicine,
        "counters": counters,
    }


# ============================================================
# 8. FORECASTING
# ============================================================

def transaction_period_totals(
    transactions,
    medicine_id,
    period_start,
    period_end
):
    """
    Half-open date interval:
    period_start <= dispensed_at < period_end
    """

    total_quantity = 0
    transaction_count = 0

    for transaction in transactions:
        if transaction["medicine_id"] != medicine_id:
            continue

        timestamp = datetime.fromisoformat(
            transaction["dispensed_at"]
        )

        if (
            datetime.combine(period_start, time.min)
            <= timestamp
            < datetime.combine(period_end, time.min)
        ):
            total_quantity += int(
                transaction["quantity_dispensed"]
            )
            transaction_count += 1

    return total_quantity, transaction_count


def calculate_forecast(
    transactions,
    medicine_id,
    origin
):
    period_volumes = []
    transaction_counts = []

    history_start = origin - timedelta(
        days=PERIOD_DAYS * HISTORY_PERIODS
    )

    for period_number in range(HISTORY_PERIODS):
        start = history_start + timedelta(
            days=period_number * PERIOD_DAYS
        )
        end = start + timedelta(days=PERIOD_DAYS)

        quantity, count = transaction_period_totals(
            transactions,
            medicine_id,
            start,
            end
        )

        period_volumes.append(quantity)
        transaction_counts.append(count)

    moving_average = round_half_up(
        sum(period_volumes) / HISTORY_PERIODS
    )

    highest = max(period_volumes)
    lowest = min(period_volumes)

    if highest == 0:
        consistency_score = Decimal("0.00")
    else:
        score = Decimal("100") * (
            Decimal("1")
            - Decimal(highest - lowest) / Decimal(highest)
        )

        score = max(Decimal("0"), min(Decimal("100"), score))

        consistency_score = score.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

    return {
        "history_start_date": history_start,
        "history_end_date": origin,
        "period_volumes": period_volumes,
        "moving_average": moving_average,
        "transaction_count": sum(transaction_counts),
        "confidence_score": str(consistency_score),
    }


def generate_forecasts(medicines, transactions):
    evaluation_rows = []
    november_rows = []

    evaluation_actuals = {}

    forecast_counter = 0

    # Six rolling-origin evaluation periods.
    for origin in EVALUATION_ORIGINS:
        actual_start = origin
        actual_end = next_month_start(origin)

        for medicine in medicines:
            medicine_id = medicine["medicine_id"]

            result = calculate_forecast(
                transactions,
                medicine_id,
                origin
            )

            actual_quantity, _ = transaction_period_totals(
                transactions,
                medicine_id,
                actual_start,
                actual_end
            )

            forecast_counter += 1
            forecasted = result["moving_average"]

            evaluation_rows.append({
                "forecast_id": f"FCE{forecast_counter:06d}",
                "medicine_id": medicine_id,
                "forecast_period_start": iso_date(origin),
                "forecast_period_end": iso_date(
                    actual_end - timedelta(days=1)
                ),
                "forecasted_demand_quantity": forecasted,
                "moving_avg_3month": forecasted,
                "forecast_method": "MOVING_AVERAGE",
                "history_start_date": iso_date(
                    result["history_start_date"]
                ),
                "history_end_date": iso_date(
                    result["history_end_date"]
                ),
                "historical_transaction_count": (
                    result["transaction_count"]
                ),
                "confidence_score": result["confidence_score"],
                "actual_demand_quantity": actual_quantity,
                "absolute_error": abs(forecasted - actual_quantity),
                "generated_at": iso_datetime(
                    datetime_at(origin, 8)
                ),
            })

            days_in_month = (
                actual_end - actual_start
            ).days

            normalized_actual = (
                actual_quantity * PERIOD_DAYS / days_in_month
            )

            evaluation_actuals[
                (medicine_id, origin)
            ] = {
                "forecast": forecasted,
                "actual": actual_quantity,
                "normalized_actual": normalized_actual,
            }

    # November forward forecasts.
    # Origin is 1 November; the history window is the preceding
    # 90 days, ending at the beginning of 1 November.
    forward_origin = FORWARD_FORECAST_START

    for medicine in medicines:
        medicine_id = medicine["medicine_id"]

        result = calculate_forecast(
            transactions,
            medicine_id,
            forward_origin
        )

        forecast_counter += 1

        november_rows.append({
            "forecast_id": f"FCN{forecast_counter:06d}",
            "medicine_id": medicine_id,
            "forecast_period_start": iso_date(
                FORWARD_FORECAST_START
            ),
            "forecast_period_end": iso_date(
                FORWARD_FORECAST_END
            ),
            "forecasted_demand_quantity": (
                result["moving_average"]
            ),
            "moving_avg_3month": result["moving_average"],
            "forecast_method": "MOVING_AVERAGE",
            "history_start_date": iso_date(
                result["history_start_date"]
            ),
            "history_end_date": iso_date(
                result["history_end_date"]
            ),
            "historical_transaction_count": (
                result["transaction_count"]
            ),
            "confidence_score": result["confidence_score"],
            "actual_demand_quantity": "",
            "absolute_error": "",
            "generated_at": iso_datetime(
                datetime_at(SNAPSHOT_DATE, 9)
            ),
        })

    return evaluation_rows, november_rows, evaluation_actuals


# ============================================================
# 9. NOVEMBER PROCUREMENT RECOMMENDATIONS AND PURCHASE ORDERS
# ============================================================

def generate_november_procurement(
    medicines,
    batches,
    november_forecasts,
    recommendations,
    purchase_orders,
    suppliers,
    counters,
):
    forecast_by_medicine = {
        row["medicine_id"]: row
        for row in november_forecasts
    }

    for medicine in medicines:
        medicine_id = medicine["medicine_id"]
        forecast = forecast_by_medicine[medicine_id]

        eligible = sum(
            batch["quantity_available"]
            for batch in batches
            if batch["medicine_id"] == medicine_id
            and batch["status"] == "Active"
            and batch["quantity_available"] > 0
            and date.fromisoformat(batch["expiry_date"])
                > SNAPSHOT_DATE
        )

        moving_average = int(
            forecast["forecasted_demand_quantity"]
        )

        target_stock = round_half_up(
            moving_average
            * (30 + int(medicine["safety_stock_days"]))
            / 30
        )

        recommended_quantity = max(
            0,
            target_stock - eligible
        )

        if recommended_quantity <= 0:
            continue

        urgency = (
            "HIGH"
            if moving_average > 0
            and eligible <= moving_average / 2
            else "MEDIUM"
        )

        counters["recommendation"] += 1
        recommendation_id = (
            f"REC{counters['recommendation']:06d}"
        )

        # Default recommendation state: Pending.
        recommendation_status = "Pending"
        is_actioned = False

        recommendations.append({
            "recommendation_id": recommendation_id,
            "medicine_id": medicine_id,
            "forecast_id": forecast["forecast_id"],
            "recommended_quantity": recommended_quantity,
            "urgency_level": urgency,
            "reasoning": (
                "November 2026 moving-average forecast indicates "
                "a projected stock shortfall against target stock."
            ),
            "status": recommendation_status,
            "is_actioned": is_actioned,
            "created_at": iso_datetime(
                datetime_at(SNAPSHOT_DATE, 9)
            ),
            "updated_at": iso_datetime(
                datetime_at(SNAPSHOT_DATE, 9)
            ),
        })

        # Only a subset of recommendations proceeds to a PO.
        if random.random() > 0.45:
            continue

        counters["purchase_order"] += 1
        purchase_order_id = (
            f"PO{counters['purchase_order']:06d}"
        )

        supplier = random.choice(suppliers)

        po_status = random.choices(
            [
                "Pending Admin Review",
                "Rejected",
                "Approved",
                "Placed with Supplier",
            ],
            weights=[40, 15, 20, 25],
            k=1
        )[0]

        if po_status == "Rejected":
            recommendation_status = "Rejected"
            is_actioned = False
        elif po_status in ["Approved", "Placed with Supplier"]:
            recommendation_status = "Actioned"
            is_actioned = True
        else:
            recommendation_status = "Pending"
            is_actioned = False

        recommendations[-1]["status"] = recommendation_status
        recommendations[-1]["is_actioned"] = is_actioned

        unit_cost = Decimal(
            str(round(random.uniform(8, 900), 2))
        )

        total_cost = (
            unit_cost * recommended_quantity
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        purchase_orders.append({
            "purchase_order_id": purchase_order_id,
            "medicine_id": medicine_id,
            "supplier_id": supplier["supplier_id"],
            "recommendation_id": recommendation_id,
            "quantity_ordered": recommended_quantity,
            "total_amount": str(total_cost),
            "total_cost": str(total_cost),
            "order_date": iso_datetime(
                datetime_at(SNAPSHOT_DATE, 10)
            ),
            "status": po_status,
        })


# ============================================================
# 10. EVALUATION METRICS
# ============================================================

def calculate_evaluation_metrics(evaluation_actuals):
    errors = []
    absolute_actuals = []
    percentage_errors = []

    for values in evaluation_actuals.values():
        forecast = values["forecast"]
        actual_30_day = values["normalized_actual"]

        error = abs(forecast - actual_30_day)

        errors.append(error)
        absolute_actuals.append(actual_30_day)

        if actual_30_day > 0:
            percentage_errors.append(
                error / actual_30_day * 100
            )

    mae = float(np.mean(errors)) if errors else 0.0

    total_actual = sum(absolute_actuals)
    total_absolute_error = sum(errors)

    wape = (
        total_absolute_error / total_actual * 100
        if total_actual > 0 else 0.0
    )

    mape = (
        float(np.mean(percentage_errors))
        if percentage_errors else None
    )

    return {
        "MAE_30_day_equivalent": round(mae, 2),
        "WAPE_percent": round(wape, 2),
        "MAPE_percent": (
            round(mape, 2) if mape is not None else None
        ),
        "MAPE_note": (
            "MAPE excludes observations with zero actual demand."
        ),
        "normalization_note": (
            "Calendar-month actual demand is converted to a "
            "30-day equivalent for evaluation metrics. The CSV "
            "retains raw calendar-month actual demand."
        ),
    }


# ============================================================
# 11. DATASET EXPORT
# ============================================================

def export_all_datasets(
    medicines,
    suppliers,
    operations,
    evaluation_forecasts,
    november_forecasts,
):
    write_csv(
        "medicines.csv",
        medicines,
        [
            "medicine_id", "name", "medicine_name", "generic_name",
            "category", "dosage_form", "reorder_level",
            "safety_stock_days", "is_active"
        ]
    )

    write_csv(
        "suppliers.csv",
        suppliers,
        [
            "supplier_id", "supplier_name", "name", "contact_person",
            "email", "phone_number", "phone", "address", "is_active"
        ]
    )

    write_csv(
        "medicine_batches.csv",
        operations["batches"],
        [
            "batch_id", "medicine_id", "batch_number",
            "quantity_received", "quantity_available",
            "received_date", "expiry_date", "storage_location",
            "status"
        ]
    )

    write_csv(
        "dispensing_transactions.csv",
        operations["transactions"],
        [
            "transaction_id", "medicine_id", "batch_id",
            "quantity_dispensed", "dispensed_date", "dispensed_at",
            "is_override", "patient_identifier", "notes"
        ]
    )

    forecast_columns = [
        "forecast_id", "medicine_id", "forecast_period_start",
        "forecast_period_end", "forecasted_demand_quantity",
        "moving_avg_3month", "forecast_method",
        "history_start_date", "history_end_date",
        "historical_transaction_count", "confidence_score",
        "actual_demand_quantity", "absolute_error", "generated_at"
    ]

    write_csv(
        "demand_forecasts_evaluation.csv",
        evaluation_forecasts,
        forecast_columns
    )

    write_csv(
        "demand_forecasts_november_2026.csv",
        november_forecasts,
        forecast_columns
    )

    write_csv(
        "procurement_recommendations.csv",
        operations["recommendations"],
        [
            "recommendation_id", "medicine_id", "forecast_id",
            "recommended_quantity", "urgency_level", "reasoning",
            "status", "is_actioned", "created_at", "updated_at"
        ]
    )

    write_csv(
        "purchase_orders.csv",
        operations["purchase_orders"],
        [
            "purchase_order_id", "medicine_id", "supplier_id",
            "recommendation_id", "quantity_ordered",
            "total_amount", "total_cost", "order_date", "status"
        ]
    )

    write_csv(
        "goods_receipts.csv",
        operations["goods_receipts"],
        [
            "goods_receipt_id", "purchase_order_id", "delivery_date",
            "received_at", "delivery_reference", "notes"
        ]
    )

    write_csv(
        "goods_receipt_items.csv",
        operations["goods_receipt_items"],
        [
            "receipt_item_id", "goods_receipt_id",
            "medicine_batch_id", "batch_number",
            "quantity_received", "expiry_date", "storage_location",
            "inspection_status", "inspected_at", "inspection_notes"
        ]
    )


# ============================================================
# 12. GENERATION SUMMARY
# ============================================================

def generate_summary(
    operations,
    evaluation_forecasts,
    november_forecasts,
    metrics,
):
    datasets = {
        "medicines.csv": MEDICINE_COUNT,
        "suppliers.csv": SUPPLIER_COUNT,
        "medicine_batches.csv": len(operations["batches"]),
        "dispensing_transactions.csv": len(operations["transactions"]),
        "demand_forecasts_evaluation.csv": len(evaluation_forecasts),
        "demand_forecasts_november_2026.csv": len(november_forecasts),
        "procurement_recommendations.csv": len(
            operations["recommendations"]
        ),
        "purchase_orders.csv": len(operations["purchase_orders"]),
        "goods_receipts.csv": len(operations["goods_receipts"]),
        "goods_receipt_items.csv": len(
            operations["goods_receipt_items"]
        ),
    }

    summary = {
        "project": (
            "Demand-Driven Medicine Expiry Management System "
            "using FEFO"
        ),
        "random_seed": SEED,
        "historical_start": iso_date(HISTORY_START),
        "historical_end": iso_date(HISTORY_END),
        "snapshot_date": iso_date(SNAPSHOT_DATE),
        "forecast_period": (
            f"{iso_date(FORWARD_FORECAST_START)} to "
            f"{iso_date(FORWARD_FORECAST_END)}"
        ),
        "training_period_months": TRAINING_MONTHS,
        "evaluation_period_months": EVALUATION_MONTHS,
        "dataset_record_counts": datasets,
        "forecast_evaluation_metrics": metrics,
        "generation_restrictions": [
            "No connection to Django database was made.",
            "No records were imported into Django.",
            "All supplier and patient identifiers are synthetic.",
            "Synthetic costs are illustrative and not market quotations.",
            "Forecast consistency score is not a probability.",
            "Historical actual demand is retained as calendar-month demand.",
        ],
    }

    json_path = REPORT_DIR / "generation_summary.json"
    text_path = REPORT_DIR / "generation_summary.txt"

    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(summary, file, indent=4)

    lines = [
        "SYNTHETIC DATASET GENERATION SUMMARY",
        "=" * 48,
        f"Random seed: {SEED}",
        f"Historical period: {HISTORY_START} to {HISTORY_END}",
        f"Inventory snapshot: {SNAPSHOT_DATE}",
        (
            "Forward forecast: "
            f"{FORWARD_FORECAST_START} to {FORWARD_FORECAST_END}"
        ),
        "",
        "DATASET RECORD COUNTS",
        "-" * 48,
    ]

    for filename, count in datasets.items():
        lines.append(f"{filename}: {count:,}")

    lines.extend([
        "",
        "FORECAST EVALUATION",
        "-" * 48,
        f"30-day equivalent MAE: {metrics['MAE_30_day_equivalent']}",
        f"WAPE: {metrics['WAPE_percent']}%",
        f"MAPE: {metrics['MAPE_percent']}",
        metrics["MAPE_note"],
        metrics["normalization_note"],
        "",
        "IMPORTANT",
        "-" * 48,
        "This generation run did not connect to Django.",
        "No records were imported into the application database.",
        "All CSV files must undergo independent cleaning and validation.",
        "The generated files are for inspection only.",
    ])

    with open(text_path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines))

    print("\n".join(lines))


# ============================================================
# 13. MAIN
# ============================================================

def main():
    print("Starting synthetic dataset generation...")
    print(f"Random seed: {SEED}")

    medicines = generate_medicines()
    suppliers = generate_suppliers()

    print(f"Generated {len(medicines)} medicines.")
    print(f"Generated {len(suppliers)} suppliers.")

    operations = generate_historical_operations(
        medicines,
        suppliers
    )

    print(
        "Historical dispensing transactions generated: "
        f"{len(operations['transactions']):,}"
    )

    evaluation_forecasts, november_forecasts, evaluation_actuals = (
        generate_forecasts(
            medicines,
            operations["transactions"]
        )
    )

    generate_november_procurement(
        medicines=medicines,
        batches=operations["batches"],
        november_forecasts=november_forecasts,
        recommendations=operations["recommendations"],
        purchase_orders=operations["purchase_orders"],
        suppliers=suppliers,
        counters=operations["counters"],
    )

    metrics = calculate_evaluation_metrics(
        evaluation_actuals
    )

    export_all_datasets(
        medicines=medicines,
        suppliers=suppliers,
        operations=operations,
        evaluation_forecasts=evaluation_forecasts,
        november_forecasts=november_forecasts,
    )

    generate_summary(
        operations=operations,
        evaluation_forecasts=evaluation_forecasts,
        november_forecasts=november_forecasts,
        metrics=metrics,
    )

    print("\nGeneration completed.")
    print(f"Datasets: {DATASET_DIR}")
    print(f"Summary: {REPORT_DIR}")


if __name__ == "__main__":
    main()
PYcat > synthetic_dataset_package/scripts/generation_script.py <<'PY'
"""
Synthetic dataset generator for:
Web-Based Demand-Driven Medicine Expiry Management System
using the First Expiry First Out (FEFO) Approach.

This script:
- Generates ten related CSV datasets.
- Uses a fixed random seed for reproducibility.
- Simulates 24 months of historical demand and stock movements.
- Allocates dispensing transactions using date-aware FEFO.
- Simulates procurement, purchase orders and goods receipts.
- Generates six-month forecast evaluation data.
- Generates November 2026 forward forecasts.
- Produces a generation summary.

It does NOT connect to Django or import data into the database.
"""

from __future__ import annotations

import calendar
import json
import math
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker


# ============================================================
# 1. CONFIGURATION
# ============================================================

SEED = 20261109

random.seed(SEED)
np.random.seed(SEED)

fake = Faker()
Faker.seed(SEED)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = PROJECT_ROOT / "synthetic_dataset_package"
DATASET_DIR = PACKAGE_DIR / "datasets"
REPORT_DIR = PACKAGE_DIR / "reports"

DATASET_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

HISTORY_START = date(2024, 11, 1)
HISTORY_END = date(2026, 10, 31)

SNAPSHOT_DATE = date(2026, 11, 9)
FORWARD_FORECAST_START = date(2026, 11, 1)
FORWARD_FORECAST_END = date(2026, 11, 30)

TRAINING_MONTHS = 18
EVALUATION_MONTHS = 6

PERIOD_DAYS = 30
HISTORY_PERIODS = 3
MAX_PRESCRIPTION_DAYS = 14

MEDICINE_COUNT = 100
SUPPLIER_COUNT = 15

# Fixed historical evaluation origins.
EVALUATION_ORIGINS = [
    date(2026, month, 1)
    for month in range(5, 11)
]

# All generated IDs are external dataset identifiers.
# They are NOT Django primary keys.


# ============================================================
# 2. MEDICINE AND SUPPLIER MASTER DATA
# ============================================================

MEDICINE_CATALOGUE = [
    ("Paracetamol", "Analgesic"),
    ("Ibuprofen", "Analgesic"),
    ("Diclofenac", "Analgesic"),
    ("Amoxicillin", "Antibiotic"),
    ("Azithromycin", "Antibiotic"),
    ("Ciprofloxacin", "Antibiotic"),
    ("Metronidazole", "Antibiotic"),
    ("Doxycycline", "Antibiotic"),
    ("Metformin", "Antidiabetic"),
    ("Glibenclamide", "Antidiabetic"),
    ("Amlodipine", "Cardiovascular"),
    ("Losartan", "Cardiovascular"),
    ("Atenolol", "Cardiovascular"),
    ("Enalapril", "Cardiovascular"),
    ("Hydrochlorothiazide", "Cardiovascular"),
    ("Omeprazole", "Gastrointestinal"),
    ("Ranitidine", "Gastrointestinal"),
    ("Loperamide", "Gastrointestinal"),
    ("Cetirizine", "Antihistamine"),
    ("Loratadine", "Antihistamine"),
    ("Salbutamol", "Respiratory"),
    ("Prednisolone", "Corticosteroid"),
    ("Ferrous Sulphate", "Supplement"),
    ("Folic Acid", "Supplement"),
    ("Vitamin C", "Supplement"),
]

DOSAGE_FORMS = [
    "Tablet",
    "Capsule",
    "Oral Suspension",
    "Injection",
]

STORAGE_LOCATIONS = [
    "Main Store A-01",
    "Main Store A-02",
    "Main Store B-01",
    "Main Store B-02",
    "Pharmacy Shelf P-01",
    "Pharmacy Shelf P-02",
    "Pharmacy Shelf P-03",
    "Cold Storage C-01",
]

def generate_medicines():
    rows = []
    medicine_number = 1

    for generic_name, category in MEDICINE_CATALOGUE:
        for dosage_form in DOSAGE_FORMS:
            if medicine_number > MEDICINE_COUNT:
                break

            medicine_id = f"MED{medicine_number:03d}"
            medicine_name = f"{generic_name} {dosage_form}s"

            rows.append({
                "medicine_id": medicine_id,
                "name": medicine_name,
                "medicine_name": medicine_name,
                "generic_name": generic_name,
                "category": category,
                "dosage_form": dosage_form,
                "reorder_level": random.choice([20, 30, 40, 50]),
                "safety_stock_days": random.choice([15, 30, 45]),
                "is_active": True,
            })

            medicine_number += 1

        if medicine_number > MEDICINE_COUNT:
            break

    return rows


def generate_suppliers():
    rows = []

    for number in range(1, SUPPLIER_COUNT + 1):
        supplier_id = f"SUP{number:03d}"
        supplier_name = f"Fictional {fake.unique.company()} Medical Supplies Ltd"

        phone_number = f"+2547{random.randint(10000000, 99999999)}"

        rows.append({
            "supplier_id": supplier_id,
            "supplier_name": supplier_name,
            "name": supplier_name,
            "contact_person": fake.name(),
            "email": f"supplier{number:02d}@example.test",
            "phone_number": phone_number,
            "phone": phone_number,
            "address": f"Fictional Business Centre, Nairobi, Kenya",
            "is_active": True,
        })

    return rows


# ============================================================
# 3. GENERAL HELPERS
# ============================================================

def iso_date(value: date) -> str:
    return value.isoformat()


def iso_datetime(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def round_half_up(value) -> int:
    return int(
        Decimal(str(value)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP
        )
    )


def month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def next_month_start(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def month_end(value: date) -> date:
    last_day = calendar.monthrange(value.year, value.month)[1]
    return date(value.year, value.month, last_day)


def datetime_at(value: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(value, time(hour, minute))


def write_csv(filename: str, rows: list[dict], columns: list[str]):
    path = DATASET_DIR / filename
    dataframe = pd.DataFrame(rows, columns=columns)
    dataframe.to_csv(path, index=False, encoding="utf-8")
    return dataframe


# ============================================================
# 4. DEMAND GENERATION
# ============================================================

def generate_medicine_demand(medicine):
    """
    Generate monthly demand for one medicine.

    Demand is synthetic and does not represent actual hospital
    consumption or clinical prescribing guidance.
    """

    baseline = random.randint(15, 140)
    monthly_demand = {}

    for month_index in range(24):
        current_month = (
            date(2024, 11, 1)
            + timedelta(days=month_index * 30)
        )

        # Use actual calendar month boundaries.
        year = current_month.year
        month = current_month.month
        start = date(year, month, 1)
        end = month_end(start)

        days = (end - start).days + 1

        # Mild seasonal variation, deliberately not extreme.
        seasonal_factor = 1.0

        if month in [3, 4, 5]:
            seasonal_factor = 1.08
        elif month in [11, 12]:
            seasonal_factor = 1.05

        noise = random.uniform(0.82, 1.18)

        demand = round_half_up(
            baseline * (days / 30) * seasonal_factor * noise
        )

        monthly_demand[(year, month)] = max(0, demand)

    return monthly_demand


# ============================================================
# 5. INVENTORY AND FEFO SIMULATION
# ============================================================

def eligible_stock(batches, medicine_id, required_valid_until):
    return sum(
        batch["quantity_available"]
        for batch in batches
        if batch["medicine_id"] == medicine_id
        and batch["status"] == "Active"
        and batch["quantity_available"] > 0
        and date.fromisoformat(batch["expiry_date"]) >= required_valid_until
    )


def eligible_batches(batches, medicine_id, dispensing_date, duration):
    required_valid_until = (
        dispensing_date + timedelta(days=duration - 1)
    )

    candidates = [
        batch for batch in batches
        if batch["medicine_id"] == medicine_id
        and batch["status"] == "Active"
        and batch["quantity_available"] > 0
        and date.fromisoformat(batch["expiry_date"]) >= required_valid_until
    ]

    return sorted(
        candidates,
        key=lambda batch: (
            batch["expiry_date"],
            batch["batch_id"]
        )
    )


def allocate_fefo(
    batches,
    medicine_id,
    dispensing_date,
    quantity,
    duration,
    patient_identifier,
    timestamp,
    transaction_rows,
    transaction_counter,
):
    """
    Allocate a dispensing event across one or more batches.

    Each transaction row references exactly one batch.
    If a dispensing event spans multiple batches, it is split
    into multiple rows with the same patient identifier and time.

    A small number of documented overrides select a later
    eligible batch. Expiry and prescription-validity checks
    are never bypassed.
    """

    candidates = eligible_batches(
        batches,
        medicine_id,
        dispensing_date,
        duration
    )

    available = sum(
        batch["quantity_available"]
        for batch in candidates
    )

    if available < quantity:
        raise RuntimeError(
            f"Stock shortfall for {medicine_id} on {dispensing_date}. "
            f"Required={quantity}, eligible={available}"
        )

    remaining = quantity
    first_row = True

    # Rare controlled override: choose a later eligible batch.
    use_override = (
        len(candidates) > 1
        and random.random() < 0.005
    )

    allocation_order = list(candidates)

    if use_override:
        allocation_order = [candidates[1]] + [
            batch for batch in candidates
            if batch["batch_id"] != candidates[1]["batch_id"]
        ]

    for batch in allocation_order:
        if remaining <= 0:
            break

        allocated = min(
            remaining,
            batch["quantity_available"]
        )

        if allocated <= 0:
            continue

        batch["quantity_available"] -= allocated

        if batch["quantity_available"] == 0:
            batch["status"] = "Depleted"

        is_override = use_override and first_row

        if is_override:
            notes = (
                "Synthetic documented operational override. "
                f"Prescription duration: {duration} days."
            )
        else:
            notes = (
                f"Synthetic dispensing record. "
                f"Prescription duration: {duration} days."
            )

        transaction_counter += 1

        transaction_rows.append({
            "transaction_id": f"TXN{transaction_counter:07d}",
            "medicine_id": medicine_id,
            "batch_id": batch["batch_id"],
            "quantity_dispensed": allocated,
            "dispensed_date": iso_datetime(timestamp),
            "dispensed_at": iso_datetime(timestamp),
            "is_override": is_override,
            "patient_identifier": patient_identifier,
            "notes": notes,
        })

        remaining -= allocated
        first_row = False

    if remaining != 0:
        raise RuntimeError(
            f"FEFO allocation did not complete for {medicine_id}"
        )

    return transaction_counter


# ============================================================
# 6. PROCUREMENT AND RECEIVING SIMULATION
# ============================================================

def add_replenishment(
    medicine,
    quantity,
    order_date,
    delivery_date,
    medicines_batches,
    recommendations,
    purchase_orders,
    goods_receipts,
    goods_receipt_items,
    counters,
    suppliers,
):
    """
    Create a complete historical replenishment chain:

    ProcurementRecommendation
        -> PurchaseOrder
        -> GoodsReceipt
        -> GoodsReceiptItem
        -> MedicineBatch
    """

    medicine_id = medicine["medicine_id"]

    counters["recommendation"] += 1
    counters["purchase_order"] += 1
    counters["goods_receipt"] += 1
    counters["receipt_item"] += 1
    counters["batch"] += 1

    recommendation_id = f"REC{counters['recommendation']:06d}"
    purchase_order_id = f"PO{counters['purchase_order']:06d}"
    receipt_id = f"GR{counters['goods_receipt']:06d}"
    receipt_item_id = f"GRI{counters['receipt_item']:06d}"
    batch_id = f"BAT{counters['batch']:06d}"

    supplier = random.choice(suppliers)

    unit_cost = Decimal(str(round(random.uniform(8, 900), 2)))
    total_cost = (unit_cost * quantity).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )

    expiry_date = delivery_date + timedelta(
        days=random.randint(540, 900)
    )

    urgency = "HIGH" if quantity > 100 else "MEDIUM"

    recommendations.append({
        "recommendation_id": recommendation_id,
        "medicine_id": medicine_id,
        "forecast_id": "",
        "recommended_quantity": quantity,
        "urgency_level": urgency,
        "reasoning": (
            "Synthetic replenishment generated to maintain "
            "eligible stock coverage for historical demand."
        ),
        "status": "Actioned",
        "is_actioned": True,
        "created_at": iso_datetime(datetime_at(order_date, 9)),
        "updated_at": iso_datetime(datetime_at(delivery_date, 10)),
    })

    purchase_orders.append({
        "purchase_order_id": purchase_order_id,
        "medicine_id": medicine_id,
        "supplier_id": supplier["supplier_id"],
        "recommendation_id": recommendation_id,
        "quantity_ordered": quantity,
        "total_amount": str(total_cost),
        "total_cost": str(total_cost),
        "order_date": iso_datetime(datetime_at(order_date, 9)),
        "status": "Placed with Supplier",
    })

    goods_receipts.append({
        "goods_receipt_id": receipt_id,
        "purchase_order_id": purchase_order_id,
        "delivery_date": iso_date(delivery_date),
        "received_at": iso_datetime(datetime_at(delivery_date, 10)),
        "delivery_reference": f"DEL-{receipt_id}",
        "notes": "Synthetic historical goods receipt.",
    })

    batch = {
        "batch_id": batch_id,
        "medicine_id": medicine_id,
        "batch_number": (
            f"{medicine_id}-{delivery_date.strftime('%Y%m%d')}-"
            f"{counters['batch']:04d}"
        ),
        "quantity_received": quantity,
        "quantity_available": quantity,
        "received_date": iso_date(delivery_date),
        "expiry_date": iso_date(expiry_date),
        "storage_location": random.choice(STORAGE_LOCATIONS),
        "status": "Active",
    }

    medicines_batches.append(batch)

    goods_receipt_items.append({
        "receipt_item_id": receipt_item_id,
        "goods_receipt_id": receipt_id,
        "medicine_batch_id": batch_id,
        "batch_number": batch["batch_number"],
        "quantity_received": quantity,
        "expiry_date": iso_date(expiry_date),
        "storage_location": batch["storage_location"],
        "inspection_status": "Accepted",
        "inspected_at": iso_datetime(
            datetime_at(delivery_date, 11)
        ),
        "inspection_notes": (
            "Synthetic inspection record; accepted for inventory."
        ),
    })


# ============================================================
# 7. HISTORICAL STOCK AND DISPENSING GENERATION
# ============================================================

def generate_historical_operations(medicines, suppliers):
    batches = []
    transactions = []
    recommendations = []
    purchase_orders = []
    goods_receipts = []
    goods_receipt_items = []

    counters = {
        "recommendation": 0,
        "purchase_order": 0,
        "goods_receipt": 0,
        "receipt_item": 0,
        "batch": 0,
        "transaction": 0,
    }

    demand_by_medicine = {}

    # Initial stock received before the historical period.
    for medicine in medicines:
        medicine_id = medicine["medicine_id"]
        demand = generate_medicine_demand(medicine)
        demand_by_medicine[medicine_id] = demand

        initial_batch_quantity = max(
            20,
            round_half_up(
                np.mean(list(demand.values())) * 1.5
            )
        )

        counters["batch"] += 1
        initial_batch_id = f"BAT{counters['batch']:06d}"

        initial_expiry = date(
            2026,
            random.choice([6, 7, 8, 9, 10, 11, 12]),
            random.choice([10, 15, 20, 25])
        )

        batches.append({
            "batch_id": initial_batch_id,
            "medicine_id": medicine_id,
            "batch_number": f"{medicine_id}-INITIAL-001",
            "quantity_received": initial_batch_quantity,
            "quantity_available": initial_batch_quantity,
            "received_date": "2024-10-15",
            "expiry_date": iso_date(initial_expiry),
            "storage_location": random.choice(STORAGE_LOCATIONS),
            "status": "Active",
        })

    # Simulate monthly dispensing from November 2024 to October 2026.
    transaction_counter = 0

    for medicine in medicines:
        medicine_id = medicine["medicine_id"]
        demand = demand_by_medicine[medicine_id]

        for year in [2024, 2025, 2026]:
            months = (
                range(11, 13) if year == 2024
                else range(1, 13) if year == 2025
                else range(1, 11)
            )

            for month in months:
                start = date(year, month, 1)
                end = month_end(start)
                total_demand = demand[(year, month)]

                # Maintain stock that remains valid through the
                # end of the month plus the maximum prescription period.
                required_valid_until = (
                    end + timedelta(days=MAX_PRESCRIPTION_DAYS - 1)
                )

                stock = eligible_stock(
                    batches,
                    medicine_id,
                    required_valid_until
                )

                reserve = max(
                    10,
                    round_half_up(
                        np.mean(list(demand.values()))
                    )
                )

                target_stock = total_demand + reserve
                shortfall = max(0, target_stock - stock)

                if shortfall > 0:
                    order_date = start - timedelta(days=10)
                    delivery_date = start - timedelta(days=3)

                    add_replenishment(
                        medicine=medicine,
                        quantity=shortfall,
                        order_date=order_date,
                        delivery_date=delivery_date,
                        medicines_batches=batches,
                        recommendations=recommendations,
                        purchase_orders=purchase_orders,
                        goods_receipts=goods_receipts,
                        goods_receipt_items=goods_receipt_items,
                        counters=counters,
                        suppliers=suppliers,
                    )

                if total_demand == 0:
                    continue

                transaction_count = min(
                    total_demand,
                    max(1, round(total_demand / 5))
                )

                quantities = np.random.multinomial(
                    total_demand,
                    np.ones(transaction_count) / transaction_count
                )

                events = []

                for quantity in quantities:
                    if quantity <= 0:
                        continue

                    day_offset = random.randint(
                        0,
                        (end - start).days
                    )

                    dispensing_date = start + timedelta(days=day_offset)
                    duration = random.randint(
                        1,
                        MAX_PRESCRIPTION_DAYS
                    )

                    hour = random.randint(8, 16)
                    minute = random.randint(0, 59)

                    timestamp = datetime_at(
                        dispensing_date,
                        hour,
                        minute
                    )

                    events.append({
                        "date": dispensing_date,
                        "timestamp": timestamp,
                        "quantity": int(quantity),
                        "duration": duration,
                    })

                events.sort(key=lambda event: event["timestamp"])

                for event in events:
                    transaction_counter = allocate_fefo(
                        batches=batches,
                        medicine_id=medicine_id,
                        dispensing_date=event["date"],
                        quantity=event["quantity"],
                        duration=event["duration"],
                        patient_identifier=(
                            f"PAT{transaction_counter + 1:07d}"
                        ),
                        timestamp=event["timestamp"],
                        transaction_rows=transactions,
                        transaction_counter=transaction_counter,
                    )

    counters["transaction"] = transaction_counter

    return {
        "batches": batches,
        "transactions": transactions,
        "recommendations": recommendations,
        "purchase_orders": purchase_orders,
        "goods_receipts": goods_receipts,
        "goods_receipt_items": goods_receipt_items,
        "demand_by_medicine": demand_by_medicine,
        "counters": counters,
    }


# ============================================================
# 8. FORECASTING
# ============================================================

def transaction_period_totals(
    transactions,
    medicine_id,
    period_start,
    period_end
):
    """
    Half-open date interval:
    period_start <= dispensed_at < period_end
    """

    total_quantity = 0
    transaction_count = 0

    for transaction in transactions:
        if transaction["medicine_id"] != medicine_id:
            continue

        timestamp = datetime.fromisoformat(
            transaction["dispensed_at"]
        )

        if (
            datetime.combine(period_start, time.min)
            <= timestamp
            < datetime.combine(period_end, time.min)
        ):
            total_quantity += int(
                transaction["quantity_dispensed"]
            )
            transaction_count += 1

    return total_quantity, transaction_count


def calculate_forecast(
    transactions,
    medicine_id,
    origin
):
    period_volumes = []
    transaction_counts = []

    history_start = origin - timedelta(
        days=PERIOD_DAYS * HISTORY_PERIODS
    )

    for period_number in range(HISTORY_PERIODS):
        start = history_start + timedelta(
            days=period_number * PERIOD_DAYS
        )
        end = start + timedelta(days=PERIOD_DAYS)

        quantity, count = transaction_period_totals(
            transactions,
            medicine_id,
            start,
            end
        )

        period_volumes.append(quantity)
        transaction_counts.append(count)

    moving_average = round_half_up(
        sum(period_volumes) / HISTORY_PERIODS
    )

    highest = max(period_volumes)
    lowest = min(period_volumes)

    if highest == 0:
        consistency_score = Decimal("0.00")
    else:
        score = Decimal("100") * (
            Decimal("1")
            - Decimal(highest - lowest) / Decimal(highest)
        )

        score = max(Decimal("0"), min(Decimal("100"), score))

        consistency_score = score.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

    return {
        "history_start_date": history_start,
        "history_end_date": origin,
        "period_volumes": period_volumes,
        "moving_average": moving_average,
        "transaction_count": sum(transaction_counts),
        "confidence_score": str(consistency_score),
    }


def generate_forecasts(medicines, transactions):
    evaluation_rows = []
    november_rows = []

    evaluation_actuals = {}

    forecast_counter = 0

    # Six rolling-origin evaluation periods.
    for origin in EVALUATION_ORIGINS:
        actual_start = origin
        actual_end = next_month_start(origin)

        for medicine in medicines:
            medicine_id = medicine["medicine_id"]

            result = calculate_forecast(
                transactions,
                medicine_id,
                origin
            )

            actual_quantity, _ = transaction_period_totals(
                transactions,
                medicine_id,
                actual_start,
                actual_end
            )

            forecast_counter += 1
            forecasted = result["moving_average"]

            evaluation_rows.append({
                "forecast_id": f"FCE{forecast_counter:06d}",
                "medicine_id": medicine_id,
                "forecast_period_start": iso_date(origin),
                "forecast_period_end": iso_date(
                    actual_end - timedelta(days=1)
                ),
                "forecasted_demand_quantity": forecasted,
                "moving_avg_3month": forecasted,
                "forecast_method": "MOVING_AVERAGE",
                "history_start_date": iso_date(
                    result["history_start_date"]
                ),
                "history_end_date": iso_date(
                    result["history_end_date"]
                ),
                "historical_transaction_count": (
                    result["transaction_count"]
                ),
                "confidence_score": result["confidence_score"],
                "actual_demand_quantity": actual_quantity,
                "absolute_error": abs(forecasted - actual_quantity),
                "generated_at": iso_datetime(
                    datetime_at(origin, 8)
                ),
            })

            days_in_month = (
                actual_end - actual_start
            ).days

            normalized_actual = (
                actual_quantity * PERIOD_DAYS / days_in_month
            )

            evaluation_actuals[
                (medicine_id, origin)
            ] = {
                "forecast": forecasted,
                "actual": actual_quantity,
                "normalized_actual": normalized_actual,
            }

    # November forward forecasts.
    # Origin is 1 November; the history window is the preceding
    # 90 days, ending at the beginning of 1 November.
    forward_origin = FORWARD_FORECAST_START

    for medicine in medicines:
        medicine_id = medicine["medicine_id"]

        result = calculate_forecast(
            transactions,
            medicine_id,
            forward_origin
        )

        forecast_counter += 1

        november_rows.append({
            "forecast_id": f"FCN{forecast_counter:06d}",
            "medicine_id": medicine_id,
            "forecast_period_start": iso_date(
                FORWARD_FORECAST_START
            ),
            "forecast_period_end": iso_date(
                FORWARD_FORECAST_END
            ),
            "forecasted_demand_quantity": (
                result["moving_average"]
            ),
            "moving_avg_3month": result["moving_average"],
            "forecast_method": "MOVING_AVERAGE",
            "history_start_date": iso_date(
                result["history_start_date"]
            ),
            "history_end_date": iso_date(
                result["history_end_date"]
            ),
            "historical_transaction_count": (
                result["transaction_count"]
            ),
            "confidence_score": result["confidence_score"],
            "actual_demand_quantity": "",
            "absolute_error": "",
            "generated_at": iso_datetime(
                datetime_at(SNAPSHOT_DATE, 9)
            ),
        })

    return evaluation_rows, november_rows, evaluation_actuals


# ============================================================
# 9. NOVEMBER PROCUREMENT RECOMMENDATIONS AND PURCHASE ORDERS
# ============================================================

def generate_november_procurement(
    medicines,
    batches,
    november_forecasts,
    recommendations,
    purchase_orders,
    suppliers,
    counters,
):
    forecast_by_medicine = {
        row["medicine_id"]: row
        for row in november_forecasts
    }

    for medicine in medicines:
        medicine_id = medicine["medicine_id"]
        forecast = forecast_by_medicine[medicine_id]

        eligible = sum(
            batch["quantity_available"]
            for batch in batches
            if batch["medicine_id"] == medicine_id
            and batch["status"] == "Active"
            and batch["quantity_available"] > 0
            and date.fromisoformat(batch["expiry_date"])
                > SNAPSHOT_DATE
        )

        moving_average = int(
            forecast["forecasted_demand_quantity"]
        )

        target_stock = round_half_up(
            moving_average
            * (30 + int(medicine["safety_stock_days"]))
            / 30
        )

        recommended_quantity = max(
            0,
            target_stock - eligible
        )

        if recommended_quantity <= 0:
            continue

        urgency = (
            "HIGH"
            if moving_average > 0
            and eligible <= moving_average / 2
            else "MEDIUM"
        )

        counters["recommendation"] += 1
        recommendation_id = (
            f"REC{counters['recommendation']:06d}"
        )

        # Default recommendation state: Pending.
        recommendation_status = "Pending"
        is_actioned = False

        recommendations.append({
            "recommendation_id": recommendation_id,
            "medicine_id": medicine_id,
            "forecast_id": forecast["forecast_id"],
            "recommended_quantity": recommended_quantity,
            "urgency_level": urgency,
            "reasoning": (
                "November 2026 moving-average forecast indicates "
                "a projected stock shortfall against target stock."
            ),
            "status": recommendation_status,
            "is_actioned": is_actioned,
            "created_at": iso_datetime(
                datetime_at(SNAPSHOT_DATE, 9)
            ),
            "updated_at": iso_datetime(
                datetime_at(SNAPSHOT_DATE, 9)
            ),
        })

        # Only a subset of recommendations proceeds to a PO.
        if random.random() > 0.45:
            continue

        counters["purchase_order"] += 1
        purchase_order_id = (
            f"PO{counters['purchase_order']:06d}"
        )

        supplier = random.choice(suppliers)

        po_status = random.choices(
            [
                "Pending Admin Review",
                "Rejected",
                "Approved",
                "Placed with Supplier",
            ],
            weights=[40, 15, 20, 25],
            k=1
        )[0]

        if po_status == "Rejected":
            recommendation_status = "Rejected"
            is_actioned = False
        elif po_status in ["Approved", "Placed with Supplier"]:
            recommendation_status = "Actioned"
            is_actioned = True
        else:
            recommendation_status = "Pending"
            is_actioned = False

        recommendations[-1]["status"] = recommendation_status
        recommendations[-1]["is_actioned"] = is_actioned

        unit_cost = Decimal(
            str(round(random.uniform(8, 900), 2))
        )

        total_cost = (
            unit_cost * recommended_quantity
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        purchase_orders.append({
            "purchase_order_id": purchase_order_id,
            "medicine_id": medicine_id,
            "supplier_id": supplier["supplier_id"],
            "recommendation_id": recommendation_id,
            "quantity_ordered": recommended_quantity,
            "total_amount": str(total_cost),
            "total_cost": str(total_cost),
            "order_date": iso_datetime(
                datetime_at(SNAPSHOT_DATE, 10)
            ),
            "status": po_status,
        })


# ============================================================
# 10. EVALUATION METRICS
# ============================================================

def calculate_evaluation_metrics(evaluation_actuals):
    errors = []
    absolute_actuals = []
    percentage_errors = []

    for values in evaluation_actuals.values():
        forecast = values["forecast"]
        actual_30_day = values["normalized_actual"]

        error = abs(forecast - actual_30_day)

        errors.append(error)
        absolute_actuals.append(actual_30_day)

        if actual_30_day > 0:
            percentage_errors.append(
                error / actual_30_day * 100
            )

    mae = float(np.mean(errors)) if errors else 0.0

    total_actual = sum(absolute_actuals)
    total_absolute_error = sum(errors)

    wape = (
        total_absolute_error / total_actual * 100
        if total_actual > 0 else 0.0
    )

    mape = (
        float(np.mean(percentage_errors))
        if percentage_errors else None
    )

    return {
        "MAE_30_day_equivalent": round(mae, 2),
        "WAPE_percent": round(wape, 2),
        "MAPE_percent": (
            round(mape, 2) if mape is not None else None
        ),
        "MAPE_note": (
            "MAPE excludes observations with zero actual demand."
        ),
        "normalization_note": (
            "Calendar-month actual demand is converted to a "
            "30-day equivalent for evaluation metrics. The CSV "
            "retains raw calendar-month actual demand."
        ),
    }


# ============================================================
# 11. DATASET EXPORT
# ============================================================

def export_all_datasets(
    medicines,
    suppliers,
    operations,
    evaluation_forecasts,
    november_forecasts,
):
    write_csv(
        "medicines.csv",
        medicines,
        [
            "medicine_id", "name", "medicine_name", "generic_name",
            "category", "dosage_form", "reorder_level",
            "safety_stock_days", "is_active"
        ]
    )

    write_csv(
        "suppliers.csv",
        suppliers,
        [
            "supplier_id", "supplier_name", "name", "contact_person",
            "email", "phone_number", "phone", "address", "is_active"
        ]
    )

    write_csv(
        "medicine_batches.csv",
        operations["batches"],
        [
            "batch_id", "medicine_id", "batch_number",
            "quantity_received", "quantity_available",
            "received_date", "expiry_date", "storage_location",
            "status"
        ]
    )

    write_csv(
        "dispensing_transactions.csv",
        operations["transactions"],
        [
            "transaction_id", "medicine_id", "batch_id",
            "quantity_dispensed", "dispensed_date", "dispensed_at",
            "is_override", "patient_identifier", "notes"
        ]
    )

    forecast_columns = [
        "forecast_id", "medicine_id", "forecast_period_start",
        "forecast_period_end", "forecasted_demand_quantity",
        "moving_avg_3month", "forecast_method",
        "history_start_date", "history_end_date",
        "historical_transaction_count", "confidence_score",
        "actual_demand_quantity", "absolute_error", "generated_at"
    ]

    write_csv(
        "demand_forecasts_evaluation.csv",
        evaluation_forecasts,
        forecast_columns
    )

    write_csv(
        "demand_forecasts_november_2026.csv",
        november_forecasts,
        forecast_columns
    )

    write_csv(
        "procurement_recommendations.csv",
        operations["recommendations"],
        [
            "recommendation_id", "medicine_id", "forecast_id",
            "recommended_quantity", "urgency_level", "reasoning",
            "status", "is_actioned", "created_at", "updated_at"
        ]
    )

    write_csv(
        "purchase_orders.csv",
        operations["purchase_orders"],
        [
            "purchase_order_id", "medicine_id", "supplier_id",
            "recommendation_id", "quantity_ordered",
            "total_amount", "total_cost", "order_date", "status"
        ]
    )

    write_csv(
        "goods_receipts.csv",
        operations["goods_receipts"],
        [
            "goods_receipt_id", "purchase_order_id", "delivery_date",
            "received_at", "delivery_reference", "notes"
        ]
    )

    write_csv(
        "goods_receipt_items.csv",
        operations["goods_receipt_items"],
        [
            "receipt_item_id", "goods_receipt_id",
            "medicine_batch_id", "batch_number",
            "quantity_received", "expiry_date", "storage_location",
            "inspection_status", "inspected_at", "inspection_notes"
        ]
    )


# ============================================================
# 12. GENERATION SUMMARY
# ============================================================

def generate_summary(
    operations,
    evaluation_forecasts,
    november_forecasts,
    metrics,
):
    datasets = {
        "medicines.csv": MEDICINE_COUNT,
        "suppliers.csv": SUPPLIER_COUNT,
        "medicine_batches.csv": len(operations["batches"]),
        "dispensing_transactions.csv": len(operations["transactions"]),
        "demand_forecasts_evaluation.csv": len(evaluation_forecasts),
        "demand_forecasts_november_2026.csv": len(november_forecasts),
        "procurement_recommendations.csv": len(
            operations["recommendations"]
        ),
        "purchase_orders.csv": len(operations["purchase_orders"]),
        "goods_receipts.csv": len(operations["goods_receipts"]),
        "goods_receipt_items.csv": len(
            operations["goods_receipt_items"]
        ),
    }

    summary = {
        "project": (
            "Demand-Driven Medicine Expiry Management System "
            "using FEFO"
        ),
        "random_seed": SEED,
        "historical_start": iso_date(HISTORY_START),
        "historical_end": iso_date(HISTORY_END),
        "snapshot_date": iso_date(SNAPSHOT_DATE),
        "forecast_period": (
            f"{iso_date(FORWARD_FORECAST_START)} to "
            f"{iso_date(FORWARD_FORECAST_END)}"
        ),
        "training_period_months": TRAINING_MONTHS,
        "evaluation_period_months": EVALUATION_MONTHS,
        "dataset_record_counts": datasets,
        "forecast_evaluation_metrics": metrics,
        "generation_restrictions": [
            "No connection to Django database was made.",
            "No records were imported into Django.",
            "All supplier and patient identifiers are synthetic.",
            "Synthetic costs are illustrative and not market quotations.",
            "Forecast consistency score is not a probability.",
            "Historical actual demand is retained as calendar-month demand.",
        ],
    }

    json_path = REPORT_DIR / "generation_summary.json"
    text_path = REPORT_DIR / "generation_summary.txt"

    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(summary, file, indent=4)

    lines = [
        "SYNTHETIC DATASET GENERATION SUMMARY",
        "=" * 48,
        f"Random seed: {SEED}",
        f"Historical period: {HISTORY_START} to {HISTORY_END}",
        f"Inventory snapshot: {SNAPSHOT_DATE}",
        (
            "Forward forecast: "
            f"{FORWARD_FORECAST_START} to {FORWARD_FORECAST_END}"
        ),
        "",
        "DATASET RECORD COUNTS",
        "-" * 48,
    ]

    for filename, count in datasets.items():
        lines.append(f"{filename}: {count:,}")

    lines.extend([
        "",
        "FORECAST EVALUATION",
        "-" * 48,
        f"30-day equivalent MAE: {metrics['MAE_30_day_equivalent']}",
        f"WAPE: {metrics['WAPE_percent']}%",
        f"MAPE: {metrics['MAPE_percent']}",
        metrics["MAPE_note"],
        metrics["normalization_note"],
        "",
        "IMPORTANT",
        "-" * 48,
        "This generation run did not connect to Django.",
        "No records were imported into the application database.",
        "All CSV files must undergo independent cleaning and validation.",
        "The generated files are for inspection only.",
    ])

    with open(text_path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines))

    print("\n".join(lines))


# ============================================================
# 13. MAIN
# ============================================================

def main():
    print("Starting synthetic dataset generation...")
    print(f"Random seed: {SEED}")

    medicines = generate_medicines()
    suppliers = generate_suppliers()

    print(f"Generated {len(medicines)} medicines.")
    print(f"Generated {len(suppliers)} suppliers.")

    operations = generate_historical_operations(
        medicines,
        suppliers
    )

    print(
        "Historical dispensing transactions generated: "
        f"{len(operations['transactions']):,}"
    )

    evaluation_forecasts, november_forecasts, evaluation_actuals = (
        generate_forecasts(
            medicines,
            operations["transactions"]
        )
    )

    generate_november_procurement(
        medicines=medicines,
        batches=operations["batches"],
        november_forecasts=november_forecasts,
        recommendations=operations["recommendations"],
        purchase_orders=operations["purchase_orders"],
        suppliers=suppliers,
        counters=operations["counters"],
    )

    metrics = calculate_evaluation_metrics(
        evaluation_actuals
    )

    export_all_datasets(
        medicines=medicines,
        suppliers=suppliers,
        operations=operations,
        evaluation_forecasts=evaluation_forecasts,
        november_forecasts=november_forecasts,
    )

    generate_summary(
        operations=operations,
        evaluation_forecasts=evaluation_forecasts,
        november_forecasts=november_forecasts,
        metrics=metrics,
    )

    print("\nGeneration completed.")
    print(f"Datasets: {DATASET_DIR}")
    print(f"Summary: {REPORT_DIR}")


if __name__ == "__main__":
    main()
PYcat > synthetic_dataset_package/scripts/generation_script.py <<'PY'
"""
Synthetic dataset generator for:
Web-Based Demand-Driven Medicine Expiry Management System
using the First Expiry First Out (FEFO) Approach.

This script:
- Generates ten related CSV datasets.
- Uses a fixed random seed for reproducibility.
- Simulates 24 months of historical demand and stock movements.
- Allocates dispensing transactions using date-aware FEFO.
- Simulates procurement, purchase orders and goods receipts.
- Generates six-month forecast evaluation data.
- Generates November 2026 forward forecasts.
- Produces a generation summary.

It does NOT connect to Django or import data into the database.
"""

from __future__ import annotations

import calendar
import json
import math
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker


# ============================================================
# 1. CONFIGURATION
# ============================================================

SEED = 20261109

random.seed(SEED)
np.random.seed(SEED)

fake = Faker()
Faker.seed(SEED)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = PROJECT_ROOT / "synthetic_dataset_package"
DATASET_DIR = PACKAGE_DIR / "datasets"
REPORT_DIR = PACKAGE_DIR / "reports"

DATASET_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

HISTORY_START = date(2024, 11, 1)
HISTORY_END = date(2026, 10, 31)

SNAPSHOT_DATE = date(2026, 11, 9)
FORWARD_FORECAST_START = date(2026, 11, 1)
FORWARD_FORECAST_END = date(2026, 11, 30)

TRAINING_MONTHS = 18
EVALUATION_MONTHS = 6

PERIOD_DAYS = 30
HISTORY_PERIODS = 3
MAX_PRESCRIPTION_DAYS = 14

MEDICINE_COUNT = 100
SUPPLIER_COUNT = 15

# Fixed historical evaluation origins.
EVALUATION_ORIGINS = [
    date(2026, month, 1)
    for month in range(5, 11)
]

# All generated IDs are external dataset identifiers.
# They are NOT Django primary keys.


# ============================================================
# 2. MEDICINE AND SUPPLIER MASTER DATA
# ============================================================

MEDICINE_CATALOGUE = [
    ("Paracetamol", "Analgesic"),
    ("Ibuprofen", "Analgesic"),
    ("Diclofenac", "Analgesic"),
    ("Amoxicillin", "Antibiotic"),
    ("Azithromycin", "Antibiotic"),
    ("Ciprofloxacin", "Antibiotic"),
    ("Metronidazole", "Antibiotic"),
    ("Doxycycline", "Antibiotic"),
    ("Metformin", "Antidiabetic"),
    ("Glibenclamide", "Antidiabetic"),
    ("Amlodipine", "Cardiovascular"),
    ("Losartan", "Cardiovascular"),
    ("Atenolol", "Cardiovascular"),
    ("Enalapril", "Cardiovascular"),
    ("Hydrochlorothiazide", "Cardiovascular"),
    ("Omeprazole", "Gastrointestinal"),
    ("Ranitidine", "Gastrointestinal"),
    ("Loperamide", "Gastrointestinal"),
    ("Cetirizine", "Antihistamine"),
    ("Loratadine", "Antihistamine"),
    ("Salbutamol", "Respiratory"),
    ("Prednisolone", "Corticosteroid"),
    ("Ferrous Sulphate", "Supplement"),
    ("Folic Acid", "Supplement"),
    ("Vitamin C", "Supplement"),
]

DOSAGE_FORMS = [
    "Tablet",
    "Capsule",
    "Oral Suspension",
    "Injection",
]

STORAGE_LOCATIONS = [
    "Main Store A-01",
    "Main Store A-02",
    "Main Store B-01",
    "Main Store B-02",
    "Pharmacy Shelf P-01",
    "Pharmacy Shelf P-02",
    "Pharmacy Shelf P-03",
    "Cold Storage C-01",
]

def generate_medicines():
    rows = []
    medicine_number = 1

    for generic_name, category in MEDICINE_CATALOGUE:
        for dosage_form in DOSAGE_FORMS:
            if medicine_number > MEDICINE_COUNT:
                break

            medicine_id = f"MED{medicine_number:03d}"
            medicine_name = f"{generic_name} {dosage_form}s"

            rows.append({
                "medicine_id": medicine_id,
                "name": medicine_name,
                "medicine_name": medicine_name,
                "generic_name": generic_name,
                "category": category,
                "dosage_form": dosage_form,
                "reorder_level": random.choice([20, 30, 40, 50]),
                "safety_stock_days": random.choice([15, 30, 45]),
                "is_active": True,
            })

            medicine_number += 1

        if medicine_number > MEDICINE_COUNT:
            break

    return rows


def generate_suppliers():
    rows = []

    for number in range(1, SUPPLIER_COUNT + 1):
        supplier_id = f"SUP{number:03d}"
        supplier_name = f"Fictional {fake.unique.company()} Medical Supplies Ltd"

        phone_number = f"+2547{random.randint(10000000, 99999999)}"

        rows.append({
            "supplier_id": supplier_id,
            "supplier_name": supplier_name,
            "name": supplier_name,
            "contact_person": fake.name(),
            "email": f"supplier{number:02d}@example.test",
            "phone_number": phone_number,
            "phone": phone_number,
            "address": f"Fictional Business Centre, Nairobi, Kenya",
            "is_active": True,
        })

    return rows


# ============================================================
# 3. GENERAL HELPERS
# ============================================================

def iso_date(value: date) -> str:
    return value.isoformat()


def iso_datetime(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def round_half_up(value) -> int:
    return int(
        Decimal(str(value)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP
        )
    )


def month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def next_month_start(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def month_end(value: date) -> date:
    last_day = calendar.monthrange(value.year, value.month)[1]
    return date(value.year, value.month, last_day)


def datetime_at(value: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(value, time(hour, minute))


def write_csv(filename: str, rows: list[dict], columns: list[str]):
    path = DATASET_DIR / filename
    dataframe = pd.DataFrame(rows, columns=columns)
    dataframe.to_csv(path, index=False, encoding="utf-8")
    return dataframe


# ============================================================
# 4. DEMAND GENERATION
# ============================================================

def generate_medicine_demand(medicine):
    """
    Generate monthly demand for one medicine.

    Demand is synthetic and does not represent actual hospital
    consumption or clinical prescribing guidance.
    """

    baseline = random.randint(15, 140)
    monthly_demand = {}

    for month_index in range(24):
        current_month = (
            date(2024, 11, 1)
            + timedelta(days=month_index * 30)
        )

        # Use actual calendar month boundaries.
        year = current_month.year
        month = current_month.month
        start = date(year, month, 1)
        end = month_end(start)

        days = (end - start).days + 1

        # Mild seasonal variation, deliberately not extreme.
        seasonal_factor = 1.0

        if month in [3, 4, 5]:
            seasonal_factor = 1.08
        elif month in [11, 12]:
            seasonal_factor = 1.05

        noise = random.uniform(0.82, 1.18)

        demand = round_half_up(
            baseline * (days / 30) * seasonal_factor * noise
        )

        monthly_demand[(year, month)] = max(0, demand)

    return monthly_demand


# ============================================================
# 5. INVENTORY AND FEFO SIMULATION
# ============================================================

def eligible_stock(batches, medicine_id, required_valid_until):
    return sum(
        batch["quantity_available"]
        for batch in batches
        if batch["medicine_id"] == medicine_id
        and batch["status"] == "Active"
        and batch["quantity_available"] > 0
        and date.fromisoformat(batch["expiry_date"]) >= required_valid_until
    )


def eligible_batches(batches, medicine_id, dispensing_date, duration):
    required_valid_until = (
        dispensing_date + timedelta(days=duration - 1)
    )

    candidates = [
        batch for batch in batches
        if batch["medicine_id"] == medicine_id
        and batch["status"] == "Active"
        and batch["quantity_available"] > 0
        and date.fromisoformat(batch["expiry_date"]) >= required_valid_until
    ]

    return sorted(
        candidates,
        key=lambda batch: (
            batch["expiry_date"],
            batch["batch_id"]
        )
    )


def allocate_fefo(
    batches,
    medicine_id,
    dispensing_date,
    quantity,
    duration,
    patient_identifier,
    timestamp,
    transaction_rows,
    transaction_counter,
):
    """
    Allocate a dispensing event across one or more batches.

    Each transaction row references exactly one batch.
    If a dispensing event spans multiple batches, it is split
    into multiple rows with the same patient identifier and time.

    A small number of documented overrides select a later
    eligible batch. Expiry and prescription-validity checks
    are never bypassed.
    """

    candidates = eligible_batches(
        batches,
        medicine_id,
        dispensing_date,
        duration
    )

    available = sum(
        batch["quantity_available"]
        for batch in candidates
    )

    if available < quantity:
        raise RuntimeError(
            f"Stock shortfall for {medicine_id} on {dispensing_date}. "
            f"Required={quantity}, eligible={available}"
        )

    remaining = quantity
    first_row = True

    # Rare controlled override: choose a later eligible batch.
    use_override = (
        len(candidates) > 1
        and random.random() < 0.005
    )

    allocation_order = list(candidates)

    if use_override:
        allocation_order = [candidates[1]] + [
            batch for batch in candidates
            if batch["batch_id"] != candidates[1]["batch_id"]
        ]

    for batch in allocation_order:
        if remaining <= 0:
            break

        allocated = min(
            remaining,
            batch["quantity_available"]
        )

        if allocated <= 0:
            continue

        batch["quantity_available"] -= allocated

        if batch["quantity_available"] == 0:
            batch["status"] = "Depleted"

        is_override = use_override and first_row

        if is_override:
            notes = (
                "Synthetic documented operational override. "
                f"Prescription duration: {duration} days."
            )
        else:
            notes = (
                f"Synthetic dispensing record. "
                f"Prescription duration: {duration} days."
            )

        transaction_counter += 1

        transaction_rows.append({
            "transaction_id": f"TXN{transaction_counter:07d}",
            "medicine_id": medicine_id,
            "batch_id": batch["batch_id"],
            "quantity_dispensed": allocated,
            "dispensed_date": iso_datetime(timestamp),
            "dispensed_at": iso_datetime(timestamp),
            "is_override": is_override,
            "patient_identifier": patient_identifier,
            "notes": notes,
        })

        remaining -= allocated
        first_row = False

    if remaining != 0:
        raise RuntimeError(
            f"FEFO allocation did not complete for {medicine_id}"
        )

    return transaction_counter


# ============================================================
# 6. PROCUREMENT AND RECEIVING SIMULATION
# ============================================================

def add_replenishment(
    medicine,
    quantity,
    order_date,
    delivery_date,
    medicines_batches,
    recommendations,
    purchase_orders,
    goods_receipts,
    goods_receipt_items,
    counters,
    suppliers,
):
    """
    Create a complete historical replenishment chain:

    ProcurementRecommendation
        -> PurchaseOrder
        -> GoodsReceipt
        -> GoodsReceiptItem
        -> MedicineBatch
    """

    medicine_id = medicine["medicine_id"]

    counters["recommendation"] += 1
    counters["purchase_order"] += 1
    counters["goods_receipt"] += 1
    counters["receipt_item"] += 1
    counters["batch"] += 1

    recommendation_id = f"REC{counters['recommendation']:06d}"
    purchase_order_id = f"PO{counters['purchase_order']:06d}"
    receipt_id = f"GR{counters['goods_receipt']:06d}"
    receipt_item_id = f"GRI{counters['receipt_item']:06d}"
    batch_id = f"BAT{counters['batch']:06d}"

    supplier = random.choice(suppliers)

    unit_cost = Decimal(str(round(random.uniform(8, 900), 2)))
    total_cost = (unit_cost * quantity).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )

    expiry_date = delivery_date + timedelta(
        days=random.randint(540, 900)
    )

    urgency = "HIGH" if quantity > 100 else "MEDIUM"

    recommendations.append({
        "recommendation_id": recommendation_id,
        "medicine_id": medicine_id,
        "forecast_id": "",
        "recommended_quantity": quantity,
        "urgency_level": urgency,
        "reasoning": (
            "Synthetic replenishment generated to maintain "
            "eligible stock coverage for historical demand."
        ),
        "status": "Actioned",
        "is_actioned": True,
        "created_at": iso_datetime(datetime_at(order_date, 9)),
        "updated_at": iso_datetime(datetime_at(delivery_date, 10)),
    })

    purchase_orders.append({
        "purchase_order_id": purchase_order_id,
        "medicine_id": medicine_id,
        "supplier_id": supplier["supplier_id"],
        "recommendation_id": recommendation_id,
        "quantity_ordered": quantity,
        "total_amount": str(total_cost),
        "total_cost": str(total_cost),
        "order_date": iso_datetime(datetime_at(order_date, 9)),
        "status": "Placed with Supplier",
    })

    goods_receipts.append({
        "goods_receipt_id": receipt_id,
        "purchase_order_id": purchase_order_id,
        "delivery_date": iso_date(delivery_date),
        "received_at": iso_datetime(datetime_at(delivery_date, 10)),
        "delivery_reference": f"DEL-{receipt_id}",
        "notes": "Synthetic historical goods receipt.",
    })

    batch = {
        "batch_id": batch_id,
        "medicine_id": medicine_id,
        "batch_number": (
            f"{medicine_id}-{delivery_date.strftime('%Y%m%d')}-"
            f"{counters['batch']:04d}"
        ),
        "quantity_received": quantity,
        "quantity_available": quantity,
        "received_date": iso_date(delivery_date),
        "expiry_date": iso_date(expiry_date),
        "storage_location": random.choice(STORAGE_LOCATIONS),
        "status": "Active",
    }

    medicines_batches.append(batch)

    goods_receipt_items.append({
        "receipt_item_id": receipt_item_id,
        "goods_receipt_id": receipt_id,
        "medicine_batch_id": batch_id,
        "batch_number": batch["batch_number"],
        "quantity_received": quantity,
        "expiry_date": iso_date(expiry_date),
        "storage_location": batch["storage_location"],
        "inspection_status": "Accepted",
        "inspected_at": iso_datetime(
            datetime_at(delivery_date, 11)
        ),
        "inspection_notes": (
            "Synthetic inspection record; accepted for inventory."
        ),
    })


# ============================================================
# 7. HISTORICAL STOCK AND DISPENSING GENERATION
# ============================================================

def generate_historical_operations(medicines, suppliers):
    batches = []
    transactions = []
    recommendations = []
    purchase_orders = []
    goods_receipts = []
    goods_receipt_items = []

    counters = {
        "recommendation": 0,
        "purchase_order": 0,
        "goods_receipt": 0,
        "receipt_item": 0,
        "batch": 0,
        "transaction": 0,
    }

    demand_by_medicine = {}

    # Initial stock received before the historical period.
    for medicine in medicines:
        medicine_id = medicine["medicine_id"]
        demand = generate_medicine_demand(medicine)
        demand_by_medicine[medicine_id] = demand

        initial_batch_quantity = max(
            20,
            round_half_up(
                np.mean(list(demand.values())) * 1.5
            )
        )

        counters["batch"] += 1
        initial_batch_id = f"BAT{counters['batch']:06d}"

        initial_expiry = date(
            2026,
            random.choice([6, 7, 8, 9, 10, 11, 12]),
            random.choice([10, 15, 20, 25])
        )

        batches.append({
            "batch_id": initial_batch_id,
            "medicine_id": medicine_id,
            "batch_number": f"{medicine_id}-INITIAL-001",
            "quantity_received": initial_batch_quantity,
            "quantity_available": initial_batch_quantity,
            "received_date": "2024-10-15",
            "expiry_date": iso_date(initial_expiry),
            "storage_location": random.choice(STORAGE_LOCATIONS),
            "status": "Active",
        })

    # Simulate monthly dispensing from November 2024 to October 2026.
    transaction_counter = 0

    for medicine in medicines:
        medicine_id = medicine["medicine_id"]
        demand = demand_by_medicine[medicine_id]

        for year in [2024, 2025, 2026]:
            months = (
                range(11, 13) if year == 2024
                else range(1, 13) if year == 2025
                else range(1, 11)
            )

            for month in months:
                start = date(year, month, 1)
                end = month_end(start)
                total_demand = demand[(year, month)]

                # Maintain stock that remains valid through the
                # end of the month plus the maximum prescription period.
                required_valid_until = (
                    end + timedelta(days=MAX_PRESCRIPTION_DAYS - 1)
                )

                stock = eligible_stock(
                    batches,
                    medicine_id,
                    required_valid_until
                )

                reserve = max(
                    10,
                    round_half_up(
                        np.mean(list(demand.values()))
                    )
                )

                target_stock = total_demand + reserve
                shortfall = max(0, target_stock - stock)

                if shortfall > 0:
                    order_date = start - timedelta(days=10)
                    delivery_date = start - timedelta(days=3)

                    add_replenishment(
                        medicine=medicine,
                        quantity=shortfall,
                        order_date=order_date,
                        delivery_date=delivery_date,
                        medicines_batches=batches,
                        recommendations=recommendations,
                        purchase_orders=purchase_orders,
                        goods_receipts=goods_receipts,
                        goods_receipt_items=goods_receipt_items,
                        counters=counters,
                        suppliers=suppliers,
                    )

                if total_demand == 0:
                    continue

                transaction_count = min(
                    total_demand,
                    max(1, round(total_demand / 5))
                )

                quantities = np.random.multinomial(
                    total_demand,
                    np.ones(transaction_count) / transaction_count
                )

                events = []

                for quantity in quantities:
                    if quantity <= 0:
                        continue

                    day_offset = random.randint(
                        0,
                        (end - start).days
                    )

                    dispensing_date = start + timedelta(days=day_offset)
                    duration = random.randint(
                        1,
                        MAX_PRESCRIPTION_DAYS
                    )

                    hour = random.randint(8, 16)
                    minute = random.randint(0, 59)

                    timestamp = datetime_at(
                        dispensing_date,
                        hour,
                        minute
                    )

                    events.append({
                        "date": dispensing_date,
                        "timestamp": timestamp,
                        "quantity": int(quantity),
                        "duration": duration,
                    })

                events.sort(key=lambda event: event["timestamp"])

                for event in events:
                    transaction_counter = allocate_fefo(
                        batches=batches,
                        medicine_id=medicine_id,
                        dispensing_date=event["date"],
                        quantity=event["quantity"],
                        duration=event["duration"],
                        patient_identifier=(
                            f"PAT{transaction_counter + 1:07d}"
                        ),
                        timestamp=event["timestamp"],
                        transaction_rows=transactions,
                        transaction_counter=transaction_counter,
                    )

    counters["transaction"] = transaction_counter

    return {
        "batches": batches,
        "transactions": transactions,
        "recommendations": recommendations,
        "purchase_orders": purchase_orders,
        "goods_receipts": goods_receipts,
        "goods_receipt_items": goods_receipt_items,
        "demand_by_medicine": demand_by_medicine,
        "counters": counters,
    }


# ============================================================
# 8. FORECASTING
# ============================================================

def transaction_period_totals(
    transactions,
    medicine_id,
    period_start,
    period_end
):
    """
    Half-open date interval:
    period_start <= dispensed_at < period_end
    """

    total_quantity = 0
    transaction_count = 0

    for transaction in transactions:
        if transaction["medicine_id"] != medicine_id:
            continue

        timestamp = datetime.fromisoformat(
            transaction["dispensed_at"]
        )

        if (
            datetime.combine(period_start, time.min)
            <= timestamp
            < datetime.combine(period_end, time.min)
        ):
            total_quantity += int(
                transaction["quantity_dispensed"]
            )
            transaction_count += 1

    return total_quantity, transaction_count


def calculate_forecast(
    transactions,
    medicine_id,
    origin
):
    period_volumes = []
    transaction_counts = []

    history_start = origin - timedelta(
        days=PERIOD_DAYS * HISTORY_PERIODS
    )

    for period_number in range(HISTORY_PERIODS):
        start = history_start + timedelta(
            days=period_number * PERIOD_DAYS
        )
        end = start + timedelta(days=PERIOD_DAYS)

        quantity, count = transaction_period_totals(
            transactions,
            medicine_id,
            start,
            end
        )

        period_volumes.append(quantity)
        transaction_counts.append(count)

    moving_average = round_half_up(
        sum(period_volumes) / HISTORY_PERIODS
    )

    highest = max(period_volumes)
    lowest = min(period_volumes)

    if highest == 0:
        consistency_score = Decimal("0.00")
    else:
        score = Decimal("100") * (
            Decimal("1")
            - Decimal(highest - lowest) / Decimal(highest)
        )

        score = max(Decimal("0"), min(Decimal("100"), score))

        consistency_score = score.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

    return {
        "history_start_date": history_start,
        "history_end_date": origin,
        "period_volumes": period_volumes,
        "moving_average": moving_average,
        "transaction_count": sum(transaction_counts),
        "confidence_score": str(consistency_score),
    }


def generate_forecasts(medicines, transactions):
    evaluation_rows = []
    november_rows = []

    evaluation_actuals = {}

    forecast_counter = 0

    # Six rolling-origin evaluation periods.
    for origin in EVALUATION_ORIGINS:
        actual_start = origin
        actual_end = next_month_start(origin)

        for medicine in medicines:
            medicine_id = medicine["medicine_id"]

            result = calculate_forecast(
                transactions,
                medicine_id,
                origin
            )

            actual_quantity, _ = transaction_period_totals(
                transactions,
                medicine_id,
                actual_start,
                actual_end
            )

            forecast_counter += 1
            forecasted = result["moving_average"]

            evaluation_rows.append({
                "forecast_id": f"FCE{forecast_counter:06d}",
                "medicine_id": medicine_id,
                "forecast_period_start": iso_date(origin),
                "forecast_period_end": iso_date(
                    actual_end - timedelta(days=1)
                ),
                "forecasted_demand_quantity": forecasted,
                "moving_avg_3month": forecasted,
                "forecast_method": "MOVING_AVERAGE",
                "history_start_date": iso_date(
                    result["history_start_date"]
                ),
                "history_end_date": iso_date(
                    result["history_end_date"]
                ),
                "historical_transaction_count": (
                    result["transaction_count"]
                ),
                "confidence_score": result["confidence_score"],
                "actual_demand_quantity": actual_quantity,
                "absolute_error": abs(forecasted - actual_quantity),
                "generated_at": iso_datetime(
                    datetime_at(origin, 8)
                ),
            })

            days_in_month = (
                actual_end - actual_start
            ).days

            normalized_actual = (
                actual_quantity * PERIOD_DAYS / days_in_month
            )

            evaluation_actuals[
                (medicine_id, origin)
            ] = {
                "forecast": forecasted,
                "actual": actual_quantity,
                "normalized_actual": normalized_actual,
            }

    # November forward forecasts.
    # Origin is 1 November; the history window is the preceding
    # 90 days, ending at the beginning of 1 November.
    forward_origin = FORWARD_FORECAST_START

    for medicine in medicines:
        medicine_id = medicine["medicine_id"]

        result = calculate_forecast(
            transactions,
            medicine_id,
            forward_origin
        )

        forecast_counter += 1

        november_rows.append({
            "forecast_id": f"FCN{forecast_counter:06d}",
            "medicine_id": medicine_id,
            "forecast_period_start": iso_date(
                FORWARD_FORECAST_START
            ),
            "forecast_period_end": iso_date(
                FORWARD_FORECAST_END
            ),
            "forecasted_demand_quantity": (
                result["moving_average"]
            ),
            "moving_avg_3month": result["moving_average"],
            "forecast_method": "MOVING_AVERAGE",
            "history_start_date": iso_date(
                result["history_start_date"]
            ),
            "history_end_date": iso_date(
                result["history_end_date"]
            ),
            "historical_transaction_count": (
                result["transaction_count"]
            ),
            "confidence_score": result["confidence_score"],
            "actual_demand_quantity": "",
            "absolute_error": "",
            "generated_at": iso_datetime(
                datetime_at(SNAPSHOT_DATE, 9)
            ),
        })

    return evaluation_rows, november_rows, evaluation_actuals


# ============================================================
# 9. NOVEMBER PROCUREMENT RECOMMENDATIONS AND PURCHASE ORDERS
# ============================================================

def generate_november_procurement(
    medicines,
    batches,
    november_forecasts,
    recommendations,
    purchase_orders,
    suppliers,
    counters,
):
    forecast_by_medicine = {
        row["medicine_id"]: row
        for row in november_forecasts
    }

    for medicine in medicines:
        medicine_id = medicine["medicine_id"]
        forecast = forecast_by_medicine[medicine_id]

        eligible = sum(
            batch["quantity_available"]
            for batch in batches
            if batch["medicine_id"] == medicine_id
            and batch["status"] == "Active"
            and batch["quantity_available"] > 0
            and date.fromisoformat(batch["expiry_date"])
                > SNAPSHOT_DATE
        )

        moving_average = int(
            forecast["forecasted_demand_quantity"]
        )

        target_stock = round_half_up(
            moving_average
            * (30 + int(medicine["safety_stock_days"]))
            / 30
        )

        recommended_quantity = max(
            0,
            target_stock - eligible
        )

        if recommended_quantity <= 0:
            continue

        urgency = (
            "HIGH"
            if moving_average > 0
            and eligible <= moving_average / 2
            else "MEDIUM"
        )

        counters["recommendation"] += 1
        recommendation_id = (
            f"REC{counters['recommendation']:06d}"
        )

        # Default recommendation state: Pending.
        recommendation_status = "Pending"
        is_actioned = False

        recommendations.append({
            "recommendation_id": recommendation_id,
            "medicine_id": medicine_id,
            "forecast_id": forecast["forecast_id"],
            "recommended_quantity": recommended_quantity,
            "urgency_level": urgency,
            "reasoning": (
                "November 2026 moving-average forecast indicates "
                "a projected stock shortfall against target stock."
            ),
            "status": recommendation_status,
            "is_actioned": is_actioned,
            "created_at": iso_datetime(
                datetime_at(SNAPSHOT_DATE, 9)
            ),
            "updated_at": iso_datetime(
                datetime_at(SNAPSHOT_DATE, 9)
            ),
        })

        # Only a subset of recommendations proceeds to a PO.
        if random.random() > 0.45:
            continue

        counters["purchase_order"] += 1
        purchase_order_id = (
            f"PO{counters['purchase_order']:06d}"
        )

        supplier = random.choice(suppliers)

        po_status = random.choices(
            [
                "Pending Admin Review",
                "Rejected",
                "Approved",
                "Placed with Supplier",
            ],
            weights=[40, 15, 20, 25],
            k=1
        )[0]

        if po_status == "Rejected":
            recommendation_status = "Rejected"
            is_actioned = False
        elif po_status in ["Approved", "Placed with Supplier"]:
            recommendation_status = "Actioned"
            is_actioned = True
        else:
            recommendation_status = "Pending"
            is_actioned = False

        recommendations[-1]["status"] = recommendation_status
        recommendations[-1]["is_actioned"] = is_actioned

        unit_cost = Decimal(
            str(round(random.uniform(8, 900), 2))
        )

        total_cost = (
            unit_cost * recommended_quantity
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        purchase_orders.append({
            "purchase_order_id": purchase_order_id,
            "medicine_id": medicine_id,
            "supplier_id": supplier["supplier_id"],
            "recommendation_id": recommendation_id,
            "quantity_ordered": recommended_quantity,
            "total_amount": str(total_cost),
            "total_cost": str(total_cost),
            "order_date": iso_datetime(
                datetime_at(SNAPSHOT_DATE, 10)
            ),
            "status": po_status,
        })


# ============================================================
# 10. EVALUATION METRICS
# ============================================================

def calculate_evaluation_metrics(evaluation_actuals):
    errors = []
    absolute_actuals = []
    percentage_errors = []

    for values in evaluation_actuals.values():
        forecast = values["forecast"]
        actual_30_day = values["normalized_actual"]

        error = abs(forecast - actual_30_day)

        errors.append(error)
        absolute_actuals.append(actual_30_day)

        if actual_30_day > 0:
            percentage_errors.append(
                error / actual_30_day * 100
            )

    mae = float(np.mean(errors)) if errors else 0.0

    total_actual = sum(absolute_actuals)
    total_absolute_error = sum(errors)

    wape = (
        total_absolute_error / total_actual * 100
        if total_actual > 0 else 0.0
    )

    mape = (
        float(np.mean(percentage_errors))
        if percentage_errors else None
    )

    return {
        "MAE_30_day_equivalent": round(mae, 2),
        "WAPE_percent": round(wape, 2),
        "MAPE_percent": (
            round(mape, 2) if mape is not None else None
        ),
        "MAPE_note": (
            "MAPE excludes observations with zero actual demand."
        ),
        "normalization_note": (
            "Calendar-month actual demand is converted to a "
            "30-day equivalent for evaluation metrics. The CSV "
            "retains raw calendar-month actual demand."
        ),
    }


# ============================================================
# 11. DATASET EXPORT
# ============================================================

def export_all_datasets(
    medicines,
    suppliers,
    operations,
    evaluation_forecasts,
    november_forecasts,
):
    write_csv(
        "medicines.csv",
        medicines,
        [
            "medicine_id", "name", "medicine_name", "generic_name",
            "category", "dosage_form", "reorder_level",
            "safety_stock_days", "is_active"
        ]
    )

    write_csv(
        "suppliers.csv",
        suppliers,
        [
            "supplier_id", "supplier_name", "name", "contact_person",
            "email", "phone_number", "phone", "address", "is_active"
        ]
    )

    write_csv(
        "medicine_batches.csv",
        operations["batches"],
        [
            "batch_id", "medicine_id", "batch_number",
            "quantity_received", "quantity_available",
            "received_date", "expiry_date", "storage_location",
            "status"
        ]
    )

    write_csv(
        "dispensing_transactions.csv",
        operations["transactions"],
        [
            "transaction_id", "medicine_id", "batch_id",
            "quantity_dispensed", "dispensed_date", "dispensed_at",
            "is_override", "patient_identifier", "notes"
        ]
    )

    forecast_columns = [
        "forecast_id", "medicine_id", "forecast_period_start",
        "forecast_period_end", "forecasted_demand_quantity",
        "moving_avg_3month", "forecast_method",
        "history_start_date", "history_end_date",
        "historical_transaction_count", "confidence_score",
        "actual_demand_quantity", "absolute_error", "generated_at"
    ]

    write_csv(
        "demand_forecasts_evaluation.csv",
        evaluation_forecasts,
        forecast_columns
    )

    write_csv(
        "demand_forecasts_november_2026.csv",
        november_forecasts,
        forecast_columns
    )

    write_csv(
        "procurement_recommendations.csv",
        operations["recommendations"],
        [
            "recommendation_id", "medicine_id", "forecast_id",
            "recommended_quantity", "urgency_level", "reasoning",
            "status", "is_actioned", "created_at", "updated_at"
        ]
    )

    write_csv(
        "purchase_orders.csv",
        operations["purchase_orders"],
        [
            "purchase_order_id", "medicine_id", "supplier_id",
            "recommendation_id", "quantity_ordered",
            "total_amount", "total_cost", "order_date", "status"
        ]
    )

    write_csv(
        "goods_receipts.csv",
        operations["goods_receipts"],
        [
            "goods_receipt_id", "purchase_order_id", "delivery_date",
            "received_at", "delivery_reference", "notes"
        ]
    )

    write_csv(
        "goods_receipt_items.csv",
        operations["goods_receipt_items"],
        [
            "receipt_item_id", "goods_receipt_id",
            "medicine_batch_id", "batch_number",
            "quantity_received", "expiry_date", "storage_location",
            "inspection_status", "inspected_at", "inspection_notes"
        ]
    )


# ============================================================
# 12. GENERATION SUMMARY
# ============================================================

def generate_summary(
    operations,
    evaluation_forecasts,
    november_forecasts,
    metrics,
):
    datasets = {
        "medicines.csv": MEDICINE_COUNT,
        "suppliers.csv": SUPPLIER_COUNT,
        "medicine_batches.csv": len(operations["batches"]),
        "dispensing_transactions.csv": len(operations["transactions"]),
        "demand_forecasts_evaluation.csv": len(evaluation_forecasts),
        "demand_forecasts_november_2026.csv": len(november_forecasts),
        "procurement_recommendations.csv": len(
            operations["recommendations"]
        ),
        "purchase_orders.csv": len(operations["purchase_orders"]),
        "goods_receipts.csv": len(operations["goods_receipts"]),
        "goods_receipt_items.csv": len(
            operations["goods_receipt_items"]
        ),
    }

    summary = {
        "project": (
            "Demand-Driven Medicine Expiry Management System "
            "using FEFO"
        ),
        "random_seed": SEED,
        "historical_start": iso_date(HISTORY_START),
        "historical_end": iso_date(HISTORY_END),
        "snapshot_date": iso_date(SNAPSHOT_DATE),
        "forecast_period": (
            f"{iso_date(FORWARD_FORECAST_START)} to "
            f"{iso_date(FORWARD_FORECAST_END)}"
        ),
        "training_period_months": TRAINING_MONTHS,
        "evaluation_period_months": EVALUATION_MONTHS,
        "dataset_record_counts": datasets,
        "forecast_evaluation_metrics": metrics,
        "generation_restrictions": [
            "No connection to Django database was made.",
            "No records were imported into Django.",
            "All supplier and patient identifiers are synthetic.",
            "Synthetic costs are illustrative and not market quotations.",
            "Forecast consistency score is not a probability.",
            "Historical actual demand is retained as calendar-month demand.",
        ],
    }

    json_path = REPORT_DIR / "generation_summary.json"
    text_path = REPORT_DIR / "generation_summary.txt"

    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(summary, file, indent=4)

    lines = [
        "SYNTHETIC DATASET GENERATION SUMMARY",
        "=" * 48,
        f"Random seed: {SEED}",
        f"Historical period: {HISTORY_START} to {HISTORY_END}",
        f"Inventory snapshot: {SNAPSHOT_DATE}",
        (
            "Forward forecast: "
            f"{FORWARD_FORECAST_START} to {FORWARD_FORECAST_END}"
        ),
        "",
        "DATASET RECORD COUNTS",
        "-" * 48,
    ]

    for filename, count in datasets.items():
        lines.append(f"{filename}: {count:,}")

    lines.extend([
        "",
        "FORECAST EVALUATION",
        "-" * 48,
        f"30-day equivalent MAE: {metrics['MAE_30_day_equivalent']}",
        f"WAPE: {metrics['WAPE_percent']}%",
        f"MAPE: {metrics['MAPE_percent']}",
        metrics["MAPE_note"],
        metrics["normalization_note"],
        "",
        "IMPORTANT",
        "-" * 48,
        "This generation run did not connect to Django.",
        "No records were imported into the application database.",
        "All CSV files must undergo independent cleaning and validation.",
        "The generated files are for inspection only.",
    ])

    with open(text_path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines))

    print("\n".join(lines))


# ============================================================
# 13. MAIN
# ============================================================

def main():
    print("Starting synthetic dataset generation...")
    print(f"Random seed: {SEED}")

    medicines = generate_medicines()
    suppliers = generate_suppliers()

    print(f"Generated {len(medicines)} medicines.")
    print(f"Generated {len(suppliers)} suppliers.")

    operations = generate_historical_operations(
        medicines,
        suppliers
    )

    print(
        "Historical dispensing transactions generated: "
        f"{len(operations['transactions']):,}"
    )

    evaluation_forecasts, november_forecasts, evaluation_actuals = (
        generate_forecasts(
            medicines,
            operations["transactions"]
        )
    )

    generate_november_procurement(
        medicines=medicines,
        batches=operations["batches"],
        november_forecasts=november_forecasts,
        recommendations=operations["recommendations"],
        purchase_orders=operations["purchase_orders"],
        suppliers=suppliers,
        counters=operations["counters"],
    )

    metrics = calculate_evaluation_metrics(
        evaluation_actuals
    )

    export_all_datasets(
        medicines=medicines,
        suppliers=suppliers,
        operations=operations,
        evaluation_forecasts=evaluation_forecasts,
        november_forecasts=november_forecasts,
    )

    generate_summary(
        operations=operations,
        evaluation_forecasts=evaluation_forecasts,
        november_forecasts=november_forecasts,
        metrics=metrics,
    )

    print("\nGeneration completed.")
    print(f"Datasets: {DATASET_DIR}")
    print(f"Summary: {REPORT_DIR}")


if __name__ == "__main__":
    main()
