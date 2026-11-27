from .models import ProcurementRecommendation, PurchaseOrder


def procurement_nav(request):
    """Counts shown as badges in the procurement sidebar (procurement pages only)."""
    match = getattr(request, "resolver_match", None)
    url_name = getattr(match, "url_name", "") or ""
    user = getattr(request, "user", None)

    if not (user and user.is_authenticated and url_name.startswith("procurement")):
        return {}

    return {
        "nav_counts": {
            "recommendations": ProcurementRecommendation.objects.filter(
                status=ProcurementRecommendation.Status.PENDING,
                purchase_order__isnull=True,
            ).count(),
            "to_place": PurchaseOrder.objects.filter(
                status=PurchaseOrder.Status.APPROVED
            ).count(),
        }
    }