from django.core.management.base import BaseCommand
from core.models import Medicine
from core.forecasting_engine import ForecastingEngine

class Command(BaseCommand):
    help = (
        "Generates weekly rolling 30-day medicine demand forecasts "
        "using the preceding 90 days of dispensing history."
    )

    def handle(self, *args, **options):
        active_medicines = Medicine.objects.filter(is_active=True).order_by("id")
        if not active_medicines.exists():
            self.stdout.write(self.style.WARNING("No active medicines found."))
            return

        self.stdout.write(self.style.NOTICE(
                f"Starting forecasting for "
                f"{active_medicines.count()} medicines."
            )
        )
        success_count = 0
        failure_count = 0

        for medicine in active_medicines:
            try:
                forecast = (ForecastingEngine.calculate_3_month_forecast(medicine.id))
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{medicine.name}: "
                        f"{forecast.forecasted_demand_quantity} "
                        f"units forecasted."
                    )
                )
                success_count += 1

            except Exception as error:
                self.stderr.write(self.style.ERROR(f"{medicine.name}: {error}"))
                failure_count += 1

        self.stdout.write("\n")
        self.stdout.write(self.style.SUCCESS("FORECASTING EXECUTION SUMMARY"))
        self.stdout.write(f"Successfully processed: {success_count}")
        self.stdout.write(f"Failed: {failure_count}")