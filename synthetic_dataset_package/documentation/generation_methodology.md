# Synthetic Dataset Generation Methodology

## 1. Project
Web-Based Demand-Driven Medicine Expiry Management System
Using First Expiry First Out (FEFO) Approach.

## 2. Purpose
Generate reproducible synthetic data for testing inventory management,
FEFO dispensing, demand forecasting, procurement recommendations,
purchase orders and goods receiving.

All records are fictional and must not be interpreted as actual
hospital records or Kenyan pharmaceutical procurement statistics.

## 3. Historical period
- Historical coverage: 1 November 2024 to 31 October 2026.
- Training/history period: 1 November 2024 to 30 April 2026.
- Evaluation period: 1 May 2026 to 31 October 2026.
- Inventory snapshot: 9 November 2026.
- Forward forecast: November 2026.

## 4. Dataset volumes
- Medicines: 100.
- Suppliers: 15.
- Medicine batches: approximately 500 or more.
- Evaluation forecasts: 600.
- November forward forecasts: 100.
- Dispensing transactions, recommendations, purchase orders,
  receipts and receipt items: generated according to simulated
  demand and stock movements.

## 5. Generation principles
1. Use a fixed random seed for reproducibility.
2. Generate fictional medicine and supplier records.
3. Generate demand at medicine and time-period level.
4. Generate replenishment events where required.
5. Allocate dispensing transactions using historical-date-aware FEFO.
6. Maintain batch-level stock balances.
7. Generate forecasts using the three-period moving-average method.
8. Generate procurement recommendations using the application rules.
9. Link purchase orders, suppliers, receipts and receipt items.
10. Validate all foreign-key relationships and business constraints.

## 6. FEFO rules
A batch is eligible for dispensing only when:
- Its medicine is active.
- Its status is Active.
- Its available quantity is greater than zero.
- Its expiry date is after the dispensing date.
- Its expiry date covers the required prescription period.

Eligible batches are ordered by expiry date, then batch identifier.
A batch becomes Depleted when its available quantity reaches zero.
Dispensing must never exceed available eligible stock.

## 7. Receiving rules
Only Accepted goods receipt items create usable medicine batches.
Pending, Rejected and Quarantined items do not create usable stock.
Accepted items must have positive quantities and expiry dates later
than their delivery dates.
The total quantity recorded against a purchase order must not exceed
the ordered quantity.

## 8. Forecasting
The forecasting method is a three-period moving average.
Each historical period is a consecutive 30-day interval.
Forecast quantities are rounded to whole units using
ROUND_HALF_UP.

The confidence_score field stores the application's historical
consistency indicator. It is not a statistical probability.

Forecast evaluation reports MAE and WAPE. MAPE is reported only
where actual demand is nonzero, with its limitation documented.

Calendar-month actual demand is retained in the evaluation data.
A separate 30-day-equivalent actual demand is calculated for
comparisons with the application's 30-day forecast horizon.

## 9. Procurement
Target stock:
Forecast demand x (30 + safety_stock_days) / 30.

Recommended quantity:
Maximum of zero and (target stock - FEFO-eligible stock).

Urgency values:
LOW, MEDIUM, HIGH.

Recommendation statuses:
Pending, Approved, Rejected, Actioned, Cancelled.

Purchase-order statuses:
PENDING, Pending Admin Review, Approved, Rejected,
Placed with Supplier.

Synthetic costs are illustrative and are not actual market prices.

## 10. Data integrity
- Primary synthetic identifiers must be unique.
- Foreign-key references must resolve.
- Medicine and batch references must agree.
- Batch quantities must reconcile.
- Dispensing quantities must be positive.
- Available stock must never be negative.
- Batch numbers must be unique per medicine.
- A recommendation may be linked to at most one purchase order.
- Accepted receipt items must link to their created batches.
- Rejected, Pending and Quarantined items must not create usable stock.
- Purchase-order receipt quantities must not exceed ordered quantities.

## 11. Data cleaning and validation
The generated data will be profiled, cleaned and validated before use.
Validation will cover schema, missing values, duplicate identifiers,
date consistency, stock reconciliation, FEFO allocation, procurement
relationships and forecast evaluation.

## 12. Import restriction
No dataset may be imported into the Django database until the
complete package has been reviewed and explicitly approved.
