"""
Demand forecasting and FEFO-aware procurement recommendations.
Purpose:
1. Estimate medicine demand from historical dispensing.
2. Assess stock eligible for FEFO dispensing.
3. Estimate a target inventory level.
4. Create or refresh a pending procurement recommendation.
5. Record the forecast for reporting and evaluation.

This is a decision-support engine. Procurement staff must review
recommendations before purchase orders are approved or placed.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from django.db import models, transaction
from django.utils import timezone
from .models import (Medicine,DispensingTransaction,DemandForecast,ProcurementRecommendation,)

class ForecastingEngine:
    """
    Three-period moving-average forecasting engine.

    Each historical period is a consecutive 30-day window.
    The forecast is for the next 30-day period.

    Important:
    - A consistency score is not statistical forecast accuracy.
    - Stock calculations use Medicine.get_fefo_batches().
    - This class does not automatically approve or place orders.
    """

    PERIOD_DAYS = 30
    HISTORY_PERIODS = 3

    @staticmethod
    def _decimal(value):
        return Decimal(str(value or 0))

    @classmethod
    def _round_units(cls, value): #Round a forecast to the nearest whole medicine unit.
        return int(cls._decimal(value).quantize(Decimal("1"),rounding=ROUND_HALF_UP,))

    @classmethod
    def _get_period_consumption(cls, medicine, start, end):
        """
        Return total dispensing quantity and number of records
        in the half-open interval [start, end).
        The half-open interval prevents transactions on a boundary
        from being counted in two periods.
        """
        result = DispensingTransaction.objects.filter(
            medicine=medicine,
            dispensed_at__gte=start,
            dispensed_at__lt=end,).aggregate(
            total_quantity=models.Sum("quantity_dispensed"),
            transaction_count=models.Count("id"),
        )
        return (
            int(result["total_quantity"] or 0),
            int(result["transaction_count"] or 0),
        )

    @classmethod
    def _calculate_consistency_score(cls, volumes):
        """
        Calculate a simple consistency indicator from 0 to 100.

        This measures historical variation only. It is NOT a
        probability that the forecast is correct.

        A zero score is returned when all three periods show no
        recorded consumption; insufficient data must be reviewed.
        """
        highest = max(volumes)
        lowest = min(volumes)

        if highest == 0: return Decimal("0.00")
        variation = (Decimal(highest - lowest) / Decimal(highest))
        score = Decimal("100.00") * (Decimal("1.00") - variation)
        return max(Decimal("0.00"),min(Decimal("100.00"), score),).quantize(Decimal("0.01"))

    @classmethod
    def _get_fefo_eligible_stock(cls, medicine):
        """
        Sum the stock returned by the medicine's existing FEFO
        eligibility method.
        The existing get_fefo_batches() method must exclude expired,
        depleted, and otherwise ineligible batches.
        This method assumes each batch exposes quantity_available.
        """
        batches = list(medicine.get_fefo_batches())
        eligible_quantity = sum(max(0, int(batch.quantity_available or 0)) for batch in batches)
        return eligible_quantity, batches

    @classmethod
    def _get_expiring_stock(cls, batches, horizon_end):
        """
        Estimate eligible stock expiring on or before horizon_end.
        This helper expects MedicineBatch to expose expiry_date as
        a date or datetime. If your model uses another field name,
        adjust it before using expiry-risk reporting.
        """
        today = timezone.localdate()
        expiring_quantity = 0

        for batch in batches:
            expiry = getattr(batch, "expiry_date", None)
            if expiry is None: continue
            if hasattr(expiry, "date"): expiry = expiry.date()  #Support both DateField and DateTimeField.
            if today < expiry <= horizon_end: expiring_quantity += max(0,int(batch.quantity_available or 0),)
        return expiring_quantity

    @classmethod
    @transaction.atomic
    def calculate_3_month_forecast(cls, medicine_id):
        """
        Calculate and record a 30-day demand forecast.

        Replenishment logic:
        - Forecast demand from three historical 30-day periods.
        - Include safety-stock coverage in the target.
        - Recommend purchasing only the stock shortfall.
        - Refresh an existing pending recommendation when possible.

        The target uses safety_stock_days as additional days of
        forecast coverage. Supplier lead time is not currently
        modelled separately; add it when a reliable field exists.
        """
        medicine = Medicine.objects.select_for_update().get(id=medicine_id)
        now = timezone.now()
        today = timezone.localdate()

        # Define three consecutive 30-day historical periods.
        period_1_start = now - timedelta(days=30)
        period_1_end = now

        period_2_start = now - timedelta(days=60)
        period_2_end = period_1_start

        period_3_start = now - timedelta(days=90)
        period_3_end = period_2_start

        # Retrieve historical dispensing totals.
        vol_1, count_1 = cls._get_period_consumption(medicine, period_1_start, period_1_end)
        vol_2, count_2 = cls._get_period_consumption(medicine, period_2_start, period_2_end)
        vol_3, count_3 = cls._get_period_consumption(medicine, period_3_start, period_3_end)
        volumes = [vol_1, vol_2, vol_3]
        transaction_count = count_1 + count_2 + count_3

        # Simple moving average: equal weight for each 30-day period.
        moving_average = cls._round_units(Decimal(sum(volumes)) / Decimal(3))

        # A score of zero means no recorded demand or very unstable
        # demand. It should not be interpreted as forecast probability.
        consistency_score = cls._calculate_consistency_score(volumes)

        # Record whether the historical evidence is limited.
        # Three periods with no records are different from three
        # observed periods that happened to have zero consumption.
        insufficient_history = transaction_count == 0

        # Store forecast dates as dates, consistent with the model
        # fields shown in the existing implementation.
        forecast_start = today
        forecast_end = today + timedelta(days=cls.PERIOD_DAYS)

        forecast_entry, _created = DemandForecast.objects.update_or_create(
            medicine=medicine,
            forecast_period_start=forecast_start,
            forecast_period_end=forecast_end,
            defaults={
                "forecasted_demand_quantity": moving_average,
                "moving_avg_3month": moving_average,
                "forecast_method": DemandForecast.ForecastMethod.MOVING_AVERAGE,
                "history_start_date": period_3_start.date(),
                "history_end_date": today,
                "historical_transaction_count": transaction_count,
                "confidence_score": consistency_score,
            },
        )

        # Obtain stock eligible for FEFO dispensing.
        eligible_stock, eligible_batches = (
            cls._get_fefo_eligible_stock(medicine)
        )

        # Estimate stock likely to expire during the forecast horizon.
        expiring_stock = cls._get_expiring_stock(eligible_batches,forecast_end,)

        # Safety stock is additional coverage, expressed in days.
        safety_days = max(0,int(getattr(medicine, "safety_stock_days", 0) or 0),)

        # Target = demand for the next 30 days + safety-stock coverage.
        # This is a basic policy; supplier lead time should be added
        # separately once the model contains a reliable lead-time field.
        target_stock = cls._round_units(Decimal(moving_average)* Decimal(cls.PERIOD_DAYS + safety_days)/ Decimal(cls.PERIOD_DAYS))

        # Replenishment is the shortfall against target inventory.
        recommended_quantity = max(0,target_stock - eligible_stock,)

        # Determine whether the current inventory is below target.
        needs_replenishment = recommended_quantity > 0

        if needs_replenishment:
            # HIGH means the usable stock cannot cover half the
            # forecasted 30-day demand. This is a transparent rule,
            # not a clinical risk classification.
            if ( moving_average > 0 and eligible_stock <= moving_average / 2
            ): urgency = "HIGH"
            else: urgency = "MEDIUM"

            reasons = [
                f"FEFO-eligible stock: {eligible_stock} units.",
                f"Forecast demand for 30 days: {moving_average} units.",
                f"Target stock including safety coverage: {target_stock} units.",
                f"Estimated replenishment shortfall: {recommended_quantity} units.",
            ]

            if insufficient_history:
                reasons.append(
                    "Warning: no dispensing records were found in "
                    "the 90-day historical window. Validate demand "
                    "before approving procurement."
                )

            if expiring_stock:
                reasons.append(
                    f"Approximately {expiring_stock} eligible units "
                    "have expiry dates within the forecast horizon. "
                    "Review batch-level expiry dates before ordering."
                )

            recommendation_fields = {
                "forecast": forecast_entry,
                "recommended_quantity": recommended_quantity,
                "urgency_level": urgency,
                "reasoning": " ".join(reasons),
            }

            # Update an existing pending recommendation rather than
            # creating another one for the same medicine.
            recommendation = (
                ProcurementRecommendation.objects.filter(
                    medicine=medicine,
                    status=ProcurementRecommendation.Status.PENDING).order_by("id").first())

            if recommendation:
                for field, value in recommendation_fields.items():setattr(recommendation, field, value)
                recommendation.save(update_fields=list(recommendation_fields.keys()))
            else:ProcurementRecommendation.objects.create(medicine=medicine,status="Pending",**recommendation_fields,)

        else:
            # Do not automatically cancel approved or placed orders.
            # Close obsolete pending recommendations if your model
            # supports a dedicated cancellation status. Since the
            # existing status choices are not provided here, leave
            # the record untouched and flag this for workflow review.
            pass
        return forecast_entry