"""
Synthetic dataset generator
Project: Web-Based Demand-Driven Medicine Expiry Management System
         using the First Expiry First Out (FEFO) Approach.

Generates ten related CSV datasets and generation reports.

Historical period:
    1 November 2024 – 31 October 2026

Forecast evaluation:
    May – October 2026 (six rolling-origin periods)

Forward forecast:
    1 – 30 November 2026

Inventory snapshot:
    9 November 2026

Important:
    - Uses synthetic data only.
    - Does not connect to Django.
    - Does not import records into the application database.
    - Uses external dataset IDs, not Django primary keys.
    - Uses a fixed random seed for reproducibility.
"""

from __future__ import annotations
import calendar
import json
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

# The 18-month historical reference period is November 2024
# through April 2026. It is not an 18-month fitted model window.
REFERENCE_PERIOD_MONTHS = 18
REFERENCE_PERIOD_START = date(2024, 11, 1)
REFERENCE_PERIOD_END = date(2026, 4, 30)

EVALUATION_MONTHS = 6

PERIOD_DAYS = 30
HISTORY_PERIODS = 3
MAX_PRESCRIPTION_DAYS = 14

MEDICINE_COUNT = 100
SUPPLIER_COUNT = 15

OVERRIDE_PROBABILITY = 0.005

EVALUATION_ORIGINS = [
    date(2026, month, 1)
    for month in range(5, 11)
]

# The generator uses external identifiers.
# These are not Django primary keys.


# ============================================================
# 2. MASTER DATA
# ============================================================
# Each medicine has explicitly assigned dosage forms.
# These are synthetic medicine presentations, not a clinical formulary.

MEDICINE_CATALOGUE = [
    ("Paracetamol", "Analgesic", ["Tablet", "Oral Suspension"]),
    ("Ibuprofen", "Analgesic", ["Tablet", "Oral Suspension"]),
    ("Diclofenac", "Analgesic", ["Tablet", "Injection"]),
    ("Tramadol", "Analgesic", ["Capsule", "Injection"]),
    ("Aspirin", "Analgesic", ["Tablet", "Oral Suspension"]),

    ("Amoxicillin", "Antibiotic", ["Capsule", "Oral Suspension"]),
    ("Azithromycin", "Antibiotic", ["Tablet", "Oral Suspension"]),
    ("Ciprofloxacin", "Antibiotic", ["Tablet", "Injection"]),
    ("Metronidazole", "Antibiotic", ["Tablet", "Injection"]),
    ("Doxycycline", "Antibiotic", ["Capsule", "Tablet"]),
    ("Ceftriaxone", "Antibiotic", ["Injection", "Powder for Injection"]),
    ("Cefuroxime", "Antibiotic", ["Tablet", "Injection"]),
    ("Flucloxacillin", "Antibiotic", ["Capsule", "Oral Suspension"]),
    ("Benzylpenicillin", "Antibiotic", ["Injection", "Powder for Injection"]),
    ("Gentamicin", "Antibiotic", ["Injection", "Eye Drops"]),

    ("Metformin", "Antidiabetic", ["Tablet", "Oral Solution"]),
    ("Glibenclamide", "Antidiabetic", ["Tablet", "Oral Suspension"]),
    ("Insulin", "Antidiabetic", ["Injection", "Cartridge"]),
    ("Gliclazide", "Antidiabetic", ["Tablet", "Modified Release Tablet"]),

    ("Amlodipine", "Cardiovascular", ["Tablet", "Oral Suspension"]),
    ("Losartan", "Cardiovascular", ["Tablet", "Oral Suspension"]),
    ("Atenolol", "Cardiovascular", ["Tablet", "Oral Solution"]),
    ("Enalapril", "Cardiovascular", ["Tablet", "Oral Solution"]),
    ("Hydrochlorothiazide", "Cardiovascular", ["Tablet", "Oral Solution"]),
    ("Furosemide", "Cardiovascular", ["Tablet", "Injection"]),
    ("Nifedipine", "Cardiovascular", ["Tablet", "Modified Release Tablet"]),
    ("Propranolol", "Cardiovascular", ["Tablet", "Oral Solution"]),
    ("Captopril", "Cardiovascular", ["Tablet", "Oral Solution"]),

    ("Omeprazole", "Gastrointestinal", ["Capsule", "Injection"]),
    ("Loperamide", "Gastrointestinal", ["Capsule", "Oral Solution"]),
    ("Lansoprazole", "Gastrointestinal", ["Capsule", "Oral Suspension"]),
    ("Ondansetron", "Gastrointestinal", ["Tablet", "Injection"]),
    ("Domperidone", "Gastrointestinal", ["Tablet", "Oral Suspension"]),
    ("Oral Rehydration Salts", "Gastrointestinal", ["Powder", "Oral Solution"]),

    ("Cetirizine", "Antihistamine", ["Tablet", "Oral Solution"]),
    ("Loratadine", "Antihistamine", ["Tablet", "Oral Solution"]),
    ("Chlorpheniramine", "Antihistamine", ["Tablet", "Injection"]),

    ("Salbutamol", "Respiratory", ["Inhaler", "Nebuliser Solution"]),
    ("Beclometasone", "Respiratory", ["Inhaler", "Nasal Spray"]),
    ("Aminophylline", "Respiratory", ["Tablet", "Injection"]),
    ("Budesonide", "Respiratory", ["Inhaler", "Nebuliser Suspension"]),

    ("Prednisolone", "Corticosteroid", ["Tablet", "Oral Solution"]),
    ("Dexamethasone", "Corticosteroid", ["Tablet", "Injection"]),
    ("Hydrocortisone", "Corticosteroid", ["Injection", "Cream"]),

    ("Ferrous Sulphate", "Supplement", ["Tablet", "Oral Solution"]),
    ("Folic Acid", "Supplement", ["Tablet", "Oral Solution"]),
    ("Vitamin C", "Supplement", ["Tablet", "Oral Drops"]),
    ("Calcium Carbonate", "Supplement", ["Tablet", "Oral Suspension"]),
    ("Zinc Sulphate", "Supplement", ["Tablet", "Oral Solution"]),
    ("Vitamin B Complex", "Supplement", ["Tablet", "Injection"]),
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

def generate_medicines() -> list[dict]:
    rows = []
    medicine_number = 1

    for generic_name, category, dosage_forms in MEDICINE_CATALOGUE:
        for dosage_form in dosage_forms:
            if medicine_number > MEDICINE_COUNT:
                break

            medicine_id = f"MED{medicine_number:03d}"

            medicine_name = f"{generic_name} {dosage_form}"

            rows.append({
                "medicine_id": medicine_id,
                "medicine_name": medicine_name,
                "generic_name": generic_name,
                "category": category,
                "dosage_form": dosage_form,
                "reorder_level": random.choice([20, 30, 40, 50]),
                "safety_stock_days": random.choice([15, 30, 45]),
                "is_active": True,
            })

            medicine_number += 1

    if len(rows) != MEDICINE_COUNT:
        raise RuntimeError(
            f"Expected {MEDICINE_COUNT} medicines; generated {len(rows)}."
        )

    if len({
        (row["generic_name"], row["dosage_form"])
        for row in rows
    }) != MEDICINE_COUNT:
        raise RuntimeError(
            "Duplicate generic medicine and dosage-form combinations."
        )

    return rows

def generate_suppliers() -> list[dict]:
    rows = []

    for number in range(1, SUPPLIER_COUNT + 1):
        supplier_id = f"SUP{number:03d}"

        supplier_name = (
            f"Fictional {fake.unique.company()} Medical Supplies Ltd"
        )

        phone_number = (
            f"+2547{random.randint(10000000, 99999999)}"
        )

        rows.append({
            "supplier_id": supplier_id,
            "supplier_name": supplier_name,
            "contact_person": fake.name(),
            "email": f"supplier{number:02d}@example.test",
            "phone_number": phone_number,
            "address": "Fictional Business Centre, Nairobi, Kenya",
            "delivery_lead_time_days": 7,
            "is_active": True,
        })

    if len(rows) != SUPPLIER_COUNT:
        raise RuntimeError("Supplier generation count is incorrect.")

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


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )


def month_end(value: date) -> date:
    last_day = calendar.monthrange(
        value.year,
        value.month
    )[1]

    return date(value.year, value.month, last_day)


def next_month_start(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)

    return date(value.year, value.month + 1, 1)


def datetime_at(
    value: date,
    hour: int,
    minute: int = 0
) -> datetime:
    return datetime.combine(value, time(hour, minute))


def date_range_months():
    """Yield each calendar month in the historical period."""

    current = HISTORY_START

    while current <= HISTORY_END:
        yield current.year, current.month
        current = next_month_start(current)


def write_csv(
    filename: str,
    rows: list[dict],
    columns: list[str]
):
    path = DATASET_DIR / filename

    dataframe = pd.DataFrame(
        rows,
        columns=columns
    )

    dataframe.to_csv(
        path,
        index=False,
        encoding="utf-8"
    )

    return dataframe


def make_counters() -> dict:
    return {
        "recommendation": 0,
        "purchase_order": 0,
        "goods_receipt": 0,
        "receipt_item": 0,
        "batch": 0,
        "transaction": 0,
    }


# ============================================================
# 4. SYNTHETIC DEMAND GENERATION
# ============================================================

def generate_medicine_demand(medicine: dict) -> dict:
    """
    Generate 24 consecutive calendar months of demand.

    Demand is synthetic and varies by medicine, season and
    random monthly variation.
    """

    baseline = random.randint(15, 140)
    monthly_demand = {}

    for year, month in date_range_months():
        start = date(year, month, 1)
        end = month_end(start)

        days_in_month = (end - start).days + 1

        seasonal_factor = 1.0

        if month in [3, 4, 5]:
            seasonal_factor = 1.08
        elif month in [11, 12]:
            seasonal_factor = 1.05

        noise = random.uniform(0.82, 1.18)

        demand = round_half_up(
            baseline
            * (days_in_month / PERIOD_DAYS)
            * seasonal_factor
            * noise
        )

        monthly_demand[(year, month)] = max(0, demand)

    if len(monthly_demand) != 24:
        raise RuntimeError(
            f"Expected 24 monthly demand values for "
            f"{medicine['medicine_id']}."
        )

    return monthly_demand


# ============================================================
# 5. INVENTORY ELIGIBILITY AND FEFO
# ============================================================

def batch_is_eligible(
    batch: dict,
    medicine_id: str,
    required_valid_until: date
) -> bool:
    """
    A batch is eligible only when:
    - It belongs to the requested medicine.
    - It is Active.
    - It has positive available stock.
    - Its expiry date covers the required validity date.
    """

    return (
        batch["medicine_id"] == medicine_id
        and batch["status"] == "Active"
        and int(batch["quantity_available"]) > 0
        and date.fromisoformat(batch["expiry_date"])
            >= required_valid_until
    )


def eligible_stock(
    batches: list[dict],
    medicine_id: str,
    required_valid_until: date
) -> int:
    return sum(
        int(batch["quantity_available"])
        for batch in batches
        if batch_is_eligible(
            batch,
            medicine_id,
            required_valid_until
        )
    )


def eligible_batches(
    batches: list[dict],
    medicine_id: str,
    dispensing_date: date,
    duration: int
) -> list[dict]:
    if duration < 1:
        raise ValueError("Prescription duration must be positive.")

    required_valid_until = (
        dispensing_date + timedelta(days=duration - 1)
    )

    candidates = [
        batch
        for batch in batches
        if (batch_is_eligible(
            batch,
            medicine_id,
            required_valid_until
        )
            and date.fromisoformat(batch["received_date"])
            <= dispensing_date
        )
    ]

    return sorted(
        candidates,
        key=lambda batch: (
            batch["expiry_date"],
            batch["batch_id"]
        )
    )


def allocate_fefo(
    batches: list[dict],
    medicine_id: str,
    dispensing_date: date,
    quantity: int,
    duration: int,
    patient_identifier: str,
    timestamp: datetime,
    transaction_rows: list[dict],
    transaction_counter: int,
) -> int:
    """
    Allocate one dispensing event across eligible batches.

    Each exported transaction row refers to one batch.
    When an event spans multiple batches, the rows share
    the same patient identifier and dispensing timestamp.

    Overrides:
    - Are uncommon.
    - Select a later eligible batch first.
    - Never bypass expiry or prescription-validity checks.
    - Are explicitly recorded.
    """

    if quantity <= 0:
        raise ValueError("Dispensing quantity must be positive.")

    if duration < 1 or duration > MAX_PRESCRIPTION_DAYS:
        raise ValueError("Invalid prescription duration.")

    required_valid_until = (
        dispensing_date + timedelta(days=duration - 1)
    )

    candidates = eligible_batches(
        batches,
        medicine_id,
        dispensing_date,
        duration
    )

    available = sum(
        int(batch["quantity_available"])
        for batch in candidates
    )

    if available < quantity:
        raise RuntimeError(
            f"Stock shortfall for {medicine_id} on {dispensing_date}. "
            f"Required={quantity}; eligible={available}; "
            f"prescription valid until={required_valid_until}."
        )

    use_override = (
        len(candidates) > 1
        and random.random() < OVERRIDE_PROBABILITY
    )

    allocation_order = list(candidates)

    if use_override:
        selected_later_batch = candidates[1]

        allocation_order = (
            [selected_later_batch]
            + [
                batch
                for batch in candidates
                if batch["batch_id"]
                != selected_later_batch["batch_id"]
            ]
        )

    remaining = quantity
    first_allocation = True

    for batch in allocation_order:
        if remaining <= 0:
            break

        allocated = min(
            remaining,
            int(batch["quantity_available"])
        )

        if allocated <= 0:
            continue

        batch["quantity_available"] -= allocated

        if batch["quantity_available"] < 0:
            raise RuntimeError("Negative batch inventory detected.")

        if batch["quantity_available"] == 0:
            batch["status"] = "Depleted"

        is_override = use_override and first_allocation

        if is_override:
            notes = (
                "Synthetic authorised FEFO override for exception-workflow testing. "
                f"Prescription duration: {duration} days."
            )
        else:
            notes = (
                "Synthetic dispensing record. "
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

            # Internal validation field; not exported to CSV.
            "_prescription_duration_days": duration,
        })

        remaining -= allocated
        first_allocation = False

    if remaining != 0:
        raise RuntimeError(
            f"FEFO allocation incomplete for {medicine_id}."
        )

    return transaction_counter


# ============================================================
# 6. PROCUREMENT, PURCHASE ORDERS AND GOODS RECEIVING
# ============================================================

def add_replenishment(
    medicine: dict,
    quantity: int,
    order_date: date,
    delivery_date: date,
    batches: list[dict],
    recommendations: list[dict],
    purchase_orders: list[dict],
    goods_receipts: list[dict],
    goods_receipt_items: list[dict],
    counters: dict,
    suppliers: list[dict],
    forecast_demand_quantity: int,
    eligible_stock_quantity: int,
    target_stock_quantity: int,

):
    """
    Generate a completed historical replenishment chain:

    ProcurementRecommendation
        -> PurchaseOrder
        -> GoodsReceipt
        -> GoodsReceiptItem
        -> MedicineBatch

    The historical workflow is represented by its completed
    state. The CSV schema does not contain separate approval
    timestamps or approval-user fields.
    """

    if quantity <= 0:
        raise ValueError("Replenishment quantity must be positive.")

    if delivery_date <= order_date:
        raise ValueError("Delivery must occur after the order date.")

    medicine_id = medicine["medicine_id"]

    counters["recommendation"] += 1
    counters["purchase_order"] += 1
    counters["goods_receipt"] += 1
    counters["receipt_item"] += 1
    counters["batch"] += 1

    recommendation_id = (
        f"REC{counters['recommendation']:06d}"
    )

    purchase_order_id = (
        f"PO{counters['purchase_order']:06d}"
    )

    receipt_id = (
        f"GR{counters['goods_receipt']:06d}"
    )

    receipt_item_id = (
        f"GRI{counters['receipt_item']:06d}"
    )

    batch_id = f"BAT{counters['batch']:06d}"

    supplier = random.choice(suppliers)

    lead_time_days = int(
        supplier["delivery_lead_time_days"]
    )

    actual_delivery_days = (
        delivery_date - order_date
    ).days

    if actual_delivery_days != lead_time_days:
        raise ValueError(
            f"Supplier lead-time mismatch for "
            f"{supplier['supplier_id']}: "
            f"configured={lead_time_days}, "
            f"actual={actual_delivery_days}."
        )

    incoming_stock_quantity = 0

    projected_stock_position = (
        eligible_stock_quantity
        + incoming_stock_quantity
    )

    expected_quantity = max(
        0,
        target_stock_quantity - projected_stock_position
    )

    if quantity != expected_quantity:
        raise ValueError(
            f"Historical replenishment calculation mismatch "
            f"for {medicine_id}: "
            f"quantity={quantity}, "
            f"expected={expected_quantity}."
        )

    unit_cost = money(random.uniform(8, 900))
    total_cost = money(unit_cost * quantity)

    expiry_date = delivery_date + timedelta(
        days=random.randint(540, 900)
    )

    urgency = "HIGH" if quantity > 100 else "MEDIUM"

    recommendations.append({
        "recommendation_id": recommendation_id,
        "medicine_id": medicine_id,
        "forecast_id": "",
        "recommended_quantity": quantity,
        "forecast_demand_quantity": forecast_demand_quantity,
        "eligible_stock_quantity": eligible_stock_quantity,
        "incoming_stock_quantity": incoming_stock_quantity,
        "projected_stock_position": projected_stock_position,
        "lead_time_days": lead_time_days,
        "target_stock_quantity": target_stock_quantity,
        "urgency_level": urgency,
        "reasoning": (
            "Synthetic replenishment generated to maintain "
            "eligible stock coverage for historical demand."
        ),
        "status": "Actioned",
        "is_actioned": True,
        "created_at": iso_datetime(
            datetime_at(order_date, 9)
        ),
        "updated_at": iso_datetime(
            datetime_at(delivery_date, 10)
        ),
    })

    purchase_orders.append({
        "purchase_order_id": purchase_order_id,
        "medicine_id": medicine_id,
        "supplier_id": supplier["supplier_id"],
        "recommendation_id": recommendation_id,
        "quantity_ordered": quantity,
        "total_amount": str(total_cost),
        "total_cost": str(total_cost),
        "order_date": iso_datetime(
            datetime_at(order_date, 9)
        ),
        "status": "Placed with Supplier",
    })

    goods_receipts.append({
        "goods_receipt_id": receipt_id,
        "purchase_order_id": purchase_order_id,
        "delivery_date": iso_date(delivery_date),
        "received_at": iso_datetime(
            datetime_at(delivery_date, 7,0)
        ),
        "delivery_reference": f"DEL-{receipt_id}",
        "notes": "Synthetic historical goods receipt.",
    })

    batch = {
        "batch_id": batch_id,
        "medicine_id": medicine_id,
        "batch_number": (
            f"{medicine_id}-"
            f"{delivery_date.strftime('%Y%m%d')}-"
            f"{counters['batch']:04d}"
        ),
        "quantity_received": quantity,
        "quantity_available": quantity,
        "received_date": iso_date(delivery_date),
        "expiry_date": iso_date(expiry_date),
        "storage_location": random.choice(STORAGE_LOCATIONS),
        "status": "Active",
    }

    batches.append(batch)

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
            datetime_at(delivery_date, 7,30)
        ),
        "inspection_notes": (
            "Synthetic inspection record; accepted for inventory."
        ),
    })


# ============================================================
# 7. HISTORICAL STOCK AND DISPENSING GENERATION
# ============================================================

def generate_historical_operations(
    medicines: list[dict],
    suppliers: list[dict]
) -> dict:
    batches = []
    transactions = []
    recommendations = []
    purchase_orders = []
    goods_receipts = []
    goods_receipt_items = []

    counters = make_counters()

    demand_by_medicine = {}

    # --------------------------------------------------------
    # 7.1 Initial stock before the historical period
    # --------------------------------------------------------

    for medicine in medicines:
        medicine_id = medicine["medicine_id"]

        demand = generate_medicine_demand(medicine)
        demand_by_medicine[medicine_id] = demand

        average_monthly_demand = (
            sum(demand.values()) / len(demand)
        )

        initial_batch_quantity = max(
            20,
            round_half_up(average_monthly_demand * 1.5)
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

    # --------------------------------------------------------
    # 7.2 Monthly historical dispensing
    # --------------------------------------------------------

    transaction_counter = 0

    for medicine in medicines:
        medicine_id = medicine["medicine_id"]
        demand = demand_by_medicine[medicine_id]

        average_monthly_demand = (
            sum(demand.values()) / len(demand)
        )

        reserve = max(
            10,
            round_half_up(average_monthly_demand)
        )

        for year, month in date_range_months():
            start = date(year, month, 1)
            end = month_end(start)

            total_demand = demand[(year, month)]

            # Stock must remain valid through the end of the
            # month and the maximum prescription period.
            required_valid_until = (
                end + timedelta(
                    days=MAX_PRESCRIPTION_DAYS - 1
                )
            )

            # October 2026 must also support the 1–9 November
            # snapshot simulation.
            if year == 2026 and month == 10:
                required_valid_until = max(
                    required_valid_until,
                    SNAPSHOT_DATE + timedelta(
                        days=MAX_PRESCRIPTION_DAYS - 1
                    )
                )

            stock = eligible_stock(
                batches,
                medicine_id,
                required_valid_until
            )

            target_stock = total_demand + reserve
            shortfall = max(0, target_stock - stock)

            if shortfall > 0:
                order_date = start - timedelta(days=7)
                delivery_date = start

                add_replenishment(
                    medicine=medicine,
                    quantity=shortfall,
                    order_date=order_date,
                    delivery_date=delivery_date,
                    batches=batches,
                    recommendations=recommendations,
                    purchase_orders=purchase_orders,
                    goods_receipts=goods_receipts,
                    goods_receipt_items=goods_receipt_items,
                    counters=counters,
                    suppliers=suppliers,
                    forecast_demand_quantity=total_demand,
                    eligible_stock_quantity=stock,
                    target_stock_quantity=target_stock,
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

                dispensing_date = start + timedelta(
                    days=random.randint(
                        0,
                        (end - start).days
                    )
                )

                duration = random.randint(
                    1,
                    MAX_PRESCRIPTION_DAYS
                )

                timestamp = datetime_at(
                    dispensing_date,
                    random.randint(8, 16),
                    random.randint(0, 59)
                )

                events.append({
                    "date": dispensing_date,
                    "timestamp": timestamp,
                    "quantity": int(quantity),
                    "duration": duration,
                })

            events.sort(
                key=lambda event: event["timestamp"]
            )

            for event in events:
                patient_identifier = (
                    f"PAT{transaction_counter + 1:07d}"
                )

                transaction_counter = allocate_fefo(
                    batches=batches,
                    medicine_id=medicine_id,
                    dispensing_date=event["date"],
                    quantity=event["quantity"],
                    duration=event["duration"],
                    patient_identifier=patient_identifier,
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
    transactions: list[dict],
    medicine_id: str,
    period_start: date,
    period_end: date
) -> tuple[int, int]:
    """
    Calculate dispensing totals using a half-open interval:

        period_start <= dispensed_at < period_end

    Returns:
        Total quantity dispensed
        Number of transaction rows
    """

    total_quantity = 0
    transaction_count = 0

    start_datetime = datetime.combine(
        period_start,
        time.min
    )

    end_datetime = datetime.combine(
        period_end,
        time.min
    )

    for transaction in transactions:
        if transaction["medicine_id"] != medicine_id:
            continue

        timestamp = datetime.fromisoformat(
            transaction["dispensed_at"]
        )

        if start_datetime <= timestamp < end_datetime:
            total_quantity += int(
                transaction["quantity_dispensed"]
            )

            transaction_count += 1

    return total_quantity, transaction_count


def calculate_forecast(
    transactions: list[dict],
    medicine_id: str,
    origin: date
) -> dict:
    """
    Three-period moving average.

    Each historical period is exactly 30 days.
    The 90-day history ends at the forecast origin.
    """

    period_volumes = []
    transaction_counts = []

    history_start = origin - timedelta(
        days=PERIOD_DAYS * HISTORY_PERIODS
    )

    for period_number in range(HISTORY_PERIODS):
        period_start = history_start + timedelta(
            days=period_number * PERIOD_DAYS
        )

        period_end = period_start + timedelta(
            days=PERIOD_DAYS
        )

        quantity, count = transaction_period_totals(
            transactions,
            medicine_id,
            period_start,
            period_end
        )

        period_volumes.append(quantity)
        transaction_counts.append(count)

    moving_average = round_half_up(
        sum(period_volumes) / HISTORY_PERIODS
    )

    highest = max(period_volumes)
    lowest = min(period_volumes)

    # This is a consistency score, not a statistical
    # probability or confidence interval.
    if highest == 0:
        consistency_score = Decimal("0.00")
    else:
        score = Decimal("100") * (
            Decimal("1")
            - Decimal(highest - lowest) / Decimal(highest)
        )

        score = max(
            Decimal("0"),
            min(Decimal("100"), score)
        )

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


def generate_forecasts(
    medicines: list[dict],
    transactions: list[dict]
) -> tuple[list[dict], list[dict], dict]:
    evaluation_rows = []
    november_rows = []
    evaluation_actuals = {}

    forecast_counter = 0

    # --------------------------------------------------------
    # 8.1 Six rolling-origin evaluation periods
    # --------------------------------------------------------

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

            days_in_month = (
                actual_end - actual_start
            ).days

            normalized_actual = (
                Decimal(actual_quantity)
                * Decimal(PERIOD_DAYS)
                / Decimal(days_in_month)
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

            normalized_absolute_error = abs(
                Decimal(forecasted) - normalized_actual
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

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
                "absolute_error": normalized_absolute_error,
                "generated_at": iso_datetime(
                    datetime_at(origin, 8)
                ),
            })

            evaluation_actuals[
                (medicine_id, origin)
            ] = {
                "forecast": forecasted,
                "actual": actual_quantity,
                "normalized_actual": float(normalized_actual),
            }

    # --------------------------------------------------------
    # 8.2 November 2026 forward forecast
    # --------------------------------------------------------

    # The forecast origin is 1 November 2026.
    # Its 90-day history ends at 1 November.
    # November dispensing is deliberately excluded.

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
# 9. NOVEMBER 1–9 SNAPSHOT-PERIOD DISPENSING
# ============================================================

def generate_snapshot_period_operations(
    medicines: list[dict],
    batches: list[dict],
    november_forecasts: list[dict],
    transactions: list[dict],
    transaction_counter: int,
) -> int:
    """
    Simulate dispensing from 1–9 November 2026.

    This simulation:
    - Occurs after November forecasts have been calculated.
    - Does not change November forecast history.
    - Reduces batch quantities before procurement calculations.
    - Uses the same FEFO and prescription-validity rules.
    """

    snapshot_start = FORWARD_FORECAST_START
    snapshot_end = SNAPSHOT_DATE

    elapsed_days = (
        snapshot_end - snapshot_start
    ).days + 1

    forecast_by_medicine = {
        row["medicine_id"]: row
        for row in november_forecasts
    }

    for medicine in medicines:
        medicine_id = medicine["medicine_id"]

        forecast = forecast_by_medicine[medicine_id]

        forecasted_monthly_demand = int(
            forecast["forecasted_demand_quantity"]
        )

        expected_demand = (
            forecasted_monthly_demand
            * elapsed_days
            / PERIOD_DAYS
        )

        # Synthetic actual demand is generated around the
        # forecasted daily demand. It is not a real observation.
        actual_snapshot_demand = round_half_up(
            expected_demand * random.uniform(0.85, 1.15)
        )

        if actual_snapshot_demand <= 0:
            continue

        event_count = min(
            actual_snapshot_demand,
            max(1, round(actual_snapshot_demand / 5))
        )

        quantities = np.random.multinomial(
            actual_snapshot_demand,
            np.ones(event_count) / event_count
        )

        events = []

        for quantity in quantities:
            if quantity <= 0:
                continue

            dispensing_date = snapshot_start + timedelta(
                days=random.randint(0, elapsed_days - 1)
            )

            duration = random.randint(
                1,
                MAX_PRESCRIPTION_DAYS
            )

            timestamp = datetime_at(
                dispensing_date,
                random.randint(8, 16),
                random.randint(0, 59)
            )

            events.append({
                "date": dispensing_date,
                "timestamp": timestamp,
                "quantity": int(quantity),
                "duration": duration,
            })

        events.sort(
            key=lambda event: event["timestamp"]
        )

        for event in events:
            patient_identifier = (
                f"PAT{transaction_counter + 1:07d}"
            )

            transaction_counter = allocate_fefo(
                batches=batches,
                medicine_id=medicine_id,
                dispensing_date=event["date"],
                quantity=event["quantity"],
                duration=event["duration"],
                patient_identifier=patient_identifier,
                timestamp=event["timestamp"],
                transaction_rows=transactions,
                transaction_counter=transaction_counter,
            )

    return transaction_counter


# ============================================================
# 10. NOVEMBER PROCUREMENT RECOMMENDATIONS AND PURCHASE ORDERS
# ============================================================


def generate_november_procurement(
    medicines: list[dict],
    batches: list[dict],
    november_forecasts: list[dict],
    recommendations: list[dict],
    purchase_orders: list[dict],
    suppliers: list[dict],
    counters: dict,
):
    """
    Calculate November procurement recommendations using
    inventory remaining after 1–9 November dispensing.

    Eligible inventory must cover the maximum prescription
    validity period from the snapshot date.

    The planning lead time uses the longest delivery lead
    time among active suppliers.
    """

    forecast_by_medicine = {
        row["medicine_id"]: row
        for row in november_forecasts
    }

    active_suppliers = [
        supplier
        for supplier in suppliers
        if supplier["is_active"]
    ]

    if not active_suppliers:
        raise RuntimeError(
            "No active suppliers available for procurement."
        )

    # Conservative planning assumption: use the longest
    # configured lead time among active suppliers.
    lead_time_days = max(
        int(supplier["delivery_lead_time_days"])
        for supplier in active_suppliers
    )

    # Only suppliers matching the planning lead time can
    # be selected for the resulting purchase order.
    eligible_suppliers = [
        supplier
        for supplier in active_suppliers
        if int(supplier["delivery_lead_time_days"])
        == lead_time_days
    ]

    review_period_days = PERIOD_DAYS

    # Stock must remain valid through the maximum
    # prescription duration beginning on the snapshot date.
    required_valid_until = (
        SNAPSHOT_DATE
        + timedelta(days=MAX_PRESCRIPTION_DAYS - 1)
    )

    for medicine in medicines:
        medicine_id = medicine["medicine_id"]

        forecast = forecast_by_medicine[medicine_id]

        # Use the same eligibility rule as the dispensing engine.
        eligible = eligible_stock(
            batches,
            medicine_id,
            required_valid_until,
        )

        forecast_demand = int(
            forecast["forecasted_demand_quantity"]
        )

        safety_stock_days = int(
            medicine["safety_stock_days"]
        )

        # No outstanding purchase orders are assumed at the
        # beginning of this snapshot procurement calculation.
        incoming_stock = 0

        daily_demand = (
            Decimal(forecast_demand)
            / Decimal(PERIOD_DAYS)
        )

        target_stock = round_half_up(
            daily_demand
            * Decimal(
                lead_time_days
                + review_period_days
                + safety_stock_days
            )
        )

        projected_stock_position = (
            eligible + incoming_stock
        )

        recommended_quantity = max(
            0,
            target_stock - projected_stock_position
        )

        if recommended_quantity <= 0:
            continue

        urgency = (
            "HIGH"
            if forecast_demand > 0
            and eligible <= forecast_demand / 2
            else "MEDIUM"
        )

        counters["recommendation"] += 1

        recommendation_id = (
            f"REC{counters['recommendation']:06d}"
        )

        recommendation = {
            "recommendation_id": recommendation_id,
            "medicine_id": medicine_id,
            "forecast_id": forecast["forecast_id"],
            "recommended_quantity": recommended_quantity,

            "forecast_demand_quantity": forecast_demand,
            "eligible_stock_quantity": eligible,
            "incoming_stock_quantity": incoming_stock,
            "projected_stock_position": projected_stock_position,
            "lead_time_days": lead_time_days,
            "target_stock_quantity": target_stock,

            "urgency_level": urgency,
            "reasoning": (
                "November 2026 three-period moving-average forecast "
                "indicates a projected shortfall against target stock. "
                "The calculation considers FEFO-eligible inventory "
                "at the 9 November snapshot, supplier lead time, "
                "review period and safety-stock coverage."
            ),
            "status": "Pending",
            "is_actioned": False,
            "created_at": iso_datetime(
                datetime_at(SNAPSHOT_DATE, 9)
            ),
            "updated_at": iso_datetime(
                datetime_at(SNAPSHOT_DATE, 9)
            ),
        }

        recommendations.append(recommendation)

        # Only a subset of recommendations proceeds to a PO.
        if random.random() > 0.45:
            continue

        counters["purchase_order"] += 1

        purchase_order_id = (
            f"PO{counters['purchase_order']:06d}"
        )

        # The selected supplier must match the lead time
        # used to calculate this recommendation.
        supplier = random.choice(eligible_suppliers)

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
            recommendation["status"] = "Rejected"
            recommendation["is_actioned"] = False

        elif po_status in [
            "Approved",
            "Placed with Supplier",
        ]:
            recommendation["status"] = "Actioned"
            recommendation["is_actioned"] = True

        else:
            recommendation["status"] = "Pending"
            recommendation["is_actioned"] = False

        unit_cost = money(random.uniform(8, 900))

        total_cost = money(
            unit_cost * recommended_quantity
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
# 11. FORECAST EVALUATION METRICS
# ============================================================
def calculate_evaluation_metrics(
    evaluation_actuals: dict
) -> dict:
    errors = []
    normalized_actuals = []
    percentage_errors = []

    for values in evaluation_actuals.values():
        forecast = float(values["forecast"])
        actual_30_day = float(values["normalized_actual"])

        error = abs(forecast - actual_30_day)

        errors.append(error)
        normalized_actuals.append(actual_30_day)

        if actual_30_day > 0:
            percentage_errors.append(
                error / actual_30_day * 100
            )

    mae = (
        float(np.mean(errors))
        if errors else 0.0
    )

    total_actual = sum(normalized_actuals)
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
            round(mape, 2)
            if mape is not None else None
        ),
        "MAPE_note": (
            "MAPE excludes observations with zero normalized actual demand."
        ),
        "normalization_note": (
            "Raw calendar-month actual demand is retained in the "
            "evaluation CSV. MAE, WAPE, MAPE and absolute_error "
            "use actual demand normalized to a 30-day equivalent."
        ),
        "absolute_error_field_note": (
            "The CSV absolute_error field is the absolute difference "
            "between the forecast and the 30-day-normalized actual "
            "demand, rounded to two decimal places."
        ),
    }

# ============================================================
# 12. DATA QUALITY AND INTEGRITY VALIDATION
# ============================================================

def validate_generated_data(
    medicines: list[dict],
    suppliers: list[dict],
    operations: dict,
    evaluation_forecasts: list[dict],
    november_forecasts: list[dict],
):
    """
    Perform first-stage integrity validation before dataset export.
    Validates:
    - Master-data integrity and uniqueness.
    - Batch and transaction relationships.
    - Independent stock reconciliation.
    - Chronological FEFO allocation and prescription validity.
    - Rolling forecast evaluation and November forecast integrity.
    - Procurement recommendation and purchase-order consistency.
    - Goods receipt and accepted batch reconciliation.
    """

    batches = operations["batches"]
    transactions = operations["transactions"]
    recommendations = operations["recommendations"]
    purchase_orders = operations["purchase_orders"]
    goods_receipts = operations["goods_receipts"]
    goods_receipt_items = operations["goods_receipt_items"]

    # --------------------------------------------------------
    # 1. Helper functions
    # --------------------------------------------------------

    def assert_unique(rows, field, label):
        values = [row[field] for row in rows]
        assert len(values) == len(set(values)), (
            f"Duplicate {label} detected."
        )

    def as_date(value):
        return date.fromisoformat(str(value))

    def as_datetime(value):
        return datetime.fromisoformat(str(value))

    def as_decimal(value):
        return Decimal(str(value))

    def as_int(value):
        return int(value)

    # --------------------------------------------------------
    # 2. Master-data counts and uniqueness
    # --------------------------------------------------------

    medicine_ids = {
        medicine["medicine_id"]
        for medicine in medicines
    }

    supplier_ids = {
        supplier["supplier_id"]
        for supplier in suppliers
    }

    assert len(medicines) == MEDICINE_COUNT, (
        "Unexpected medicine count."
    )

    assert len(suppliers) == SUPPLIER_COUNT, (
        "Unexpected supplier count."
    )

    assert len(medicine_ids) == len(medicines), (
        "Duplicate medicine IDs."
    )

    assert len(supplier_ids) == len(suppliers), (
        "Duplicate supplier IDs."
    )

    assert_unique(batches, "batch_id", "batch ID")
    assert_unique(
        transactions,
        "transaction_id",
        "transaction ID"
    )
    assert_unique(
        recommendations,
        "recommendation_id",
        "recommendation ID"
    )
    assert_unique(
        purchase_orders,
        "purchase_order_id",
        "purchase order ID"
    )
    assert_unique(
        goods_receipts,
        "goods_receipt_id",
        "goods receipt ID"
    )

    assert_unique(
        evaluation_forecasts,
        "forecast_id",
        "evaluation forecast ID"
    )
    assert_unique(
        november_forecasts,
        "forecast_id",
        "November forecast ID"
    )

    batch_by_id = {
        row["batch_id"]: row
        for row in batches
    }

    recommendation_by_id = {
        row["recommendation_id"]: row
        for row in recommendations
    }

    purchase_order_by_id = {
        row["purchase_order_id"]: row
        for row in purchase_orders
    }

    receipt_by_id = {
        row["goods_receipt_id"]: row
        for row in goods_receipts
    }

    # --------------------------------------------------------
    # 3. Medicine and batch integrity
    # --------------------------------------------------------

    batch_numbers = set()

    for batch in batches:
        medicine_id = batch["medicine_id"]

        assert medicine_id in medicine_ids, (
            f"Unknown medicine in batch {batch['batch_id']}."
        )

        received_quantity = as_int(
            batch["quantity_received"]
        )

        available_quantity = as_int(
            batch["quantity_available"]
        )

        assert received_quantity > 0
        assert 0 <= available_quantity <= received_quantity

        assert batch["status"] in [
            "Active",
            "Depleted",
        ]

        received_date = as_date(
            batch["received_date"]
        )

        expiry_date = as_date(
            batch["expiry_date"]
        )

        assert expiry_date > received_date, (
            f"Invalid expiry date in batch {batch['batch_id']}."
        )

        expected_status = (
            "Depleted"
            if available_quantity == 0
            else "Active"
        )

        assert batch["status"] == expected_status, (
            f"Incorrect final status for batch {batch['batch_id']}."
        )

        batch_number_key = (
            medicine_id,
            batch["batch_number"]
        )

        assert batch_number_key not in batch_numbers, (
            f"Duplicate batch number for medicine {medicine_id}."
        )

        batch_numbers.add(batch_number_key)

    # --------------------------------------------------------
    # 4. Dispensing transaction integrity
    # --------------------------------------------------------

    transactions_by_batch = defaultdict(int)
    dispensing_events = {}

    for index, transaction in enumerate(transactions):
        transaction_id = transaction["transaction_id"]

        medicine_id = transaction["medicine_id"]
        batch_id = transaction["batch_id"]

        assert medicine_id in medicine_ids
        assert batch_id in batch_by_id

        batch = batch_by_id[batch_id]

        assert batch["medicine_id"] == medicine_id, (
            f"Medicine/batch mismatch in {transaction_id}."
        )

        quantity = as_int(
            transaction["quantity_dispensed"]
        )

        assert quantity > 0

        timestamp = as_datetime(
            transaction["dispensed_at"]
        )

        assert (
            transaction["dispensed_date"]
            == transaction["dispensed_at"]
        ), (
            f"Timestamp mismatch in {transaction_id}."
        )

        dispensing_date = timestamp.date()

        duration = as_int(
            transaction["_prescription_duration_days"]
        )

        assert 1 <= duration <= MAX_PRESCRIPTION_DAYS, (
            f"Invalid prescription duration in {transaction_id}."
        )

        required_valid_until = (
            dispensing_date + timedelta(days=duration - 1)
        )

        received_date = as_date(
            batch["received_date"]
        )

        expiry_date = as_date(
            batch["expiry_date"]
        )

        assert received_date <= dispensing_date
        assert expiry_date >= required_valid_until

        assert (
            HISTORY_START <= dispensing_date <= SNAPSHOT_DATE
        )

        assert isinstance(
            transaction["is_override"],
            bool
        )

        assert transaction["patient_identifier"], (
            f"Missing patient identifier in {transaction_id}."
        )

        transactions_by_batch[batch_id] += quantity

        # Rows from one dispensing event share both fields.
        event_key = (
            transaction["patient_identifier"],
            transaction["dispensed_at"],
        )

        if event_key not in dispensing_events:
            dispensing_events[event_key] = {
                "medicine_id": medicine_id,
                "duration": duration,
                "rows": [],
                "timestamp": timestamp,
                "first_index": index,
            }

        event = dispensing_events[event_key]

        assert event["medicine_id"] == medicine_id, (
            f"Mixed medicines in dispensing event {event_key}."
        )

        assert event["duration"] == duration, (
            f"Inconsistent prescription duration in event {event_key}."
        )

        event["rows"].append(transaction)

    # --------------------------------------------------------
    # 5. Independent stock reconciliation
    # --------------------------------------------------------

    for batch in batches:
        batch_id = batch["batch_id"]

        received_quantity = as_int(
            batch["quantity_received"]
        )

        dispensed_quantity = transactions_by_batch[batch_id]

        expected_available = (
            received_quantity - dispensed_quantity
        )

        actual_available = as_int(
            batch["quantity_available"]
        )

        assert expected_available >= 0, (
            f"Batch {batch_id} has been oversold."
        )

        assert actual_available == expected_available, (
            f"Stock reconciliation failed for {batch_id}: "
            f"received={received_quantity}, "
            f"dispensed={dispensed_quantity}, "
            f"available={actual_available}."
        )

    # --------------------------------------------------------
    # 6. Chronological FEFO replay
    # --------------------------------------------------------

    # Start with the quantity received in every batch.
    # Historical eligibility is reconstructed from dates and
    # remaining quantities, not the final batch status.

    replay_stock = {
        batch["batch_id"]: as_int(
            batch["quantity_received"]
        )
        for batch in batches
    }

    ordered_events = sorted(
        dispensing_events.values(),
        key=lambda event: (
            event["timestamp"],
            event["first_index"],
        )
    )

    for event in ordered_events:
        medicine_id = event["medicine_id"]
        dispensing_date = event["timestamp"].date()
        duration = event["duration"]

        required_valid_until = (
            dispensing_date + timedelta(days=duration - 1)
        )

        rows = event["rows"]

        event_quantity = sum(
            as_int(row["quantity_dispensed"])
            for row in rows
        )

        override_rows = [
            row for row in rows
            if row["is_override"]
        ]

        # An override is recorded only on the first allocation.
        assert len(override_rows) in [0, 1], (
            f"Multiple overrides in event {event}."
        )

        if override_rows:
            assert rows[0]["is_override"] is True, (
                "Override must be recorded on the first allocation."
            )

            assert all(
                not row["is_override"]
                for row in rows[1:]
            ), (
                "Only the first allocation may be marked as an override."
            )

        # Reconstruct eligible stock at the event date.
        candidates = []

        for batch in batches:
            if batch["medicine_id"] != medicine_id:
                continue

            batch_id = batch["batch_id"]

            remaining_quantity = replay_stock[batch_id]

            if remaining_quantity <= 0:
                continue

            if as_date(batch["received_date"]) > dispensing_date:
                continue

            if as_date(batch["expiry_date"]) < required_valid_until:
                continue

            candidates.append(batch)

        candidates.sort(
            key=lambda batch: (
                as_date(batch["expiry_date"]),
                batch["batch_id"],
            )
        )

        eligible_quantity = sum(
            replay_stock[batch["batch_id"]]
            for batch in candidates
        )

        assert eligible_quantity >= event_quantity, (
            f"Insufficient eligible stock during FEFO replay: "
            f"{medicine_id}, {dispensing_date}."
        )

        # A normal dispensing event follows earliest expiry first.
        # An override selects the second eligible batch first.
        if override_rows:
            assert len(candidates) >= 2, (
                "Override recorded without at least two eligible batches."
            )

            selected_batch = rows[0]["batch_id"]

            assert selected_batch == candidates[1]["batch_id"], (
                f"Override did not select the second eligible batch "
                f"for {medicine_id} on {dispensing_date}."
            )

            allocation_order = (
                [candidates[1]]
                + [
                    batch
                    for batch in candidates
                    if batch["batch_id"] != candidates[1]["batch_id"]
                ]
            )

        else:
            allocation_order = candidates

        expected_allocations = []
        remaining_event_quantity = event_quantity

        for batch in allocation_order:
            if remaining_event_quantity <= 0:
                break

            batch_id = batch["batch_id"]
            available_quantity = replay_stock[batch_id]

            allocated_quantity = min(
                remaining_event_quantity,
                available_quantity,
            )

            if allocated_quantity <= 0:
                continue

            expected_allocations.append(
                (batch_id, allocated_quantity)
            )

            remaining_event_quantity -= allocated_quantity

        assert remaining_event_quantity == 0, (
            f"FEFO allocation could not fulfil event for {medicine_id}."
        )

        actual_allocations = [
            (
                row["batch_id"],
                as_int(row["quantity_dispensed"]),
            )
            for row in rows
        ]

        if actual_allocations != expected_allocations:
            print("\n" + "=" * 70)
            print("FEFO REPLAY DIAGNOSTIC")
            print("=" * 70)
            print(f"Medicine: {medicine_id}")
            print(f"Dispensing date: {dispensing_date}")
            print(f"Required valid until: {required_valid_until}")
            print(f"Event quantity: {event_quantity}")

            print("\nActual allocations:")
            print(actual_allocations)

            print("\nExpected allocations:")
            print(expected_allocations)

            print("\nReplay candidates:")
            for batch in candidates:
                batch_id = batch["batch_id"]
                print({
                    "batch_id": batch_id,
                    "received_date": batch["received_date"],
                    "expiry_date": batch["expiry_date"],
                    "status": batch["status"],
                    "quantity_received": batch["quantity_received"],
                    "quantity_available_final": batch["quantity_available"],
                    "replay_quantity": replay_stock[batch_id],
                })

            print("\nActual and expected batch records:")
            relevant_ids = {
                batch_id
                for batch_id, quantity in (
                    actual_allocations + expected_allocations
                )
            }

            for batch in batches:
                if batch["batch_id"] in relevant_ids:
                    print(batch)

            print("=" * 70 + "\n")

        assert actual_allocations == expected_allocations, (
            f"FEFO allocation sequence mismatch for "
            f"{medicine_id} on {dispensing_date}. "
            f"Expected={expected_allocations}; "
            f"Actual={actual_allocations}."
        )

        # Apply the reconstructed allocations to replay stock.
        for batch_id, allocated_quantity in expected_allocations:
            replay_stock[batch_id] -= allocated_quantity

            assert replay_stock[batch_id] >= 0, (
                f"Negative replay stock in batch {batch_id}."
            )

    # Final replay quantities must equal exported quantities.
    for batch in batches:
        batch_id = batch["batch_id"]

        assert replay_stock[batch_id] == as_int(
            batch["quantity_available"]
        ), (
            f"FEFO replay stock mismatch for batch {batch_id}."
        )

    # --------------------------------------------------------
    # 7. Forecast integrity
    # --------------------------------------------------------

    expected_origins = set(EVALUATION_ORIGINS)

    assert len(evaluation_forecasts) == (
        MEDICINE_COUNT * EVALUATION_MONTHS
    ), (
        "Unexpected number of evaluation forecasts."
    )

    assert len(november_forecasts) == MEDICINE_COUNT, (
        "Unexpected number of November forecasts."
    )

    evaluation_keys = set()
    origins_by_medicine = defaultdict(set)

    for forecast in evaluation_forecasts:
        medicine_id = forecast["medicine_id"]

        assert medicine_id in medicine_ids

        assert forecast["forecast_method"] == "MOVING_AVERAGE"

        forecast_start = as_date(
            forecast["forecast_period_start"]
        )

        forecast_end = as_date(
            forecast["forecast_period_end"]
        )

        history_start = as_date(
            forecast["history_start_date"]
        )

        history_end = as_date(
            forecast["history_end_date"]
        )

        assert forecast_start in expected_origins, (
            f"Unexpected evaluation origin: {forecast_start}."
        )

        assert forecast_end == (
            next_month_start(forecast_start) - timedelta(days=1)
        ), (
            f"Incorrect evaluation period end for {medicine_id}."
        )

        assert history_end == forecast_start

        assert history_start == (
            forecast_start - timedelta(days=90)
        ), (
            f"Incorrect 90-day history window for {medicine_id}."
        )

        assert (
            as_int(forecast["forecasted_demand_quantity"]) >= 0
        )

        moving_average = as_decimal(
            forecast["moving_avg_3month"]
        )

        assert moving_average == as_decimal(
            forecast["forecasted_demand_quantity"]
        ), (
            f"Moving average and forecast differ for {medicine_id}."
        )

        score = as_decimal(
            forecast["confidence_score"]
        )

        assert Decimal("0") <= score <= Decimal("100")

        transaction_count = as_int(
            forecast["historical_transaction_count"]
        )

        assert transaction_count >= 0

        actual_quantity = as_int(
            forecast["actual_demand_quantity"]
        )

        assert actual_quantity >= 0

        month_days = (
            forecast_end - forecast_start
        ).days + 1

        normalized_actual = (
            Decimal(actual_quantity)
            * Decimal(PERIOD_DAYS)
            / Decimal(month_days)
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        expected_error = abs(
            as_decimal(forecast["forecasted_demand_quantity"])
            - normalized_actual
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        actual_error = as_decimal(
            forecast["absolute_error"]
        )

        assert actual_error == expected_error, (
            f"Normalized absolute error mismatch for {medicine_id}."
        )

        evaluation_key = (
            medicine_id,
            forecast_start,
        )

        assert evaluation_key not in evaluation_keys, (
            f"Duplicate evaluation forecast for {evaluation_key}."
        )

        evaluation_keys.add(evaluation_key)
        origins_by_medicine[medicine_id].add(forecast_start)

    for medicine_id in medicine_ids:
        assert origins_by_medicine[medicine_id] == expected_origins, (
            f"Missing evaluation forecast origin for {medicine_id}."
        )

    # --------------------------------------------------------
    # 8. November forecast integrity
    # --------------------------------------------------------

    november_medicine_ids = set()

    for forecast in november_forecasts:
        medicine_id = forecast["medicine_id"]

        assert medicine_id in medicine_ids

        assert medicine_id not in november_medicine_ids, (
            f"Duplicate November forecast for {medicine_id}."
        )

        november_medicine_ids.add(medicine_id)

        assert forecast["forecast_method"] == "MOVING_AVERAGE"

        assert (
            forecast["forecast_period_start"]
            == iso_date(FORWARD_FORECAST_START)
        )

        assert (
            forecast["forecast_period_end"]
            == iso_date(FORWARD_FORECAST_END)
        )

        assert (
            forecast["history_end_date"]
            == iso_date(FORWARD_FORECAST_START)
        )

        expected_history_start = (
            FORWARD_FORECAST_START - timedelta(days=90)
        )

        assert (
            as_date(forecast["history_start_date"])
            == expected_history_start
        )

        assert as_decimal(
            forecast["moving_avg_3month"]
        ) == as_decimal(
            forecast["forecasted_demand_quantity"]
        )

        assert (
            as_int(forecast["forecasted_demand_quantity"]) >= 0
        )

        score = as_decimal(
            forecast["confidence_score"]
        )

        assert Decimal("0") <= score <= Decimal("100")

        assert forecast["actual_demand_quantity"] == ""
        assert forecast["absolute_error"] == ""

    assert november_medicine_ids == medicine_ids, (
        "November forecasts do not cover all medicines."
    )

    november_forecast_ids = {
        row["forecast_id"]
        for row in november_forecasts
    }

    november_forecast_by_id = {
        row["forecast_id"]: row
        for row in november_forecasts
    }

    # --------------------------------------------------------
    # 9. Procurement recommendation integrity
    # --------------------------------------------------------

    medicine_by_id = {
        medicine["medicine_id"]: medicine
        for medicine in medicines
    }
    supplier_by_id = {
        supplier["supplier_id"]: supplier
        for supplier in suppliers
    }

    for recommendation in recommendations:
        medicine_id = recommendation["medicine_id"]

        assert medicine_id in medicine_ids

        medicine = medicine_by_id[medicine_id]

        recommended_quantity = as_int(
            recommendation["recommended_quantity"]
        )

        forecast_demand = as_int(
            recommendation["forecast_demand_quantity"]
        )

        eligible_stock = as_int(
            recommendation["eligible_stock_quantity"]
        )

        incoming_stock = as_int(
            recommendation["incoming_stock_quantity"]
        )

        projected_stock = as_int(
            recommendation["projected_stock_position"]
        )

        lead_time = as_int(
            recommendation["lead_time_days"]
        )

        target_stock = as_int(
            recommendation["target_stock_quantity"]
        )

        assert recommended_quantity > 0
        assert forecast_demand >= 0
        assert eligible_stock >= 0
        assert incoming_stock >= 0
        assert lead_time >= 1
        assert target_stock >= 0

        # Projected stock must reconcile with its components.
        assert projected_stock == (
            eligible_stock + incoming_stock
        ), (
            f"Projected stock mismatch for {medicine_id}."
        )

        # Recommended quantity must equal the target stock
        # shortfall after accounting for projected stock.
        expected_recommendation = max(
            0,
            target_stock - projected_stock,
        )

        assert recommended_quantity == expected_recommendation, (
            f"Recommended quantity mismatch for {medicine_id}."
        )

        assert recommendation["urgency_level"] in [
            "LOW",
            "MEDIUM",
            "HIGH",
        ]

        assert recommendation["status"] in [
            "Pending",
            "Approved",
            "Rejected",
            "Actioned",
            "Cancelled",
        ]

        assert isinstance(
            recommendation["is_actioned"],
            bool,
        )

        forecast_id = recommendation["forecast_id"]

        if forecast_id:
            assert forecast_id in november_forecast_ids, (
                "Recommendation references an unknown forecast."
            )

            forecast = november_forecast_by_id[forecast_id]

            assert forecast["medicine_id"] == medicine_id, (
                "Recommendation forecast belongs to another medicine."
            )

            # Forecast demand must match the linked November forecast.
            assert forecast_demand == as_int(
                forecast["forecasted_demand_quantity"]
            ), (
                f"Forecast demand mismatch for {medicine_id}."
            )

            # November target stock:
            # daily forecast × (lead time + review period + safety stock).
            daily_demand = (
                Decimal(forecast_demand)
                / Decimal(PERIOD_DAYS)
            )

            expected_target = round_half_up(
                daily_demand
                * Decimal(
                    lead_time
                    + PERIOD_DAYS
                    + as_int(medicine["safety_stock_days"])
                )
            )

            assert target_stock == expected_target, (
                f"November target stock mismatch for {medicine_id}."
            )

        else:
            # Historical recommendation target:
            # monthly demand + reserve.
            monthly_demand = operations[
                "demand_by_medicine"
            ][medicine_id]

            average_monthly_demand = (
                sum(monthly_demand.values())
                / len(monthly_demand)
            )

            reserve = max(
                10,
                round_half_up(average_monthly_demand),
            )

            expected_target = forecast_demand + reserve

            assert target_stock == expected_target, (
                f"Historical target stock mismatch for {medicine_id}."
            )

    # --------------------------------------------------------
    # 10. Purchase order integrity and status alignment
    # --------------------------------------------------------

    seen_recommendations = set()

    for purchase_order in purchase_orders:
        medicine_id = purchase_order["medicine_id"]
        supplier_id = purchase_order["supplier_id"]

        assert medicine_id in medicine_ids
        assert supplier_id in supplier_ids

        recommendation_id = (
            purchase_order["recommendation_id"]
        )

        assert recommendation_id in recommendation_by_id

        assert recommendation_id not in seen_recommendations, (
            "Multiple purchase orders reference one recommendation."
        )

        seen_recommendations.add(recommendation_id)

        recommendation = recommendation_by_id[
            recommendation_id
        ]

        assert (
            recommendation["medicine_id"] == medicine_id
        )

        quantity_ordered = as_int(
            purchase_order["quantity_ordered"]
        )

        assert quantity_ordered > 0

        # Purchase order quantity must match its recommendation.
        assert quantity_ordered == as_int(
            recommendation["recommended_quantity"]
        ), (
            f"Purchase order quantity does not match "
            f"recommendation {recommendation_id}."
        )

        # Selected supplier must match the lead time used
        # when calculating the recommendation.
        supplier = supplier_by_id[supplier_id]

        assert as_int(
            supplier["delivery_lead_time_days"]
        ) == as_int(
            recommendation["lead_time_days"]
        ), (
            f"Supplier lead time does not match recommendation "
            f"{recommendation_id}."
        )

        assert (
            as_decimal(purchase_order["total_amount"])
            == as_decimal(purchase_order["total_cost"])
        )

        status = purchase_order["status"]

        assert status in [
            "PENDING",
            "Pending Admin Review",
            "Approved",
            "Rejected",
            "Placed with Supplier",
        ]

        # The legacy PENDING status is retained as an allowed
        # schema value but is not generated by this dataset.
        if status == "PENDING":
            continue

        expected_recommendation_state = {
            "Pending Admin Review": ("Pending", False),
            "Rejected": ("Rejected", False),
            "Approved": ("Actioned", True),
            "Placed with Supplier": ("Actioned", True),
        }

        expected_status, expected_actioned = (
            expected_recommendation_state[status]
        )

        assert recommendation["status"] == expected_status, (
            f"Recommendation status conflicts with PO {purchase_order['purchase_order_id']}."
        )

        assert recommendation["is_actioned"] is expected_actioned, (
            f"Recommendation action flag conflicts with PO "
            f"{purchase_order['purchase_order_id']}."
        )

    # --------------------------------------------------------
    # 11. Recommendation-to-purchase-order reconciliation
    # --------------------------------------------------------

    for recommendation in recommendations:
        recommendation_id = recommendation["recommendation_id"]

        linked_po_exists = (
            recommendation_id in seen_recommendations
        )

        if not recommendation["forecast_id"]:
            # Historical recommendations must have completed
            # replenishment chains.
            assert linked_po_exists, (
                f"Historical recommendation {recommendation_id} "
                "has no linked purchase order."
            )

            assert recommendation["status"] == "Actioned"
            assert recommendation["is_actioned"] is True

        elif not linked_po_exists:
            # A November recommendation without a PO must not
            # be marked as actioned.
            assert recommendation["status"] in [
                "Pending",
                "Rejected",
            ]

            assert recommendation["is_actioned"] is False

    # --------------------------------------------------------
    # 12. Goods receipt integrity
    # --------------------------------------------------------

    seen_receipt_references = set()
    supplier_by_id = {
        supplier["supplier_id"]: supplier
        for supplier in suppliers
    }

    for receipt in goods_receipts:
        purchase_order_id = receipt["purchase_order_id"]

        assert purchase_order_id in purchase_order_by_id

        purchase_order = purchase_order_by_id[
            purchase_order_id
        ]

        assert (
            purchase_order["status"] == "Placed with Supplier"
        ), (
            "Goods receipt linked to a purchase order that "
            "has not been placed with a supplier."
        )

        delivery_date = as_date(
            receipt["delivery_date"]
        )

        received_at = as_datetime(
            receipt["received_at"]
        )

        order_date = as_datetime(
            purchase_order["order_date"]
        )
        supplier = supplier_by_id[
            purchase_order["supplier_id"]
        ]

        actual_delivery_days = (
            delivery_date - order_date.date()
        ).days

        expected_delivery_days = as_int(
            supplier["delivery_lead_time_days"]
        )

        assert actual_delivery_days == expected_delivery_days, (
            f"Delivery lead-time mismatch for "
            f"{purchase_order_id}: expected "
            f"{expected_delivery_days} days, got "
            f"{actual_delivery_days} days."
        )

        assert received_at.date() == delivery_date

        assert received_at > order_date
        assert received_at.time() == time(7, 0)

        delivery_reference = receipt["delivery_reference"]

        assert delivery_reference

        assert delivery_reference not in seen_receipt_references

        seen_receipt_references.add(delivery_reference)

    seen_receipt_items = set()
    received_quantity_by_po = defaultdict(int)

    for item in goods_receipt_items:
        receipt_id = item["goods_receipt_id"]
        batch_id = item["medicine_batch_id"]

        assert receipt_id in receipt_by_id
        assert batch_id in batch_by_id

        assert item["inspection_status"] == "Accepted"

        quantity_received = as_int(
            item["quantity_received"]
        )

        assert quantity_received > 0

        receipt = receipt_by_id[receipt_id]

        purchase_order = purchase_order_by_id[
            receipt["purchase_order_id"]
        ]

        batch = batch_by_id[batch_id]

        assert batch["medicine_id"] == purchase_order["medicine_id"]

        assert batch["batch_number"] == item["batch_number"]

        assert (
            as_int(batch["quantity_received"])
            == quantity_received
        )

        assert batch["expiry_date"] == item["expiry_date"]

        assert (
            batch["received_date"] == receipt["delivery_date"]
        )

        assert (
            batch["storage_location"] == item["storage_location"]
        )

        assert batch_id not in seen_receipt_items, (
            f"Batch {batch_id} linked to multiple receipt items."
        )

        seen_receipt_items.add(batch_id)

        inspected_at = as_datetime(item["inspected_at"])
        received_at = as_datetime(receipt["received_at"])

        assert inspected_at >= received_at, (
            f"Inspection predates receipt for batch {batch_id}."
        )

        assert inspected_at.time() == time(7, 30), (
            f"Unexpected inspection time for batch {batch_id}."
        )

        received_quantity_by_po[
            receipt["purchase_order_id"]
        ] += quantity_received

    for purchase_order_id, received_quantity in (
        received_quantity_by_po.items()
    ):
        purchase_order = purchase_order_by_id[
            purchase_order_id
        ]

        assert received_quantity <= as_int(
            purchase_order["quantity_ordered"]
        ), (
            f"Goods received exceed purchase order quantity "
            f"for {purchase_order_id}."
        )

    # Every generated replenishment batch must be linked
    # to exactly one accepted receipt item.
    replenishment_batch_ids = {
        batch["batch_id"]
        for batch in batches
        if batch["batch_number"] != (
            f"{batch['medicine_id']}-INITIAL-001"
        )
    }

    assert replenishment_batch_ids == seen_receipt_items, (
        "Replenishment batches and accepted receipt items do not match."
    )

    print("Initial integrity validation passed.")

# 13. DATASET EXPORT
def export_all_datasets(
    medicines: list[dict],
    suppliers: list[dict],
    operations: dict,
    evaluation_forecasts: list[dict],
    november_forecasts: list[dict],
):
    # Remove internal-only validation fields before export.
    export_transactions = []

    for transaction in operations["transactions"]:
        export_transactions.append({
            key: value
            for key, value in transaction.items()
            if not key.startswith("_")
        })

    # --------------------------------------------------------
    # 13.1 Medicines
    # --------------------------------------------------------

    write_csv(
        "medicines.csv",
        medicines,
        [
            "medicine_id",
            "medicine_name",
            "generic_name",
            "category",
            "dosage_form",
            "reorder_level",
            "safety_stock_days",
            "is_active",
        ]
    )

    # --------------------------------------------------------
    # 13.2 Suppliers
    # --------------------------------------------------------

    write_csv(
        "suppliers.csv",
        suppliers,
        [
            "supplier_id",
            "supplier_name",
            "contact_person",
            "email",
            "phone_number",
            "address",
            "delivery_lead_time_days",
            "is_active",
        ]
    )

    # --------------------------------------------------------
    # 13.3 Medicine batches
    # --------------------------------------------------------

    write_csv(
        "medicine_batches.csv",
        operations["batches"],
        [
            "batch_id",
            "medicine_id",
            "batch_number",
            "quantity_received",
            "quantity_available",
            "received_date",
            "expiry_date",
            "storage_location",
            "status",
        ]
    )

    # --------------------------------------------------------
    # 13.4 Dispensing transactions
    # --------------------------------------------------------

    write_csv(
        "dispensing_transactions.csv",
        export_transactions,
        [
            "transaction_id",
            "medicine_id",
            "batch_id",
            "quantity_dispensed",
            "dispensed_date",
            "dispensed_at",
            "is_override",
            "patient_identifier",
            "notes",
        ]
    )

    forecast_columns = [
        "forecast_id",
        "medicine_id",
        "forecast_period_start",
        "forecast_period_end",
        "forecasted_demand_quantity",
        "moving_avg_3month",
        "forecast_method",
        "history_start_date",
        "history_end_date",
        "historical_transaction_count",
        "confidence_score",
        "actual_demand_quantity",
        "absolute_error",
        "generated_at",
    ]

    # --------------------------------------------------------
    # 13.5 Forecast evaluation
    # --------------------------------------------------------

    write_csv(
        "demand_forecasts_evaluation.csv",
        evaluation_forecasts,
        forecast_columns
    )

    # --------------------------------------------------------
    # 13.6 November forward forecasts
    # --------------------------------------------------------

    write_csv(
        "demand_forecasts_november_2026.csv",
        november_forecasts,
        forecast_columns
    )

    # --------------------------------------------------------
    # 13.7 Procurement recommendations
    # --------------------------------------------------------

    write_csv(
        "procurement_recommendations.csv",
        operations["recommendations"],
        [
            "recommendation_id",
            "medicine_id",
            "forecast_id",
            "recommended_quantity",
            "forecast_demand_quantity",
            "eligible_stock_quantity",
            "incoming_stock_quantity",
            "projected_stock_position",
            "lead_time_days",
            "target_stock_quantity",
            "urgency_level",
            "reasoning",
            "status",
            "is_actioned",
            "created_at",
            "updated_at",
        ]
    )

    # --------------------------------------------------------
    # 13.8 Purchase orders
    # --------------------------------------------------------

    write_csv(
        "purchase_orders.csv",
        operations["purchase_orders"],
        [
            "purchase_order_id",
            "medicine_id",
            "supplier_id",
            "recommendation_id",
            "quantity_ordered",
            "total_amount",
            "total_cost",
            "order_date",
            "status",
        ]
    )

    # --------------------------------------------------------
    # 13.9 Goods receipts
    # --------------------------------------------------------

    write_csv(
        "goods_receipts.csv",
        operations["goods_receipts"],
        [
            "goods_receipt_id",
            "purchase_order_id",
            "delivery_date",
            "received_at",
            "delivery_reference",
            "notes",
        ]
    )

    # --------------------------------------------------------
    # 13.10 Goods receipt items
    # --------------------------------------------------------

    write_csv(
        "goods_receipt_items.csv",
        operations["goods_receipt_items"],
        [
            "receipt_item_id",
            "goods_receipt_id",
            "medicine_batch_id",
            "batch_number",
            "quantity_received",
            "expiry_date",
            "storage_location",
            "inspection_status",
            "inspected_at",
            "inspection_notes",
        ]
    )


# ============================================================
# 14. GENERATION SUMMARY
# ============================================================

def generate_summary(
    operations: dict,
    evaluation_forecasts: list[dict],
    november_forecasts: list[dict],
    metrics: dict,
):
    datasets = {
        "medicines.csv": MEDICINE_COUNT,
        "suppliers.csv": SUPPLIER_COUNT,
        "medicine_batches.csv": len(operations["batches"]),
        "dispensing_transactions.csv": len(
            operations["transactions"]
        ),
        "demand_forecasts_evaluation.csv": len(
            evaluation_forecasts
        ),
        "demand_forecasts_november_2026.csv": len(
            november_forecasts
        ),
        "procurement_recommendations.csv": len(
            operations["recommendations"]
        ),
        "purchase_orders.csv": len(
            operations["purchase_orders"]
        ),
        "goods_receipts.csv": len(
            operations["goods_receipts"]
        ),
        "goods_receipt_items.csv": len(
            operations["goods_receipt_items"]
        ),
    }

    historical_transaction_count = sum(
        1
        for transaction in operations["transactions"]
        if date.fromisoformat(
            transaction["dispensed_at"][:10]
        ) <= HISTORY_END
    )

    snapshot_transaction_count = (
        len(operations["transactions"])
        - historical_transaction_count
    )

    summary = {
        "project": (
            "Demand-Driven Medicine Expiry Management System "
            "using FEFO"
        ),
        "random_seed": SEED,
        "historical_start": iso_date(HISTORY_START),
        "historical_end": iso_date(HISTORY_END),
        "historical_reference_period_months": REFERENCE_PERIOD_MONTHS,
        "historical_reference_period_start": iso_date(
            REFERENCE_PERIOD_START
        ),
        "historical_reference_period_end": iso_date(
            REFERENCE_PERIOD_END
        ),
        "forecast_method_history_window_days": (
                PERIOD_DAYS * HISTORY_PERIODS
        ),
        "evaluation_period_months": EVALUATION_MONTHS,
        "evaluation_origins": [
            iso_date(origin)
            for origin in EVALUATION_ORIGINS
        ],
        "forecast_period": (
            f"{iso_date(FORWARD_FORECAST_START)} to "
            f"{iso_date(FORWARD_FORECAST_END)}"
        ),
        "forecast_origin": iso_date(FORWARD_FORECAST_START),
        "snapshot_period_start": iso_date(
            FORWARD_FORECAST_START
        ),
        "snapshot_date": iso_date(SNAPSHOT_DATE),
        "historical_transaction_rows": (
            historical_transaction_count
        ),
        "snapshot_period_transaction_rows": (
            snapshot_transaction_count
        ),
        "dataset_record_counts": datasets,
        "forecast_evaluation_metrics": metrics,
        "methodological_notes": [
            (
                "The complete historical transaction dataset "
                "covers 24 consecutive calendar months, from "
                "November 2024 through October 2026."
            ),
            (
                "The 18-month historical reference/development "
                "period runs from November 2024 through April 2026. "
                "It is not an 18-month fitted model training window."
            ),
            (
                "Each forecast uses the 90 days immediately "
                "preceding its forecast origin."
            ),
            (
                "Demand forecasting uses a three-period moving average "
                "based on the three most recent completed monthly demand "
                "periods."
            ),
            (
                "November forecasts are generated before November "
                "snapshot-period dispensing transactions. Transactions "
                "from 1–9 November are excluded from the November "
                "forecast history."
            ),
            (
                "November FEFO-eligible stock includes only active, "
                "positive-quantity batches that remain valid through "
                "the maximum 14-day prescription validity period."
            ),
            (
                "The procurement review period is 30 days. Target stock "
                "is calculated using daily forecast demand multiplied "
                "by supplier lead time, review period and safety stock days."
            ),
            (
                "Evaluation uses six rolling forecast origins "
                "from May through October 2026. Later origins "
                "can use actual demand observed in earlier "
                "evaluation months."
            ),
            (
                "Procurement recommendations account for forecast "
                "demand, FEFO-eligible stock, incoming stock, "
                "supplier delivery lead time and safety stock."
            ),
            (
                "Projected stock position is the sum of "
                "FEFO-eligible stock and incoming stock."
            ),
            (
                "Recommended procurement quantity is the "
                "positive difference between target stock "
                "and projected stock position."
            ),
            (
                "The November procurement snapshot assumes "
                "no outstanding incoming purchase orders."
            ),
        ],
        "generation_restrictions": [
            "No connection to the Django database was made.",
            "No records were imported into Django.",
            "All supplier and patient identifiers are synthetic.",
            "Synthetic costs are illustrative, not market quotations.",
            "Generated identifiers are not Django primary keys.",
            "All CSV files require independent cleaning and validation.",
        ],
    }

    json_path = REPORT_DIR / "generation_summary.json"
    text_path = REPORT_DIR / "generation_summary.txt"

    with open(
        json_path,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            summary,
            file,
            indent=4
        )

    lines = [
        "SYNTHETIC DATASET GENERATION SUMMARY",
        "=" * 60,
        f"Random seed: {SEED}",
        f"Historical period: {HISTORY_START} to {HISTORY_END}",
        f"Snapshot date: {SNAPSHOT_DATE}",
        (
            "November forecast period: "
            f"{FORWARD_FORECAST_START} to "
            f"{FORWARD_FORECAST_END}"
        ),
        (
            "Historical reference period: "
            f"{REFERENCE_PERIOD_START} to "
            f"{REFERENCE_PERIOD_END}"
        ),
        (
            "Historical reference months: "
            f"{REFERENCE_PERIOD_MONTHS}"
        ),
        (
            "Forecast history window: "
            f"{PERIOD_DAYS * HISTORY_PERIODS} days"
        ),
        (
            "Evaluation months: "
            f"{EVALUATION_MONTHS}"
        ),
        "",
        "TRANSACTION PERIODS",
        "-" * 60,
        (
            "Historical transaction rows: "
            f"{historical_transaction_count:,}"
        ),
        (
            "1–9 November snapshot transaction rows: "
            f"{snapshot_transaction_count:,}"
        ),
        "",
        "DATASET RECORD COUNTS",
        "-" * 60,
    ]

    for filename, count in datasets.items():
        lines.append(f"{filename}: {count:,}")

    lines.extend([
        "",
        "FORECAST EVALUATION",
        "-" * 60,
        (
            "30-day equivalent MAE: "
            f"{metrics['MAE_30_day_equivalent']}"
        ),
        f"WAPE: {metrics['WAPE_percent']}%",
        f"MAPE: {metrics['MAPE_percent']}",
        metrics["MAPE_note"],
        metrics["normalization_note"],
        metrics["absolute_error_field_note"],
        "",
        "IMPORTANT METHODOLOGICAL NOTES",
        "-" * 60,
        (
            "November forecasts were calculated before "
            "the 1–9 November snapshot transactions."
        ),
        (
            "Demand forecasting uses a three-period moving "
            "average of completed monthly demand."
        ),
        (
            "November FEFO-eligible stock must remain valid "
            "through the maximum 14-day prescription period."
        ),
        (
            "Procurement target stock uses daily forecast demand "
            "multiplied by supplier lead time plus the 30-day "
            "review period plus safety stock days."
        ),
        (
            "Recommended procurement quantity is the positive "
            "difference between target stock and projected stock."
        ),
        (
            "November snapshot transactions were excluded "
            "from the November forecast history."
        ),
        (
            "Expired batches may retain positive quantities "
            "but are not eligible for FEFO dispensing."
        ),
        (
            "The confidence score measures consistency, "
            "not forecast probability."
        ),
        "",
        "GENERATION RESTRICTIONS",
        "-" * 60,
        "No connection to Django was made.",
        "No records were imported into the application database.",
        "All supplier and patient identifiers are synthetic.",
        "Synthetic costs are illustrative.",
        "The generated files require independent cleaning and validation.",
    ])

    with open(
        text_path,
        "w",
        encoding="utf-8"
    ) as file:
        file.write("\n".join(lines))

    print("\n".join(lines))


# ============================================================
# 15. MAIN EXECUTION
# ============================================================

def main():
    print("=" * 65)
    print("SYNTHETIC DATASET GENERATION")
    print("=" * 65)

    print(f"Random seed: {SEED}")
    print(f"Historical period: {HISTORY_START} to {HISTORY_END}")
    print(f"Snapshot date: {SNAPSHOT_DATE}")

    # --------------------------------------------------------
    # 15.1 Generate master data
    # --------------------------------------------------------

    print("\n[1/8] Generating medicine and supplier master data...")

    medicines = generate_medicines()
    suppliers = generate_suppliers()

    print(f"Medicines generated: {len(medicines)}")
    print(f"Suppliers generated: {len(suppliers)}")

    # --------------------------------------------------------
    # 15.2 Generate historical stock and dispensing
    # --------------------------------------------------------

    print("\n[2/8] Generating 24 months of historical operations...")

    operations = generate_historical_operations(
        medicines,
        suppliers
    )

    print(
        "Historical dispensing transaction rows: "
        f"{len(operations['transactions']):,}"
    )

    print(
        "Historical replenishment recommendations: "
        f"{len(operations['recommendations']):,}"
    )

    print(
        "Historical purchase orders: "
        f"{len(operations['purchase_orders']):,}"
    )

    # --------------------------------------------------------
    # 15.3 Generate forecasts BEFORE November snapshot activity
    # --------------------------------------------------------

    print("\n[3/8] Generating forecast evaluation and November forecasts...")

    (
        evaluation_forecasts,
        november_forecasts,
        evaluation_actuals,
    ) = generate_forecasts(
        medicines,
        operations["transactions"]
    )

    print(
        "Evaluation forecasts generated: "
        f"{len(evaluation_forecasts):,}"
    )

    print(
        "November forecasts generated: "
        f"{len(november_forecasts):,}"
    )

    # --------------------------------------------------------
    # 15.4 Simulate 1–9 November stock movements
    # --------------------------------------------------------

    print("\n[4/8] Simulating 1–9 November dispensing...")

    operations["counters"]["transaction"] = (
        generate_snapshot_period_operations(
            medicines=medicines,
            batches=operations["batches"],
            november_forecasts=november_forecasts,
            transactions=operations["transactions"],
            transaction_counter=operations["counters"]["transaction"],
        )
    )

    print(
        "Total dispensing transaction rows after snapshot simulation: "
        f"{len(operations['transactions']):,}"
    )

    # --------------------------------------------------------
    # 15.5 Generate November procurement recommendations
    # --------------------------------------------------------

    print("\n[5/8] Generating November procurement recommendations...")

    generate_november_procurement(
        medicines=medicines,
        batches=operations["batches"],
        november_forecasts=november_forecasts,
        recommendations=operations["recommendations"],
        purchase_orders=operations["purchase_orders"],
        suppliers=suppliers,
        counters=operations["counters"],
    )

    print(
        "Total procurement recommendations: "
        f"{len(operations['recommendations']):,}"
    )

    print(
        "Total purchase orders: "
        f"{len(operations['purchase_orders']):,}"
    )

    # --------------------------------------------------------
    # 15.6 Calculate forecast evaluation metrics
    # --------------------------------------------------------

    print("\n[6/8] Calculating forecast evaluation metrics...")

    metrics = calculate_evaluation_metrics(
        evaluation_actuals
    )

    # --------------------------------------------------------
    # 15.7 Validate before export
    # --------------------------------------------------------

    print("\n[7/8] Validating generated data...")

    validate_generated_data(
        medicines=medicines,
        suppliers=suppliers,
        operations=operations,
        evaluation_forecasts=evaluation_forecasts,
        november_forecasts=november_forecasts,
    )

    # --------------------------------------------------------
    # 15.8 Export datasets and reports
    # --------------------------------------------------------

    print("\n[8/8] Exporting datasets and reports...")

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

    print("\n" + "=" * 65)
    print("GENERATION COMPLETED")
    print("=" * 65)

    print(f"Dataset directory: {DATASET_DIR}")
    print(f"Report directory: {REPORT_DIR}")

    print("\nNo Django database connection was made.")
    print("No records were imported into Django.")


if __name__ == "__main__":
    main()