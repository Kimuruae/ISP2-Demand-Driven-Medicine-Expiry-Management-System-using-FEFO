from django.utils import timezone
from django.db import models
from datetime import timedelta
from decimal import Decimal
from core.models import Medicine, DispensingTransaction, DemandForecast, ProcurementRecommendation

class ForecastingEngine:
    @staticmethod
    def calculate_3_month_forecast(medicine_id):
        """
        Executes rolling 3-month quantitative analysis on consumption.
        Generates forecast targets and flags procurement recommendations.
        """
        medicine = Medicine.objects.get(id=medicine_id)
        now = timezone.now()

        # Segment 30-day chronological history brackets
        m1_start, m1_end = now - timedelta(days=30), now
        m2_start, m2_end = now - timedelta(days=60), now - timedelta(days=31)
        m3_start, m3_end = now - timedelta(days=90), now - timedelta(days=61)

        def get_volume(start, end):
            aggregate = DispensingTransaction.objects.filter(
                medicine=medicine,
                dispensed_at__range=(start, end)
            ).aggregate(total=models.Sum('quantity_dispensed'))
            return aggregate['total'] if aggregate['total'] else 0

        # Extract monthly aggregate volumes
        vol_m1 = get_volume(m1_start, m1_end)
        vol_m2 = get_volume(m2_start, m2_end)
        vol_m3 = get_volume(m3_start, m3_end)

        # Compute the 3-Month Moving Average (MA)
        moving_average = int(round((vol_m1 + vol_m2 + vol_m3) / 3.0))

        # Evaluate Confidence Scores based on historical consistency variance
        all_vols = [vol_m1, vol_m2, vol_m3]
        if max(all_vols) == 0:
            confidence_score = Decimal("100.00")
        else:
            variance = Decimal(str(max(all_vols) - min(all_vols))) / Decimal(str(max(all_vols)))
            confidence_score = Decimal("100.00") - (variance * Decimal("100.00"))

        # Save record entries inside DemandForecast ledger
        forecast_entry = DemandForecast.objects.create(
            medicine=medicine,
            forecasted_demand_quantity=moving_average,
            forecast_period_start=now.date(),
            forecast_period_end=(now + timedelta(days=30)).date(),
            moving_avg_3month=moving_average,
            confidence_score=confidence_score.quantize(Decimal("0.01"))
        )

        # Proactive Procurement Decision Support Checks
        # Evaluate against your 30-day safety stock threshold metrics
        current_active_stock = sum(
            b.quantity_available for b in medicine.medicinebatch_set.filter(
                quantity_available__gt=0,
                status="Active"
            )
        )

        if current_active_stock < moving_average:
            urgency = "HIGH" if current_active_stock <= (moving_average / 2) else "MEDIUM"
            recommended_purchase_qty = (moving_average * 2) - current_active_stock

            ProcurementRecommendation.objects.create(
                medicine=medicine,
                recommended_quantity=max(recommended_purchase_qty, medicine.reorder_level),
                urgency_level=urgency,
                reasoning=(
                    f"Current inventory balance ({current_active_stock} units) dropped below "
                    f"the 3-month average forecast demand rate ({moving_average} units/month)."
                ),
                status="Pending"
            )
        return forecast_entry