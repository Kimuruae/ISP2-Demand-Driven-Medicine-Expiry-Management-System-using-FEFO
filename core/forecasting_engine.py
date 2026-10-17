
from datetime import timedelta
from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from .models import (
    Medicine,
    DispensingTransaction,
    DemandForecast,
    ProcurementRecommendation,
)


class ForecastingEngine:
    @staticmethod
    @transaction.atomic
    def calculate_3_month_forecast(medicine_id):
        """
        Calculate a three-month moving-average demand forecast,
        save the forecast, and assess procurement requirements.
        """
        medicine = Medicine.objects.get(id=medicine_id)
        now = timezone.now()

        # Three consecutive, non-overlapping 30-day periods.
        m1_start = now - timedelta(days=30)
        m1_end = now

        m2_start = now - timedelta(days=60)
        m2_end = m1_start

        m3_start = now - timedelta(days=90)
        m3_end = m2_start

        def get_volume(start, end):
            aggregate = DispensingTransaction.objects.filter(
                medicine=medicine,
                dispensed_at__gte=start,
                dispensed_at__lt=end,
            ).aggregate(
                total=models.Sum("quantity_dispensed")
            )

            return aggregate["total"] or 0

        # Calculate consumption in each period.
        vol_m1 = get_volume(m1_start, m1_end)
        vol_m2 = get_volume(m2_start, m2_end)
        vol_m3 = get_volume(m3_start, m3_end)

        # Three-month moving-average forecast.
        moving_average = int(
            round((vol_m1 + vol_m2 + vol_m3) / 3)
        )

        # Heuristic consistency score, not statistical confidence.
        all_volumes = [vol_m1, vol_m2, vol_m3]
        highest_volume = max(all_volumes)
        lowest_volume = min(all_volumes)

        if highest_volume == 0:
            confidence_score = Decimal("100.00")
        else:
            variation = (
                Decimal(str(highest_volume - lowest_volume))
                / Decimal(str(highest_volume))
            )

            confidence_score = (
                Decimal("100.00")
                - variation * Decimal("100.00")
            )

        confidence_score = max(
            Decimal("0.00"),
            min(
                Decimal("100.00"),
                confidence_score,
            ),
        ).quantize(Decimal("0.01"))

        # Record the forecast.
        forecast_entry = DemandForecast.objects.create(
            medicine=medicine,
            forecasted_demand_quantity=moving_average,
            forecast_period_start=now.date(),
            forecast_period_end=(
                now + timedelta(days=30)
            ).date(),
            moving_avg_3month=moving_average,
            confidence_score=confidence_score,
        )

        # Count stock returned by the FEFO eligibility rules.
        eligible_batches = medicine.get_fefo_batches()

        current_active_stock = sum(
            batch.quantity_available
            for batch in eligible_batches
        )

        # Generate or refresh a pending procurement recommendation.
        if current_active_stock < moving_average:
            urgency = (
                "HIGH"
                if current_active_stock <= moving_average / 2
                else "MEDIUM"
            )

            recommended_purchase_qty = max(
                (moving_average * 2) - current_active_stock,
                medicine.reorder_level or 0,
            )

            recommendation = (
                ProcurementRecommendation.objects.filter(
                    medicine=medicine,
                    status="Pending",
                ).first()
            )

            recommendation_fields = {
                "recommended_quantity": recommended_purchase_qty,
                "urgency_level": urgency,
                "reasoning": (
                    f"Current eligible inventory is "
                    f"{current_active_stock} units. "
                    f"The three-month moving-average demand is "
                    f"{moving_average} units per 30-day period."
                ),
            }

            if recommendation:
                for field, value in recommendation_fields.items():
                    setattr(recommendation, field, value)

                recommendation.save()
            else:
                ProcurementRecommendation.objects.create(
                    medicine=medicine,
                    status="Pending",
                    **recommendation_fields,
                )

        return forecast_entry