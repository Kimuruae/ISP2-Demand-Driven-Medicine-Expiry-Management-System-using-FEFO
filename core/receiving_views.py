from datetime import date
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import AuditLog, GoodsReceipt, GoodsReceiptItem, MedicineBatch, PurchaseOrder

def _has_role(user, *roles):
    if user.is_superuser:
        return True
    role_name = (getattr(getattr(user, "role", None), "name", "") or "").strip().casefold()
    return role_name in {r.casefold() for r in roles}

def _require_role(user, *roles):
    if not _has_role(user, *roles):
        raise PermissionDenied("You are not authorised to perform this receiving action.")

@login_required(login_url="/login/")
def receiving_dashboard(request):
    _require_role(request.user, "Store Manager")

    receipts = GoodsReceipt.objects.all()

    items = GoodsReceiptItem.objects.all()

    placed_orders = PurchaseOrder.objects.filter(
        status=PurchaseOrder.Status.PLACED_WITH_SUPPLIER,
        medicine__isnull=False
    )

    pending_inspections = items.filter(
        inspection_status=GoodsReceiptItem.InspectionStatus.PENDING
    )

    accepted_batches = items.filter(
        inspection_status=GoodsReceiptItem.InspectionStatus.ACCEPTED
    )

    rejected_batches = items.filter(
        inspection_status=GoodsReceiptItem.InspectionStatus.REJECTED
    )

    quarantined_batches = items.filter(
        inspection_status=GoodsReceiptItem.InspectionStatus.QUARANTINED
    )

    recent_receipts = receipts.select_related(
        "purchase_order",
        "purchase_order__medicine",
        "purchase_order__supplier",
        "received_by"
    )[:8]

    outstanding_orders = []

    for po in placed_orders.select_related("medicine", "supplier"):
        received = (
            GoodsReceiptItem.objects.filter(
                goods_receipt__purchase_order=po
            ).aggregate(total=Sum("quantity_received"))["total"] or 0
        )

        remaining = po.quantity_ordered - received

        if remaining > 0:
            outstanding_orders.append({
                "order": po,
                "received": received,
                "remaining": remaining,
            })

    context = {
        "total_receipts": receipts.count(),
        "pending_inspections": pending_inspections.count(),
        "accepted_batches": accepted_batches.count(),
        "rejected_batches": rejected_batches.count(),
        "quarantined_batches": quarantined_batches.count(),
        "placed_orders_count": len(outstanding_orders),
        "outstanding_orders": outstanding_orders,
        "recent_receipts": recent_receipts,
    }

    return render(
        request,
        "receiving/receiving_dashboard.html",
        context
    )
@login_required(login_url="/login/")
def goods_receipt_list(request):
    _require_role(request.user, "Store Manager", "Hospital Admin", "Hospital Administrator")
    receipts = (GoodsReceipt.objects.select_related("purchase_order", "purchase_order__medicine",
                "purchase_order__supplier", "received_by").prefetch_related("items")
                .order_by("-received_at"))
    placed_orders = (PurchaseOrder.objects.filter(
        status=PurchaseOrder.Status.PLACED_WITH_SUPPLIER,
        medicine__isnull=False,
    ).select_related("medicine", "supplier").order_by("-order_date"))
    return render(request, "receiving/receipt_list.html", {
        "receipts": receipts,
        "placed_orders": placed_orders,
    })

@login_required(login_url="/login/")
@require_POST
def goods_receipt_create(request):
    _require_role(request.user, "Store Manager")
    try:
        po_id = int(request.POST.get("purchase_order_id", ""))
        delivery_date = date.fromisoformat(request.POST.get("delivery_date", ""))
        reference = request.POST.get("delivery_reference", "").strip()
        notes = request.POST.get("notes", "").strip()
        if delivery_date > timezone.localdate():
            raise ValueError("Delivery date cannot be in the future.")
        with transaction.atomic():
            po = get_object_or_404(PurchaseOrder.objects.select_for_update(),
                pk=po_id, status=PurchaseOrder.Status.PLACED_WITH_SUPPLIER,
                medicine__isnull=False)
            already_recorded = sum(
                item.quantity_received
                for item in GoodsReceiptItem.objects.filter(goods_receipt__purchase_order=po)
            )
            remaining = po.quantity_ordered - already_recorded
            if remaining <= 0:
                raise ValueError("This purchase order has already been fully received.")
            receipt = GoodsReceipt.objects.create(
                purchase_order=po, received_by=request.user,
                delivery_date=delivery_date, delivery_reference=reference, notes=notes,
            )
            AuditLog.objects.create(user=request.user, action="Goods receipt created",
                entity_type="GoodsReceipt", details=f"Receipt {receipt.pk}; PO {po.pk}; remaining order quantity before receipt {remaining}.",
                ip_address=request.META.get("REMOTE_ADDR"))
        messages.success(request, f"Goods Receipt #{receipt.pk} created. Add each delivered batch for inspection.")
        return redirect("goods_receipt_detail", receipt_id=receipt.pk)
    except (ValueError, TypeError) as exc:
        messages.error(request, str(exc) or "Enter valid receipt details.")
        return redirect("goods_receipts")

@login_required(login_url="/login/")
def goods_receipt_detail(request, receipt_id):
    _require_role(request.user, "Store Manager", "Hospital Admin", "Hospital Administrator")
    receipt = get_object_or_404(
        GoodsReceipt.objects.select_related("purchase_order", "purchase_order__medicine", "purchase_order__supplier"),
        pk=receipt_id)
    items = receipt.items.select_related("medicine_batch", "inspected_by").all()
    can_manage = _has_role(request.user, "Store Manager")
    return render(request, "receiving/receipt_detail.html", {
        "receipt": receipt, "items": items, "can_manage": can_manage,
        "today": timezone.localdate(),
    })

@login_required(login_url="/login/")
def goods_receipt_inspect(request, receipt_id):
    """
    Displays all delivered batches associated with a goods receipt.

    Only Store Managers can inspect delivered batches.
    Accepted batches become usable MedicineBatch records.
    Rejected and quarantined batches do not enter usable inventory.
    """

    _require_role(request.user, "Store Manager")

    receipt = get_object_or_404(
        GoodsReceipt.objects.select_related(
            "purchase_order",
            "purchase_order__medicine",
            "purchase_order__supplier",
            "received_by",
        ),
        pk=receipt_id,
    )

    items = receipt.items.select_related(
        "medicine_batch",
        "inspected_by",
    ).order_by("expiry_date", "batch_number")

    pending_status = GoodsReceiptItem.InspectionStatus.PENDING
    accepted_status = GoodsReceiptItem.InspectionStatus.ACCEPTED
    rejected_status = GoodsReceiptItem.InspectionStatus.REJECTED
    quarantined_status = GoodsReceiptItem.InspectionStatus.QUARANTINED

    total_items = items.count()

    pending_count = items.filter(
        inspection_status=pending_status
    ).count()

    accepted_count = items.filter(
        inspection_status=accepted_status
    ).count()

    rejected_count = items.filter(
        inspection_status=rejected_status
    ).count()

    quarantined_count = items.filter(
        inspection_status=quarantined_status
    ).count()

    inspection_decisions = [
        {
            "value": accepted_status,
            "label": "Accept Batch",
        },
        {
            "value": rejected_status,
            "label": "Reject Batch",
        },
        {
            "value": quarantined_status,
            "label": "Quarantine Batch",
        },
    ]

    context = {
        "receipt": receipt,
        "items": items,
        "total_items": total_items,
        "pending_count": pending_count,
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "quarantined_count": quarantined_count,
        "pending_status": pending_status,
        "accepted_status": accepted_status,
        "rejected_status": rejected_status,
        "quarantined_status": quarantined_status,
        "inspection_decisions": inspection_decisions,
        "today": timezone.localdate(),
    }

    return render(
        request,
        "receiving/inspect_receipt.html",
        context,
    )

@login_required(login_url="/login/")
@require_POST
def goods_receipt_add_item(request, receipt_id): #Store manager received batches inspection
    _require_role(request.user, "Store Manager")
    try:
        expiry_date = date.fromisoformat(request.POST.get("expiry_date", ""))
        batch_number = request.POST.get("batch_number", "").strip()
        quantity = int(request.POST.get("quantity_received", ""))
        location = request.POST.get("storage_location", "").strip()
        if not batch_number:
            raise ValueError("Batch number is required.")
        if quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")
        if expiry_date <= timezone.localdate():
            raise ValueError("Expired or same-day-expiring stock cannot be accepted into inventory.")
        with transaction.atomic():
            receipt = get_object_or_404(GoodsReceipt.objects.select_for_update().select_related("purchase_order__medicine"), pk=receipt_id)
            po = receipt.purchase_order
            if po.status != PurchaseOrder.Status.PLACED_WITH_SUPPLIER or not po.medicine_id:
                raise ValueError("Only a placed purchase order with a medicine can be received.")
            recorded = sum(item.quantity_received for item in GoodsReceiptItem.objects.filter(goods_receipt__purchase_order=po))
            if recorded + quantity > po.quantity_ordered:
                raise ValueError(f"This item exceeds the remaining PO quantity. Remaining: {po.quantity_ordered - recorded} units.")
            if MedicineBatch.objects.filter(medicine=po.medicine, batch_number=batch_number).exists():
                raise ValueError("That batch number already exists for this medicine.")
            if GoodsReceiptItem.objects.filter(goods_receipt__purchase_order=po, batch_number=batch_number).exists():
                raise ValueError("That batch number has already been recorded against this purchase order.")
            item = GoodsReceiptItem.objects.create(
                goods_receipt=receipt, batch_number=batch_number,
                quantity_received=quantity, expiry_date=expiry_date,
                storage_location=location,
            )
            AuditLog.objects.create(user=request.user, action="Goods receipt item recorded",
                entity_type="GoodsReceiptItem", details=f"Receipt {receipt.pk}; item {item.pk}; batch {batch_number}; quantity {quantity}; expiry {expiry_date}.",
                ip_address=request.META.get("REMOTE_ADDR"))
        messages.success(request, f"Batch {batch_number} recorded as Pending Inspection. It is not yet usable stock.")
    except (ValueError, TypeError) as exc:
        messages.error(request, str(exc) or "Enter valid batch details.")
    return redirect("goods_receipt_detail", receipt_id=receipt_id)


@login_required(login_url="/login/")
@require_POST
def goods_receipt_inspect_item(request, item_id):
    _require_role(request.user, "Store Manager")
    decision = request.POST.get("decision", "").strip()
    notes = request.POST.get("inspection_notes", "").strip()
    valid = {GoodsReceiptItem.InspectionStatus.ACCEPTED,
             GoodsReceiptItem.InspectionStatus.REJECTED,
             GoodsReceiptItem.InspectionStatus.QUARANTINED}
    if decision not in valid:
        messages.error(request, "Select a valid inspection decision.")
        item = get_object_or_404(GoodsReceiptItem, pk=item_id)
        return redirect("goods_receipt_detail", receipt_id=item.goods_receipt_id)
    try:
        with transaction.atomic():
            item = get_object_or_404(GoodsReceiptItem.objects.select_for_update().select_related(
                "goods_receipt__purchase_order__medicine"), pk=item_id)
            if item.inspection_status != GoodsReceiptItem.InspectionStatus.PENDING:
                raise ValueError("This receipt item has already been inspected. Its decision cannot be overwritten.")
            if decision == GoodsReceiptItem.InspectionStatus.ACCEPTED:
                if item.expiry_date <= timezone.localdate():
                    raise ValueError("An expired batch cannot be accepted.")
                medicine = item.goods_receipt.purchase_order.medicine
                if not medicine or not medicine.is_active:
                    raise ValueError("The purchase order does not reference an active medicine.")
                if MedicineBatch.objects.filter(medicine=medicine, batch_number=item.batch_number).exists():
                    raise ValueError("A batch with this number already exists for this medicine.")
                batch = MedicineBatch.objects.create(
                    medicine=medicine, batch_number=item.batch_number,
                    quantity_received=item.quantity_received,
                    quantity_available=item.quantity_received,
                    received_date=item.goods_receipt.delivery_date,
                    expiry_date=item.expiry_date,
                    storage_location=item.storage_location,
                    status="Active",
                )
                item.medicine_batch = batch
            item.inspection_status = decision
            item.inspected_by = request.user
            item.inspected_at = timezone.now()
            item.inspection_notes = notes
            item.save()
            AuditLog.objects.create(user=request.user, action=f"Goods receipt item {decision.lower()}",
                entity_type="GoodsReceiptItem", details=f"Item {item.pk}; batch {item.batch_number}; decision {decision}; notes: {notes or 'None'}.",
                ip_address=request.META.get("REMOTE_ADDR"))
        messages.success(request, "Inspection decision saved. Accepted stock is now available to FEFO inventory." if decision == GoodsReceiptItem.InspectionStatus.ACCEPTED else f"Item marked {decision.lower()}; it has not entered usable inventory.")
    except (ValueError, ValidationError) as exc:
        messages.error(request, str(exc))
    return redirect("goods_receipt_detail", receipt_id=item.goods_receipt_id)
