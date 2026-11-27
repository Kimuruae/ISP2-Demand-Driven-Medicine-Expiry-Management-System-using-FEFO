"""Procurement Officer portal: alerts, recommendations, orders, delivery, analytics, reports."""
import csv
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import Count, OuterRef, Subquery, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from .models import (
    GoodsReceiptItem,
    Medicine,
    MedicineBatch,
    ProcurementRecommendation,
    PurchaseOrder,
    UserAlert,
)
from .views import role_required

PO = PurchaseOrder.Status
REC = ProcurementRecommendation.Status
OPEN_PO_STATUSES = (PO.PENDING_ADMIN_REVIEW, PO.APPROVED, PO.PLACED_WITH_SUPPLIER)

PAGE_SIZE = 25
DELIVERY_SECTION_LIMIT = 50

# received_units_by_po() below reads the goods-receipt records.
RECEIPTS_CONNECTED = True

procurement_only = role_required("Procurement Officer")

STATUS_CLASS = {
    PO.PENDING_ADMIN_REVIEW: "pill-pending",
    PO.APPROVED: "pill-approved",
    PO.PLACED_WITH_SUPPLIER: "pill-placed",
    PO.REJECTED: "pill-rejected",
}
SEVERITY_RANK = {"High": 0, "Medium": 1, "Info": 2}
SEVERITY_PILL = {"High": "pill-high", "Medium": "pill-medium", "Info": "pill-low"}


# ---------------------------------------------------------------- helpers
def _as_date(value):
    """order_date / created_at may be a date or a datetime; always return a date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.date()
    return value


def _order_date_range(queryset, start=None, end=None):
    """Filter purchase orders by order date, whether the field is a date or a datetime."""
    is_datetime = PurchaseOrder._meta.get_field("order_date").get_internal_type() == "DateTimeField"
    if start:
        queryset = queryset.filter(
            **({"order_date__date__gte": start} if is_datetime else {"order_date__gte": start})
        )
    if end:
        queryset = queryset.filter(
            **({"order_date__date__lte": end} if is_datetime else {"order_date__lte": end})
        )
    return queryset


def _query_string(request, drop=("page", "export")):
    """Current filters as 'a=1&b=2&' so page and export links can append to them."""
    params = request.GET.copy()
    for key in drop:
        params.pop(key, None)
    encoded = params.urlencode()
    return f"{encoded}&" if encoded else ""


def _pct(value, maximum):
    return int(round(value / maximum * 100)) if maximum else 0


def _med_name(obj):
    return obj.medicine.medicine_name if obj.medicine else "Unknown medicine"


def _supplier_name(po):
    return po.supplier.supplier_name if po.supplier else "No supplier"


def _decorate_po(po):
    po.status_class = STATUS_CLASS.get(po.status, "pill-muted")
    po.can_place = po.status == PO.APPROVED
    return po


# --------------------------------------------------------- delivery logic
def received_units_by_po(po_ids):
    """Units physically received per purchase order, from goods-receipt items.

    A PO can have several receipts (partial deliveries). Units rejected at
    inspection do not count, because the supplier still owes them. Pending,
    accepted and quarantined units all count as received.
    """
    rows = (
        GoodsReceiptItem.objects
        .filter(goods_receipt__purchase_order_id__in=po_ids)
        .exclude(inspection_status=GoodsReceiptItem.InspectionStatus.REJECTED)
        .order_by()
        .values("goods_receipt__purchase_order_id")
        .annotate(units=Sum("quantity_received"))
    )
    return {r["goods_receipt__purchase_order_id"]: r["units"] or 0 for r in rows}


def delivery_stage(ordered, received):
    if ordered and received >= ordered:
        return "delivered"
    if received > 0:
        return "inbound"
    return "placed"


def _expected_date(po):
    days = getattr(po.supplier, "delivery_lead_time_days", None)
    ordered_on = _as_date(po.order_date)
    if days is None or ordered_on is None:
        return None
    return ordered_on + timedelta(days=days)


def _delivery_rows(orders):
    orders = list(orders)
    received = received_units_by_po([po.pk for po in orders])
    today = timezone.localdate()
    rows = []
    for po in orders:
        got = received.get(po.pk, 0) or 0
        ordered = po.quantity_ordered or 0
        stage = delivery_stage(ordered, got)
        expected = _expected_date(po)
        rows.append({
            "po": po,
            "received": got,
            "balance": max(ordered - got, 0),
            "stage": stage,
            "expected": expected,
            "overdue": stage != "delivered" and expected is not None and expected < today,
        })
    return rows


# ----------------------------------------------------------------- alerts
def _build_alerts(user):
    today = timezone.localdate()
    alerts = []

    def add(severity, kind, title, detail, when=None, link="", link_label="",
            personal_id=None, is_read=False):
        alerts.append({
            "severity": severity,
            "pill": SEVERITY_PILL[severity],
            "kind": kind,
            "title": title,
            "detail": detail,
            "when": when,
            "link": link,
            "link_label": link_label,
            "personal_id": personal_id,
            "is_read": is_read,
        })

    recs_url = reverse("procurement_recommendations") + "?" + urlencode({"status": str(REC.PENDING)})
    orders_url = reverse("procurement_orders")
    delivery_url = reverse("procurement_delivery")

    # 1. Recommendations waiting for a purchase order (system and Store Manager).
    pending_recs = (
        ProcurementRecommendation.objects
        .filter(status=REC.PENDING, purchase_order__isnull=True)
        .select_related("medicine", "raised_by")
        .order_by("-created_at")
    )
    for rec in pending_recs:
        urgency = str(rec.urgency_level or "").upper()
        severity = ("High" if urgency in {"HIGH", "CRITICAL", "URGENT"}
                    else "Medium" if urgency == "MEDIUM" else "Info")
        source = rec.raised_by.get_username() if rec.raised_by else "the system forecast"
        add(severity, "Recommendation",
            f"Recommendation awaiting review: {_med_name(rec)}",
            f"{rec.recommended_quantity} units suggested by {source} (reference #{rec.pk}).",
            _as_date(rec.created_at), recs_url, "Review")

    # 2. Orders approved by the Hospital Admin and waiting to be placed.
    approved_url = orders_url + "?" + urlencode({"status": str(PO.APPROVED)})
    for po in PurchaseOrder.objects.filter(status=PO.APPROVED).select_related("medicine", "supplier"):
        add("High", "Purchase order",
            f"Approved, ready to place: PO #{po.pk}",
            f"{po.quantity_ordered} units of {_med_name(po)} from {_supplier_name(po)}.",
            _as_date(po.order_date), approved_url, "Place order")

    # 3. Orders still waiting for the Hospital Admin after 3 days, and recent rejections.
    pending_url = orders_url + "?" + urlencode({"status": str(PO.PENDING_ADMIN_REVIEW)})
    rejected_url = orders_url + "?" + urlencode({"status": str(PO.REJECTED)})
    for po in (PurchaseOrder.objects
               .filter(status__in=[PO.PENDING_ADMIN_REVIEW, PO.REJECTED])
               .select_related("medicine", "supplier")):
        ordered_on = _as_date(po.order_date)
        age = (today - ordered_on).days if ordered_on else None
        if po.status == PO.PENDING_ADMIN_REVIEW and age is not None and age >= 3:
            add("Medium", "Purchase order",
                f"Waiting for Hospital Admin for {age} days: PO #{po.pk}",
                f"{po.quantity_ordered} units of {_med_name(po)}.",
                ordered_on, pending_url, "View")
        elif po.status == PO.REJECTED and age is not None and age <= 30:
            why = po.decision_reason or "No reason recorded."
            add("Medium", "Purchase order",
                f"Rejected by Hospital Admin: PO #{po.pk}",
                f"{po.quantity_ordered} units of {_med_name(po)}. Reason: {why}",
                ordered_on, rejected_url, "View")

    # 4. Placed orders past the supplier's expected delivery date.
    placed = PurchaseOrder.objects.filter(status=PO.PLACED_WITH_SUPPLIER).select_related("medicine", "supplier")
    for row in _delivery_rows(placed):
        if row["overdue"]:
            po = row["po"]
            add("High", "Delivery",
                f"Delivery overdue: PO #{po.pk}",
                f"{_med_name(po)} from {_supplier_name(po)} was expected by {row['expected']:%d %b %Y}; "
                f"{row['balance']} units still due.",
                row["expected"], delivery_url, "Track")

    # 5. Personal alerts addressed to this officer.
    for ua in UserAlert.objects.filter(recipient=user, is_resolved=False).order_by("-created_at"):
        level = str(ua.severity or "").casefold()
        severity = "High" if level in {"critical", "high"} else "Medium" if level == "medium" else "Info"
        add(severity, "Personal", ua.title, ua.message, _as_date(ua.created_at),
            ua.action_url or "", "Open" if ua.action_url else "",
            personal_id=ua.pk, is_read=ua.is_read)

    alerts.sort(key=lambda a: (SEVERITY_RANK[a["severity"]], -(a["when"].toordinal() if a["when"] else 0)))
    return alerts


@procurement_only
def procurement_alerts_view(request):
    alerts = _build_alerts(request.user)
    summary = {
        "total": len(alerts),
        "high": sum(1 for a in alerts if a["severity"] == "High"),
        "medium": sum(1 for a in alerts if a["severity"] == "Medium"),
        "info": sum(1 for a in alerts if a["severity"] == "Info"),
    }
    selected = request.GET.get("severity", "").strip().title()
    if selected in SEVERITY_RANK:
        alerts = [a for a in alerts if a["severity"] == selected]
    else:
        selected = ""
    return render(request, "procurement/procurement_alerts.html", {
        "alerts": alerts,
        "summary": summary,
        "selected_severity": selected,
    })


# ------------------------------------------------------- recommendations
@procurement_only
def procurement_recommendations_view(request):
    status_filter = request.GET.get("status", "").strip()
    source = request.GET.get("source", "").strip()

    linked_po = PurchaseOrder.objects.filter(recommendation=OuterRef("pk"))
    base = ProcurementRecommendation.objects.all()
    queryset = (
        ProcurementRecommendation.objects
        .select_related("medicine", "raised_by")
        .annotate(
            linked_po_id=Subquery(linked_po.values("id")[:1]),
            linked_po_status=Subquery(linked_po.values("status")[:1]),
        )
        .order_by("-created_at", "-pk")
    )

    statuses = list(base.order_by("status").values_list("status", flat=True).distinct())
    if status_filter in statuses:
        queryset = queryset.filter(status=status_filter)
    else:
        status_filter = ""
    if source == "system":
        queryset = queryset.filter(raised_by__isnull=True)
    elif source == "staff":
        queryset = queryset.filter(raised_by__isnull=False)
    else:
        source = ""

    tiles = {
        "total": base.count(),
        "pending": base.filter(status=REC.PENDING, purchase_order__isnull=True).count(),
        "converted": base.filter(purchase_order__isnull=False).distinct().count(),
        "rejected": base.filter(status=REC.REJECTED).count(),
    }
    page_obj = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "procurement/procurement_recommendations.html", {
        "page_obj": page_obj,
        "recommendations": page_obj,
        "statuses": statuses,
        "selected_status": status_filter,
        "selected_source": source,
        "pending_status": str(REC.PENDING),
        "tiles": tiles,
        "query_string": _query_string(request),
    })


# ----------------------------------------------------------------- orders
@procurement_only
def procurement_orders_view(request):
    status_filter = request.GET.get("status", "").strip()
    counts = dict(PurchaseOrder.objects.values("status").annotate(n=Count("pk")).values_list("status", "n"))

    tab_defs = [
        ("", "All"),
        (str(PO.PENDING_ADMIN_REVIEW), "Pending admin review"),
        (str(PO.APPROVED), "Approved: ready to place"),
        (str(PO.PLACED_WITH_SUPPLIER), "Placed with supplier"),
        (str(PO.REJECTED), "Rejected"),
    ]
    tabs = [
        {"key": key, "label": label,
         "count": sum(counts.values()) if key == "" else counts.get(key, 0)}
        for key, label in tab_defs
    ]

    queryset = (
        PurchaseOrder.objects
        .select_related("medicine", "supplier", "raised_by", "reviewed_by")
        .order_by("-order_date", "-pk")
    )
    if status_filter in {t["key"] for t in tabs if t["key"]}:
        queryset = queryset.filter(status=status_filter)
    else:
        status_filter = ""

    page_obj = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))
    for po in page_obj:
        _decorate_po(po)

    return render(request, "procurement/procurement_orders.html", {
        "page_obj": page_obj,
        "purchase_orders": page_obj,
        "tabs": tabs,
        "selected_status": status_filter,
        "query_string": _query_string(request),
    })


# --------------------------------------------------------------- delivery
@procurement_only
def procurement_delivery_view(request):
    placed = (
        PurchaseOrder.objects
        .filter(status=PO.PLACED_WITH_SUPPLIER)
        .select_related("medicine", "supplier", "raised_by")
        .order_by("-order_date", "-pk")
    )
    rows = _delivery_rows(placed)

    columns = []
    for key, label, hint in (
        ("placed", "Placed", "Sent to the supplier; nothing received yet."),
        ("inbound", "Inbound", "Partly received; the balance is still due."),
        ("delivered", "Delivered", "Fully received."),
    ):
        stage_rows = [r for r in rows if r["stage"] == key]
        columns.append({
            "key": key,
            "label": label,
            "hint": hint,
            "count": len(stage_rows),
            "rows": stage_rows[:DELIVERY_SECTION_LIMIT],
            "truncated": len(stage_rows) > DELIVERY_SECTION_LIMIT,
        })

    return render(request, "procurement/procurement_delivery.html", {
        "columns": columns,
        "limit": DELIVERY_SECTION_LIMIT,
        "overdue_count": sum(1 for r in rows if r["overdue"]),
        "awaiting_placement": PurchaseOrder.objects.filter(status=PO.APPROVED).count(),
        "receipts_connected": RECEIPTS_CONNECTED,
    })


# -------------------------------------------------------------- analytics
@procurement_only
def procurement_analytics_view(request):
    today = timezone.localdate()
    orders = PurchaseOrder.objects.all()

    # Orders by status
    status_rows = list(
        orders.values("status").annotate(orders=Count("pk"), units=Sum("quantity_ordered")).order_by("-orders")
    )
    counts = {r["status"]: r["orders"] for r in status_rows}
    max_orders = max((r["orders"] for r in status_rows), default=0)
    status_bars = [{
        "label": r["status"],
        "orders": r["orders"],
        "units": r["units"] or 0,
        "pct": _pct(r["orders"], max_orders),
        "css": STATUS_CLASS.get(r["status"], "pill-muted"),
    } for r in status_rows]

    total_orders = sum(counts.values())
    units_ordered = orders.exclude(status=PO.REJECTED).aggregate(u=Sum("quantity_ordered"))["u"] or 0
    approved = counts.get(PO.APPROVED, 0) + counts.get(PO.PLACED_WITH_SUPPLIER, 0)
    decided = approved + counts.get(PO.REJECTED, 0)
    approval_rate = round(approved / decided * 100) if decided else None

    # Last 12 months of order activity
    months = []
    for offset in range(11, -1, -1):
        index = today.year * 12 + today.month - 1 - offset
        months.append(date(index // 12, index % 12 + 1, 1))
    monthly = (
        _order_date_range(PurchaseOrder.objects.all(), start=months[0])
        .annotate(month=TruncMonth("order_date"))
        .values("month")
        .annotate(orders=Count("pk"), units=Sum("quantity_ordered"))
        .order_by("month")
    )
    lookup = {r["month"].strftime("%Y-%m"): r for r in monthly if r["month"]}
    max_units = max((r["units"] or 0 for r in lookup.values()), default=0)
    month_cols = []
    for m in months:
        row = lookup.get(m.strftime("%Y-%m"), {})
        units = row.get("units") or 0
        month_cols.append({
            "label": m.strftime("%b %y"),
            "orders": row.get("orders", 0),
            "units": units,
            "pct": _pct(units, max_units),
        })

    # Top medicines and suppliers
    med_rows = list(
        orders.exclude(status=PO.REJECTED)
        .values("medicine__medicine_name")
        .annotate(units=Sum("quantity_ordered"), orders=Count("pk"))
        .order_by("-units")[:8]
    )
    max_med = max((r["units"] or 0 for r in med_rows), default=0)
    top_medicines = [{
        "name": r["medicine__medicine_name"] or "Unknown medicine",
        "units": r["units"] or 0,
        "orders": r["orders"],
        "pct": _pct(r["units"] or 0, max_med),
    } for r in med_rows]

    sup_rows = list(
        orders.values("supplier__supplier_name")
        .annotate(orders=Count("pk"), units=Sum("quantity_ordered"))
        .order_by("-orders")[:8]
    )
    max_sup = max((r["orders"] for r in sup_rows), default=0)
    top_suppliers = [{
        "name": r["supplier__supplier_name"] or "No supplier",
        "orders": r["orders"],
        "units": r["units"] or 0,
        "pct": _pct(r["orders"], max_sup),
    } for r in sup_rows]

    # Recommendations
    recs = ProcurementRecommendation.objects.all()
    rec_total = recs.count()
    rec_converted = recs.filter(purchase_order__isnull=False).distinct().count()
    rec_pending = recs.filter(status=REC.PENDING, purchase_order__isnull=True).count()
    rec_system = recs.filter(raised_by__isnull=True).count()
    conversion_rate = round(rec_converted / rec_total * 100) if rec_total else None

    # Low stock with no open order (coverage gap)
    usable = dict(
        MedicineBatch.objects
        .filter(quantity_available__gt=0, expiry_date__gt=today, status="Active", medicine__is_active=True)
        .values("medicine_id").annotate(total=Sum("quantity_available"))
        .values_list("medicine_id", "total")
    )
    open_order_medicines = set(
        PurchaseOrder.objects.filter(status__in=OPEN_PO_STATUSES).values_list("medicine_id", flat=True)
    )
    gaps = []
    for med in Medicine.objects.filter(is_active=True).order_by("medicine_name"):
        stock = usable.get(med.pk, 0)
        level = med.reorder_level or 0
        if stock <= level and med.pk not in open_order_medicines:
            gaps.append({"medicine": med, "stock": stock, "reorder_level": level, "shortfall": level - stock})
    gaps.sort(key=lambda g: g["shortfall"], reverse=True)

    # Stock expiring within 90 days (what a replacement order has to cover)
    expiring = list(
        MedicineBatch.objects
        .filter(quantity_available__gt=0, expiry_date__gt=today,
                expiry_date__lte=today + timedelta(days=90), status="Active", medicine__is_active=True)
        .values("medicine__medicine_name")
        .annotate(units=Sum("quantity_available"), batches=Count("pk"))
        .order_by("-units")[:8]
    )

    return render(request, "procurement/procurement_analytics.html", {
        "total_orders": total_orders,
        "units_ordered": units_ordered,
        "approval_rate": approval_rate,
        "conversion_rate": conversion_rate,
        "rec_total": rec_total,
        "rec_converted": rec_converted,
        "rec_pending": rec_pending,
        "rec_system": rec_system,
        "rec_staff": rec_total - rec_system,
        "status_bars": status_bars,
        "month_cols": month_cols,
        "top_medicines": top_medicines,
        "top_suppliers": top_suppliers,
        "gaps": gaps[:15],
        "gap_count": len(gaps),
        "expiring": expiring,
    })


# ---------------------------------------------------------------- reports
@procurement_only
def procurement_reports_view(request):
    status_filter = request.GET.get("status", "").strip()
    start = parse_date(request.GET.get("start_date", ""))
    end = parse_date(request.GET.get("end_date", ""))
    if start and end and start > end:
        start, end = end, start

    statuses = list(PurchaseOrder.objects.order_by("status").values_list("status", flat=True).distinct())

    queryset = (
        PurchaseOrder.objects
        .select_related("medicine", "supplier", "raised_by", "reviewed_by")
        .order_by("-order_date", "-pk")
    )
    queryset = _order_date_range(queryset, start, end)
    if status_filter in statuses:
        queryset = queryset.filter(status=status_filter)
    else:
        status_filter = ""

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="purchase_orders_{timezone.localdate():%Y%m%d}.csv"'
        )
        writer = csv.writer(response)
        writer.writerow(["Order ID", "Medicine", "Supplier", "Quantity", "Order date",
                         "Raised by", "Status", "Reviewed by", "Decision reason"])
        for po in queryset.iterator():
            writer.writerow([
                po.pk,
                po.medicine.medicine_name if po.medicine else "",
                po.supplier.supplier_name if po.supplier else "",
                po.quantity_ordered,
                _as_date(po.order_date) or "",
                po.raised_by.get_username() if po.raised_by else "",
                po.status,
                po.reviewed_by.get_username() if po.reviewed_by else "",
                po.decision_reason,
            ])
        return response

    summary = queryset.aggregate(orders=Count("pk"), units=Sum("quantity_ordered"))
    by_status = list(
        queryset.order_by().values("status").annotate(orders=Count("pk"), units=Sum("quantity_ordered"))
    )
    for row in by_status:
        row["css"] = STATUS_CLASS.get(row["status"], "pill-muted")

    page_obj = Paginator(queryset, PAGE_SIZE * 2).get_page(request.GET.get("page"))
    for po in page_obj:
        _decorate_po(po)

    return render(request, "procurement/procurement_reports.html", {
        "page_obj": page_obj,
        "purchase_orders": page_obj,
        "statuses": statuses,
        "selected_status": status_filter,
        "start_date": start,
        "end_date": end,
        "summary": summary,
        "by_status": by_status,
        "query_string": _query_string(request),
    })