from django.core.management.base import BaseCommand, CommandError
from core.models import Medicine
from core.forecasting_engine import ForecastingEngine


class Command(BaseCommand):
    help = (
        "Executes a quantitative rolling 3-month moving average demand forecast "
        "across all active pharmaceutical products and generates procurement recommendations "
        "for inventory lines falling below safety thresholds."
    )

    def handle(self, *args, **options):
        # Fetch active medicine lines within the facility scope
        active_medicines = Medicine.objects.filter(is_active=True)

        if not active_medicines.exists():
            self.stdout.write(self.style.WARNING("⚠️ No active medicine definitions found in the database."))
            return

        self.stdout.write(self.style.MATED(
            f"🚀 Initializing demand forecasting execution for {active_medicines.count()} active lines..."))

        success_count = 0
        failure_count = 0

        for medicine in active_medicines:
            try:
                # Invoke the algorithmic business logic layer
                forecast_record = ForecastingEngine.calculate_3_month_forecast(medicine.id)

                self.stdout.write(
                    self.style.SUCCESS(
                        f"✅ {medicine.name}: Forecast = {forecast_record.moving_avg_3month} units/month "
                        f"(Confidence Score: {forecast_record.confidence_score}%)"
                    )
                )
                success_count += 1

            except Exception as e:
                self.stderr.write(
                    self.style.ERROR(f"❌ Failed to calculate forecast metrics for {medicine.name}. Reason: {str(e)}")
                )
                failure_count += 1

        # Summary telemetry printout
        self.stdout.write(self.style.MATED("\n=== FORECASTING EXECUTION SUMMARY ==="))
        self.stdout.write(self.style.SUCCESS(f"  Successfully processed: {success_count} item(s)"))
        if failure_count > 0:
            self.stdout.write(self.style.ERROR(f"  Failed processing:      {failure_count} item(s)"))
        self.stdout.write(self.style.MATED("====================================="))