from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.password_validation import validate_password
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.contrib import messages
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.http import HttpResponseForbidden
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.db import transaction
from django.db.models import Count, Sum, Q, F
from django.db.models.functions import TruncMonth
from decimal import Decimal, InvalidOperation
from functools import wraps
from datetime import date,timedelta
from django.views.decorators.http import require_POST
from .fefo_engine import FEFOEngine
from .forecasting_engine import ForecastingEngine
from django.urls import reverse
from django.core.mail import send_mail
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode

from .models import (AuditLog,DemandForecast,DispensingTransaction,ExpiryAlert,UserAlert,Medicine,MedicineBatch,
                     ProcurementRecommendation,PurchaseOrder,Role,Supplier,SystemSetting)

def route_user_by_role(user):
    if user.is_superuser:return redirect("system_admin_dashboard")
    role = getattr(user, "role", None)
    role_name = (getattr(role, "name", "") or "").strip().casefold()

    destinations = {
        "system administrator": "system_admin_dashboard",
        "pharmacist": "pharmacist_dashboard",
        "store manager": "inventory",
        "procurement officer": "procurement",
        "hospital admin": "admin_dashboard",
        "hospital administrator": "admin_dashboard",
    }
    destination = destinations.get(role_name)
    if destination: return redirect(destination)
    return HttpResponseForbidden(f"No page is configured for role: {role_name or 'no role assigned'}.")

@login_required(login_url="/login/")
def profile_view(request):
    current_user = request.user
    password_form = PasswordChangeForm(current_user)

    if request.method == "POST":
        password_form = PasswordChangeForm(current_user,request.POST)

        if password_form.is_valid():
            updated_user = password_form.save()

            AuditLog.objects.create(
                user=updated_user,
                action="Password changed",
                entity_type="Authentication",
                details="User changed their own password.",
                ip_address=request.META.get("REMOTE_ADDR"),
            )

            # Keep the user logged in after changing their password.
            update_session_auth_hash(request, updated_user)
            messages.success( request,"Your password has been changed successfully.")
            return redirect("profile")
        messages.error(request,"Please correct the errors in the password form.")

    context = {
        "profile_user": current_user,
        "assigned_role": getattr(current_user, "role", None),
        "password_form": password_form,
    }
    return render(request, "profile.html", context)

#Checking the users roles
def role_required(*allowed_roles):
    def decorator(view_func):
        @login_required(login_url="/login/")
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.user.is_superuser: return view_func(request, *args, **kwargs)
            role = getattr(request.user, "role", None)
            role_name = (getattr(role, "name", "") or "").strip().casefold()
            permitted_roles = {name.strip().casefold() for name in allowed_roles}

            if role_name not in permitted_roles:raise PermissionDenied("You do not have permission to access this page.")
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator

def is_pharmacist(user) ->bool:
    if not user.is_authenticated:return False
    if user.is_superuser: return True
    role = getattr(user, 'role', None)
    role_name = (getattr(role, "name", "") or "").strip().casefold()
    return role_name == "pharmacist"

def is_store_manager(user) -> bool:
    if not user.is_authenticated:return False
    if user.is_superuser: return True
    role = getattr(user, 'role', None)
    role_name = (getattr(role, "name", "") or "").strip().casefold()
    return role_name == "store manager"

def is_procurement_officer(user) -> bool:
    if not user.is_authenticated:return False
    if user.is_superuser: return True
    role = getattr(user, 'role', None)
    role_name = (getattr(role, "name", "") or "").strip().casefold()
    return role_name == "procurement officer"

def is_hospital_admin(user):
    if not user.is_authenticated:return False
    if user.is_superuser: return True
    role = getattr(user, "role", None)
    role_name = ( getattr(role, "name", "") or "").strip().casefold()
    return role_name in {"hospital admin","hospital administrator",}

# USER ACCOUNT EMAIL ACTIVATION
def activate_account_view(request, uidb64, token):
    user = get_user_model()
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        target_user = user.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, user.DoesNotExist):
        target_user = None

    if target_user is None:
        messages.error(request, "Invalid account activation link.")
        return redirect("login")

    if target_user.is_active:
        messages.info(request, "This account has already been activated.")
        return redirect("login")

    if not default_token_generator.check_token(target_user, token):
        messages.error(
            request,
            "This activation link is invalid or has expired. "
            "Contact your System Administrator."
        )
        return redirect("login")

    if request.method == "POST":
        password = request.POST.get("password", "")
        confirm_password = request.POST.get("confirm_password", "")

        if not password or not confirm_password:
            messages.error(request, "Both password fields are required.")

        elif password != confirm_password:
            messages.error(request, "The passwords do not match.")

        else:
            try:
                validate_password(password, target_user)

                target_user.set_password(password)
                target_user.is_active = True
                target_user.save(update_fields=["password", "is_active"])

                AuditLog.objects.create(
                    user=target_user,
                    action="Account activated",
                    entity_type="User",
                    details=(
                        f"User {target_user.username} "
                        "completed email activation."
                    ),
                    ip_address=request.META.get("REMOTE_ADDR"),
                )

                messages.success(request,"Your account has been activated. You can now log in.")
                return redirect("login")

            except ValidationError as exc:
                for error in exc.messages:messages.error(request, error)

    return render(
        request,"system_admin/activate_account.html",{"target_user": target_user},)

@ensure_csrf_cookie
@csrf_protect
def login_view(request):
        # If already authenticated, send the user to their own workspace.
        if request.user.is_authenticated:
            return route_user_by_role(request.user)

        if request.method == "POST":
            username_input = request.POST.get("username", "").strip()
            password_input = request.POST.get("password", "")
            user = authenticate(request,username=username_input,password=password_input )

            if user is not None:
                login(request, user)
                request.session.set_expiry(0)
                messages.success(request,f"Welcome, {user.username}. Login successful.")

                return route_user_by_role(user)  #Redirect according to the user's role.
            messages.error(request,"Invalid username or password credentials.")
        return render(request, "public/login.html")

@require_POST
@login_required(login_url="/login/")
def logout_view(request):
    username = request.user.username
    AuditLog.objects.create(
        user=request.user,
        action="user logout",
        entity_type="Authentication",
        details=f"user '{username}' logged out.",
        ip_address=request.META.get("REMOTE_ADDR"),
    )

    logout(request)
    messages.info(request, "Logged out successfully.")
    return redirect("login")

def home_redirect(request):
    if request.user.is_authenticated: return route_user_by_role(request.user)
    return render(request, 'public/index.html')

def about(request):
    return render(request, 'public/about.html')

def features(request):
    return render(request, 'public/features.html')

def contact(request):
    return render(request, 'public/contact.html')

@role_required("pharmacist")
def dispense_view(request):
    if request.method == "POST":
        medicine_id = request.POST.get("medicine_id", "").strip()
        quantity_raw = request.POST.get("quantity", "").strip()
        duration_raw = request.POST.get("prescription_duration_days", "").strip()
        patient_identifier = request.POST.get("patient_identifier", "").strip()
        selected_batch_id = request.POST.get("batch_id", "").strip() or None
        override_reason = request.POST.get("override_reason", "").strip()

        try:
            if not medicine_id:
                raise ValueError("Select a medicine.")

            try:
                duration_days = int(duration_raw)
            except (TypeError, ValueError):
                raise ValueError("Enter a valid prescription duration in days.")
            if duration_days <= 0:
                raise ValueError("Prescription duration must be greater than zero.")

            try:
                quantity = int(quantity_raw)
            except (TypeError, ValueError):
                raise ValueError("Enter a valid dispensing quantity.")
            if quantity <= 0:
                raise ValueError("Dispensing quantity must be greater than zero.")

            transactions = FEFOEngine.dispense_medicine(
                medicine_id=medicine_id,
                total_qty_to_dispense=quantity,          # FIX: was quantity_raw
                user=request.user,
                selected_batch_id=selected_batch_id,
                notes=override_reason,
                patient_identifier=patient_identifier,
                prescription_duration_days=duration_days,
            )
            total_dispensed = sum(tx.quantity_dispensed for tx in transactions)

            AuditLog.objects.create(
                user=request.user,
                action="Medicine dispensed",
                entity_type="DispensingTransaction",
                details=(
                    f"Medicine ID={medicine_id}; "
                    f"quantity={total_dispensed}; "
                    f"prescription_duration_days={duration_days}; "
                    f"transaction IDs="
                    f"{', '.join(str(tx.pk) for tx in transactions)}"
                ),
            )
            messages.success(
                request, f"Dispensing completed: {total_dispensed} units recorded."
            )
        except (ValueError, TypeError) as exc:
            messages.error(request, str(exc))
        except Medicine.DoesNotExist:
            messages.error(request, "The selected medicine was not found.")

        return redirect("dispense")                      # FIX: was "pharmacist/dispense.html"

    today = timezone.localdate()
    medicines = Medicine.objects.filter(is_active=True).order_by("medicine_name")
    batches = (
        MedicineBatch.objects.filter(
            quantity_available__gt=0,
            status="Active",
            expiry_date__gt=today,
            medicine__is_active=True,
        )
        .select_related("medicine")
        .order_by("expiry_date", "id")
    )
    return render(
        request,
        "pharmacist/dispense.html",
        {"medicines": medicines, "batches": batches},
    )

@login_required(login_url="/login/")
def pharmacist_dashboard_view(request): #displays the pharmacist's dashboard with stock eligibilty, expiry risk, FEFO ques and recent dispensing activities
    # Restrict this dashboard to pharmacists and system administrators.
    role = getattr(getattr(request.user, "role", None), "name", "")
    role = str(role).strip().casefold()

    if not (request.user.is_superuser or role in {"pharmacist", "hospital admin", "system administrator", "system admin"}):
        raise PermissionDenied("You are not authorised to access this dashboard.")

    today = timezone.localdate()
    day_30 = today + timedelta(days=30)
    day_60 = today + timedelta(days=60)
    day_90 = today + timedelta(days=90)

    active_medicines = Medicine.objects.filter(is_active=True)
#Batches eligible for dispensing must be available and must not  be expired
    eligible_batches = MedicineBatch.objects.filter(
        medicine__is_active=True,
        quantity_available__gt=0,
        expiry_date__gt=today,
        status="Active",
    )
    eligible_medicine_count = (eligible_batches.values("medicine_id").distinct().count())

#Expiry risk monitoring
    near_expiry_count = eligible_batches.filter(expiry_date__lte=day_90).count()
    expiry_30_count = eligible_batches.filter(expiry_date__lte=day_30).count()
    expiry_60_count = eligible_batches.filter(expiry_date__lte=day_60).count()
    expiry_90_count = near_expiry_count
#Review of expired batches in stock
    expired_count = MedicineBatch.objects.filter(quantity_available__gt=0,expiry_date__lte=today,).count()

 #FEFO algorithm - medicine expiring earliest will be the first to be recommended for dispensing if it's not expired
    fefo_queue = (eligible_batches.select_related("medicine").order_by("expiry_date", "id")[:8])
    recent_transactions = (
        DispensingTransaction.objects.select_related("medicine","batch","dispensed_by",)
        .order_by("-dispensed_at", "-id")[:8]
    )

    # This measures transactions recorded as FEFO versus overrides.
    # It is a basic compliance indicator, not an independent verification
    # that every transaction selected the correct batch.
    transaction_stats = (DispensingTransaction.objects.aggregate(total=Count("id"),))
    total_transactions = transaction_stats["total"]
    override_count = DispensingTransaction.objects.filter(is_override=True).count()
    fefo_compliance = (
        round(((total_transactions - override_count) / total_transactions) * 100)
        if total_transactions else 100)

    context = {
        "eligible_medicine_count": eligible_medicine_count,
        "near_expiry_count": near_expiry_count,
        "expired_count": expired_count,
        "fefo_compliance": fefo_compliance,
        "expiry_30_count": expiry_30_count,
        "expiry_60_count": expiry_60_count,
        "expiry_90_count": expiry_90_count,
        "fefo_queue": fefo_queue,
        "recent_transactions": recent_transactions,
    }

    return render(request, "pharmacist/pharmacist_dashboard.html", context)

# PHARMACIST DISPENSING REPORTS
@login_required(login_url="/login/")
@role_required("Pharmacist")
def dispense_reports_view(request):
    transactions = (
        DispensingTransaction.objects
        .select_related("medicine", "batch", "dispensed_by")
        .order_by("-dispensed_at")
    )

    context = {
        "transactions": transactions,
        "total_transactions": transactions.count(),
        "total_quantity_dispensed": (
            transactions.aggregate(total=Sum("quantity_dispensed"))["total"] or 0
        ),
        "fefo_overrides": transactions.filter(is_override=True).count(),
    }
    return render(request,"pharmacist/dispense_reports.html",context,)

@role_required("Store Manager")
def store_manager_inventory_view(request):
    today = timezone.localdate()
    if request.method == "POST":
        messages.info(request,"Stock must be received through a placed Purchase Order and Goods Receipt.")
        return redirect("goods_receipts")

    # GET: Display current inventory
    batches = MedicineBatch.objects.select_related(
        "medicine"
    ).filter(
        quantity_available__gt=0,
        expiry_date__gt=today,
        status="Active",
        medicine__is_active=True
    ).order_by("expiry_date")

    context = {"batches": batches,"today": today,}
    return render(request, "store_manager/inventory.html", context)

@login_required(login_url="/login/")
@role_required("Store Manager")
def inventory_reports_view(request):
    today = timezone.localdate()
    all_batches = (MedicineBatch.objects.select_related("medicine").order_by("expiry_date", "medicine__medicine_name"))
    total_units = (all_batches.filter(quantity_available__gt=0).aggregate(total=Sum("quantity_available"))["total"] or 0)
    context = {
        "all_batches": all_batches,
        "total_batches": all_batches.count(),
        "total_units": total_units,
        "expired_batches": all_batches.filter(expiry_date__lt=today,quantity_available__gt=0,).count(),
        "expiring_soon": all_batches.filter(expiry_date__gte=today,expiry_date__lte=today + timedelta(days=30),quantity_available__gt=0,).count(),
        "today": today,
    }
    return render(request, "store_manager/inventory_reports.html", context)

@login_required(login_url="/login/")
@role_required("Store Manager")
def inventory_alerts_view(request):
    today = timezone.localdate()
    warning_date = today + timedelta(days=30)

    context = {
        "inventory_alerts_mode": True,
        "role_name": "Store Manager",
        "expired_batches": (MedicineBatch.objects.filter(expiry_date__lte=today,quantity_available__gt=0,)
            .select_related("medicine")
            .order_by("expiry_date")
        ),
        "expiring_batches": (
            MedicineBatch.objects.filter(
                expiry_date__gt=today,
                expiry_date__lte=warning_date,
                quantity_available__gt=0,
            )
            .select_related("medicine")
            .order_by("expiry_date")
        ),
        "out_of_stock_batches": (
            MedicineBatch.objects.filter(
                quantity_available__lte=0,
            )
            .select_related("medicine")
            .order_by("expiry_date")
        ),
        "today": today,
    }
    return render(request, "alerts.html", context)

@login_required(login_url="/login/")
@role_required("Store Manager")
def inventory_recommendations_view(request):
    today = timezone.localdate()
    recommendations = []
    medicines = Medicine.objects.filter(is_active=True).order_by("medicine_name")

    for medicine in medicines:
        available_stock = (
            MedicineBatch.objects.filter(
                medicine=medicine,
                expiry_date__gt=today,
                quantity_available__gt=0,
                status="Active",
            )
            .aggregate(total=Sum("quantity_available"))["total"] or 0
        )

        threshold = medicine.reorder_level

        if available_stock <= threshold:
            recommendations.append({
                "medicine": medicine,
                "available_stock": available_stock,
                "low_stock_threshold": threshold,
                "recommended_action": (
                    "Urgent procurement review"
                    if available_stock == 0
                    else "Review stock and procurement needs"
                ),
            })

    recommendation_history = (
        ProcurementRecommendation.objects.filter(raised_by=request.user,).select_related("medicine").order_by("-created_at"))

    context = {
        "medicines": medicines,
        "recommendations": recommendations,
        "recommendation_history": recommendation_history,
        "low_stock_threshold": 30,
        "today": today,
    }
    return render(request,"store_manager/inventory_recommendations.html",context,)

@login_required(login_url="/login/")
@role_required("Store Manager")
def store_manager_recommendations_view(request):
    if request.method != "POST": return redirect("inventory_recommendations")
    try:
        medicine_id = request.POST.get("medicine_id", "").strip()
        quantity = int(request.POST.get("recommended_quantity", "0"))
        urgency = request.POST.get("urgency_level", "").strip().upper()
        reasoning = request.POST.get("justification", "").strip()

        if quantity <= 0: raise ValueError("Recommended quantity must be greater than zero.")
        valid_urgencies = {
            ProcurementRecommendation.Urgency.LOW,
            ProcurementRecommendation.Urgency.MEDIUM,
            ProcurementRecommendation.Urgency.HIGH,
        }
        if urgency not in valid_urgencies:raise ValueError("Select a valid urgency level.")
        if not reasoning:raise ValueError("Provide a justification for the recommendation.")

        medicine = get_object_or_404(Medicine,id=medicine_id,is_active=True,)
        recommendation = ProcurementRecommendation.objects.create(
            medicine=medicine,
            recommended_quantity=quantity,
            urgency_level=urgency,
            reasoning=reasoning,
            raised_by=request.user,
            status=ProcurementRecommendation.Status.PENDING,
        )

        AuditLog.objects.create(
            user=request.user,
            action="Procurement recommendation raised",
            entity_type="ProcurementRecommendation",
            details=(
                f"Recommendation ID: {recommendation.id}; "
                f"Medicine: {medicine.medicine_name}; "
                f"Quantity: {quantity}; "
                f"Urgency: {urgency}"
            ),
        )
        messages.success(request,f"Recommendation for {medicine.medicine_name} submitted to Procurement.",)
    except (ValueError, TypeError) as exc:messages.error(request, str(exc))
    return redirect("inventory_recommendations")

@login_required(login_url="/login/")
@role_required("Procurement Officer")
@user_passes_test(is_procurement_officer, login_url="login", redirect_field_name=None,)
def procurement_dashboard_view(request):
    if request.method == "POST":
        medicine_id = request.POST.get("medicine_id", "").strip()
        quantity_text = request.POST.get("quantity", "").strip()
        supplier_name = request.POST.get("supplier_name", "").strip()
        rec_id = request.POST.get("recommendation_id", "").strip()

        try:
            quantity = int(quantity_text)
            if quantity <= 0:
                raise ValueError("Quantity must be greater than zero.")
            if not supplier_name:
                raise ValueError("Supplier name is required.")

            medicine = get_object_or_404(Medicine, id=medicine_id, is_active=True,)

            with transaction.atomic():
                recommendation = None

                if rec_id:
                    recommendation = get_object_or_404(
                        ProcurementRecommendation.objects.select_for_update(of=("self",)).filter(
                            id=rec_id,
                            medicine=medicine,
                            status=ProcurementRecommendation.Status.PENDING,
                            purchase_order__isnull=True,
                        )
                    )

                supplier, _ = Supplier.objects.get_or_create(supplier_name=supplier_name,)
                PurchaseOrder.objects.create(
                    medicine=medicine,
                    supplier=supplier,
                    recommendation=recommendation,
                    quantity_ordered=quantity,
                    raised_by=request.user,
                    status=PurchaseOrder.Status.PENDING_ADMIN_REVIEW,
                )

            messages.success(
                request,
                f"Purchase order for {medicine.medicine_name} forwarded to hospital admin.",
            )
        except (ValueError, TypeError) as exc:
            messages.error(request, str(exc))
        return redirect("procurement")                      # FIX: was "procurement/procurement.html"

    today = timezone.localdate()
    medicines = Medicine.objects.filter(is_active=True).order_by("medicine_name")

    # A recommendation disappears from the pending list once a PO is raised from it.
    recommendations = (
        ProcurementRecommendation.objects.filter(
            status=ProcurementRecommendation.Status.PENDING,
            purchase_order__isnull=True,
        )
        .select_related("medicine", "forecast")
        .order_by("-created_at")
    )

    # Latest saved forecast per medicine, with usable stock and stock nearing expiry.
    latest_forecasts = (
        DemandForecast.objects.filter(medicine__is_active=True)
        .select_related("medicine")
        .order_by("medicine_id", "-generated_at")
    )
    forecasts = []
    seen_medicines = set()

    for forecast in latest_forecasts:
        if forecast.medicine_id in seen_medicines:
            continue
        seen_medicines.add(forecast.medicine_id)

        usable_batches = list(forecast.medicine.get_fefo_batches())
        forecasts.append({
            "medicine": forecast.medicine,
            "forecast": forecast,
            "current_stock": sum(b.quantity_available for b in usable_batches),
            "expiring_90": sum(
                b.quantity_available for b in usable_batches
                if b.expiry_date <= today + timedelta(days=90)
            ),
            "avg_monthly_dispensed": forecast.moving_avg_3month,
            "forecasted_demand": forecast.forecasted_demand_quantity,
        })

    return render(
        request,
        "procurement/procurement.html",
        {"medicines": medicines, "recommendations": recommendations, "forecasts": forecasts},
    )

@login_required(login_url="/login/")
@role_required("Procurement Officer")
def place_supplier_order_view(request, po_id):
    if request.method != "POST":
        messages.error(request, "Supplier orders must be submitted using POST.",)
        return redirect("procurement_orders")

    po = get_object_or_404(
        PurchaseOrder.objects.select_related("supplier"),
        id=po_id,
        status=PurchaseOrder.Status.APPROVED,
    )
    po.status = PurchaseOrder.Status.PLACED_WITH_SUPPLIER
    po.save(update_fields=["status"])

    messages.success(
        request,
        f"Purchase Order #{po.id} placed with {po.supplier.supplier_name}.",
    )
    return redirect("procurement_orders")

@role_required('Hospital Admin', 'Hospital Administrator')
def hospital_admin_dashboard_view(request):
    today = timezone.localdate()
    near_expiry_date = today + timedelta(days=30)

    # INVENTORY OVERVIEW
    active_medicines = Medicine.objects.filter(is_active=True)
    active_batches = MedicineBatch.objects.filter(quantity_available__gt=0,expiry_date__gte=today)
    total_medicines = active_medicines.count()
    total_batches = active_batches.count()
    total_stock_volume = (active_batches.aggregate(total=Sum('quantity_available'))['total'] or 0)

    # EXPIRY MONITORING
    expired_batches = MedicineBatch.objects.filter(quantity_available__gt=0,expiry_date__lt=today)
    near_expiry_batches = MedicineBatch.objects.filter(
        quantity_available__gt=0,
        expiry_date__gte=today,
        expiry_date__lte=near_expiry_date
    )

    expired_count = expired_batches.count()
    near_expiry_count = near_expiry_batches.count()

    # DISPENSING OVERVIEW
    total_dispenses = DispensingTransaction.objects.count()
    fefo_overrides = DispensingTransaction.objects.filter(is_override=True).count()
    fefo_compliant = total_dispenses - fefo_overrides

    # ALERTS
    active_alerts_count = ExpiryAlert.objects.filter(is_resolved=False).count()
    # PROCUREMENT OVERVIEW
    pending_pos = (
        PurchaseOrder.objects.filter(status=PurchaseOrder.Status.PENDING_ADMIN_REVIEW)
        .select_related("medicine", "raised_by")
        .order_by("-order_date")
    )
    pending_po_count = pending_pos.count()
    approved_po_count = PurchaseOrder.objects.filter(
        status=PurchaseOrder.Status.APPROVED).count()

    placed_po_count = PurchaseOrder.objects.filter(
        status=PurchaseOrder.Status.PLACED_WITH_SUPPLIER).count()

    rejected_po_count = PurchaseOrder.objects.filter(
        status=PurchaseOrder.Status.REJECTED).count()

    # PROCUREMENT RECOMMENDATIONS
    pending_recommendations = ProcurementRecommendation.objects.filter(
        status=ProcurementRecommendation.Status.PENDING).count()

    # RECENT DISPENSING ACTIVITY
    global_transactions = (DispensingTransaction.objects
        .select_related('medicine', 'batch', 'dispensed_by')
        .order_by('-dispensed_at')[:10]
    )

    # BATCHES FOR THE DASHBOARD TABLE
    batches = (
        MedicineBatch.objects
        .filter(quantity_available__gt=0)
        .select_related('medicine')
        .order_by('expiry_date')
    )

    context = {
        # Inventory
        "total_medicines": total_medicines,
        "total_batches": total_batches,
        "total_stock_volume": total_stock_volume,

        # Expiry
        "expired_count": expired_count,
        "near_expiry_count": near_expiry_count,
        "expired_batches": expired_batches,
        "near_expiry_batches": near_expiry_batches,

        # Dispensing
        "total_dispenses": total_dispenses,
        "fefo_overrides": fefo_overrides,
        "fefo_compliant": fefo_compliant,

        # Alerts
        "active_alerts_count": active_alerts_count,

        # Procurement
        "pending_pos": pending_pos,
        "pending_po_count": pending_po_count,
        "approved_po_count": approved_po_count,
        "placed_po_count": placed_po_count,
        "rejected_po_count": rejected_po_count,
        "pending_recommendations": pending_recommendations,

        # Activity and stock
        "today": today,
        "near_expiry_date": near_expiry_date,
        "global_transactions": global_transactions,
        "batches": batches,
    }
    return render(request, "hospital_admin/dashboard.html", context)

@login_required
@role_required("Hospital Admin", "Hospital Administrator")
def hospital_admin_analytics_view(request):
        from datetime import date, timedelta
        from django.db.models import Sum, Count, Q, F
        from django.db.models.functions import TruncMonth
        from django.utils import timezone
        from django.shortcuts import render

        today = timezone.localdate()
        near_expiry_date = today + timedelta(days=30)

        # --------------------------------------------------
        # 1. INVENTORY OVERVIEW
        # --------------------------------------------------

        total_medicines = Medicine.objects.count()
        total_batches = MedicineBatch.objects.count()

        total_stock_volume = (
                MedicineBatch.objects.aggregate(
                    total=Sum("quantity_available")
                )["total"] or 0
        )

        stock_batches = MedicineBatch.objects.filter(
            quantity_available__gt=0
        )

        expired_count = stock_batches.filter(
            expiry_date__lt=today
        ).count()

        near_expiry_count = stock_batches.filter(
            expiry_date__gte=today,
            expiry_date__lte=near_expiry_date
        ).count()

        other_batches_count = stock_batches.filter(
            expiry_date__gt=near_expiry_date
        ).count()

        # --------------------------------------------------
        # 2. DISPENSING AND FEFO PERFORMANCE
        # --------------------------------------------------

        total_dispenses = DispensingTransaction.objects.count()

        fefo_overrides = DispensingTransaction.objects.filter(
            is_override=True
        ).count()

        fefo_compliant = total_dispenses - fefo_overrides

        fefo_compliance_rate = (
            round((fefo_compliant / total_dispenses) * 100, 2)
            if total_dispenses else 0
        )

        # --------------------------------------------------
        # 3. GENERATE PREVIOUS 12 CALENDAR MONTHS
        # --------------------------------------------------

        month_periods = []

        for offset in range(11, -1, -1):
            month_index = today.year * 12 + today.month - 1 - offset
            year = month_index // 12
            month = month_index % 12 + 1

            month_periods.append(date(year, month, 1))

        start_month = month_periods[0]

        # --------------------------------------------------
        # 4. MONTHLY MEDICINE CONSUMPTION
        # --------------------------------------------------

        monthly_consumption = (
            DispensingTransaction.objects
            .filter(dispensed_at__gte=start_month)
            .annotate(month=TruncMonth("dispensed_at"))
            .values("month")
            .annotate(
                total_quantity=Sum("quantity_dispensed"),
                transaction_count=Count("pk")
            )
            .order_by("month")
        )

        consumption_lookup = {
            item["month"].strftime("%Y-%m"): item
            for item in monthly_consumption
        }

        consumption_labels = []
        consumption_values = []
        consumption_transaction_counts = []

        for month in month_periods:
            month_key = month.strftime("%Y-%m")
            month_data = consumption_lookup.get(month_key, {})

            consumption_labels.append(month.strftime("%b %Y"))

            consumption_values.append(
                float(month_data.get("total_quantity") or 0)
            )

            consumption_transaction_counts.append(
                month_data.get("transaction_count", 0)
            )

        # --------------------------------------------------
        # 5. MOST CONSUMED MEDICINES
        # --------------------------------------------------

        top_consumed_medicines = (
            DispensingTransaction.objects
            .values("medicine__medicine_name")
            .annotate(
                total_quantity=Sum("quantity_dispensed"),
                transaction_count=Count("pk")
            )
            .order_by("-total_quantity")[:10]
        )

        top_medicine_labels = [
            item["medicine__medicine_name"]
            for item in top_consumed_medicines
        ]

        top_medicine_values = [
            float(item["total_quantity"] or 0)
            for item in top_consumed_medicines
        ]

        # --------------------------------------------------
        # 6. LOW-STOCK AND REORDER MONITORING
        # --------------------------------------------------

        usable_stock = (
            MedicineBatch.objects
            .filter(
                quantity_available__gt=0,
                expiry_date__gte=today
            )
            .values("medicine_id")
            .annotate(
                current_stock=Sum("quantity_available")
            )
        )

        stock_lookup = {
            item["medicine_id"]: item["current_stock"] or 0
            for item in usable_stock
        }

        low_stock_medicines = []

        active_medicines = Medicine.objects.filter(
            is_active=True
        )

        for medicine in active_medicines:
            current_stock = stock_lookup.get(medicine.pk, 0)
            reorder_level = medicine.reorder_level or 0

            if current_stock < reorder_level:
                low_stock_medicines.append({
                    "medicine_name": medicine.medicine_name,
                    "current_stock": current_stock,
                    "reorder_level": reorder_level,
                    "stock_shortfall": reorder_level - current_stock,
                })

        low_stock_medicines.sort(
            key=lambda item: item["stock_shortfall"],
            reverse=True
        )

        total_low_stock_medicines = len(low_stock_medicines)

        # --------------------------------------------------
        # 7. PROCUREMENT STATUS OVERVIEW
        # --------------------------------------------------

        pending_po_count = PurchaseOrder.objects.filter(
            status=PurchaseOrder.Status.PENDING_ADMIN_REVIEW
        ).count()

        approved_po_count = PurchaseOrder.objects.filter(
            status=PurchaseOrder.Status.APPROVED
        ).count()

        placed_po_count = PurchaseOrder.objects.filter(
            status=PurchaseOrder.Status.PLACED_WITH_SUPPLIER
        ).count()

        rejected_po_count = PurchaseOrder.objects.filter(
            status=PurchaseOrder.Status.REJECTED
        ).count()

        # --------------------------------------------------
        # 8. MONTHLY PROCUREMENT ACTIVITY
        # --------------------------------------------------

        monthly_procurement = (
            PurchaseOrder.objects
            .filter(order_date__gte=start_month)
            .annotate(month=TruncMonth("order_date"))
            .values("month")
            .annotate(
                order_count=Count("pk"),
                quantity_ordered=Sum("quantity_ordered")
            )
            .order_by("month")
        )

        procurement_lookup = {
            item["month"].strftime("%Y-%m"): item
            for item in monthly_procurement
        }

        procurement_labels = []
        procurement_order_values = []
        procurement_quantity_values = []

        for month in month_periods:
            month_key = month.strftime("%Y-%m")
            month_data = procurement_lookup.get(month_key, {})

            procurement_labels.append(month.strftime("%b %Y"))

            procurement_order_values.append(
                month_data.get("order_count", 0)
            )

            procurement_quantity_values.append(
                float(month_data.get("quantity_ordered") or 0)
            )

        # --------------------------------------------------
        # 9. DEMAND FORECASTING
        # --------------------------------------------------

        forecast_field_names = {
            field.name
            for field in DemandForecast._meta.get_fields()
        }

        forecast_quantity_field = next(
            (
                field_name
                for field_name in (
                "forecasted_quantity",
                "forecasted_demand_quantity"
            )
                if field_name in forecast_field_names
            ),
            None
        )

        recent_forecasts = (
            DemandForecast.objects
            .select_related("medicine")
            .order_by("-forecast_period_start")
        )

        if forecast_quantity_field:
            if forecast_quantity_field != "forecasted_quantity":
                recent_forecasts = recent_forecasts.annotate(
                    forecasted_quantity=F(forecast_quantity_field)
                )

        recent_forecasts = recent_forecasts[:10]

        forecast_labels = []
        historical_demand = []
        forecast_demand = []

        for forecast in recent_forecasts:
            forecast_labels.append(
                f"{forecast.medicine.medicine_name} "
                f"({forecast.forecast_period_start:%b %Y})"
            )

            actual_quantity = getattr(
                forecast,
                "actual_demand_quantity",
                None
            )

            forecast_quantity = getattr(
                forecast,
                "forecasted_quantity",
                None
            )

            historical_demand.append(
                float(actual_quantity)
                if actual_quantity is not None else None
            )

            forecast_demand.append(
                float(forecast_quantity)
                if forecast_quantity is not None else None
            )

        # --------------------------------------------------
        # 10. RECENT BATCHES AND EXPIRY MONITORING
        # --------------------------------------------------

        batches = (
            MedicineBatch.objects
            .select_related("medicine")
            .filter(quantity_available__gt=0)
            .order_by("expiry_date")[:20]
        )

        # --------------------------------------------------
        # 11. CHART DATA
        # --------------------------------------------------

        analytics_chart_data = {
            # Inventory expiry
            "expired": expired_count,
            "near_expiry": near_expiry_count,
            "other_batches": other_batches_count,

            # FEFO
            "fefo_compliant": fefo_compliant,
            "fefo_overrides": fefo_overrides,

            # Procurement status
            "pending_pos": pending_po_count,
            "approved_pos": approved_po_count,
            "placed_pos": placed_po_count,
            "rejected_pos": rejected_po_count,

            # Monthly consumption
            "consumption_labels": consumption_labels,
            "consumption_values": consumption_values,
            "consumption_transaction_counts": consumption_transaction_counts,

            # Most consumed medicines
            "top_medicine_labels": top_medicine_labels,
            "top_medicine_values": top_medicine_values,

            # Demand forecasts
            "forecast_labels": forecast_labels,
            "historical_demand": historical_demand,
            "forecast_demand": forecast_demand,

            # Monthly procurement
            "procurement_labels": procurement_labels,
            "procurement_order_values": procurement_order_values,
            "procurement_quantity_values": procurement_quantity_values,
        }

        # --------------------------------------------------
        # 12. PAGE CONTEXT
        # --------------------------------------------------

        context = {
            "today": today,
            "near_expiry_date": near_expiry_date,

            # Inventory
            "total_medicines": total_medicines,
            "total_batches": total_batches,
            "total_stock_volume": total_stock_volume,
            "expired_count": expired_count,
            "near_expiry_count": near_expiry_count,

            # Dispensing and FEFO
            "total_dispenses": total_dispenses,
            "fefo_compliant": fefo_compliant,
            "fefo_overrides": fefo_overrides,
            "fefo_compliance_rate": fefo_compliance_rate,

            # Medicine consumption
            "top_consumed_medicines": top_consumed_medicines,

            # Low-stock monitoring
            "low_stock_medicines": low_stock_medicines,
            "total_low_stock_medicines": total_low_stock_medicines,

            # Procurement
            "pending_po_count": pending_po_count,
            "approved_po_count": approved_po_count,
            "placed_po_count": placed_po_count,
            "rejected_po_count": rejected_po_count,

            # Forecasting and expiry records
            "recent_forecasts": recent_forecasts,
            "batches": batches,

            # Chart datasets
            "analytics_chart_data": analytics_chart_data,
        }

        return render(
            request,
            "hospital_admin/analytics.html",
            context
        )


@role_required('Hospital Admin', 'Hospital Administrator')
def hospital_admin_inventory_view(request):
    today = timezone.localdate()
    near_expiry_date = today + timedelta(days=30)

    active_medicines = Medicine.objects.filter(is_active=True)

    all_batches = MedicineBatch.objects.select_related(
        'medicine'
    )

    active_batches = all_batches.filter(
        quantity_available__gt=0,
        expiry_date__gte=today,
        medicine__is_active=True
    )

    expired_batches = all_batches.filter(
        quantity_available__gt=0,
        expiry_date__lt=today
    )

    near_expiry_batches = all_batches.filter(
        quantity_available__gt=0,
        expiry_date__gte=today,
        expiry_date__lte=near_expiry_date
    )

    total_medicines = active_medicines.count()

    total_stock_volume = active_batches.aggregate(
        total=Sum('quantity_available')
    )['total'] or 0

    expired_count = expired_batches.count()
    near_expiry_count = near_expiry_batches.count()

    # Classify every active medicine by its usable (FEFO-eligible) stock.
    usable_stock = dict(
        MedicineBatch.objects.filter(
            quantity_available__gt=0,
            expiry_date__gt=today,
            status="Active",
        )
        .order_by()
        .values_list('medicine_id')
        .annotate(total=Sum('quantity_available'))
    )

    out_of_stock_count = 0
    low_stock_count = 0
    adequate_stock_count = 0

    for medicine in active_medicines:
        stock = usable_stock.get(medicine.pk, 0)
        if stock <= 0:
            out_of_stock_count += 1
        elif stock < medicine.reorder_level:
            low_stock_count += 1
        else:
            adequate_stock_count += 1

    # Batches that are in stock, in date and not near expiry.
    other_active_count = all_batches.filter(
        quantity_available__gt=0,
        expiry_date__gt=near_expiry_date
    ).count()
    batch_total = expired_count + near_expiry_count + other_active_count

    def pct(part, whole):
        return round(part * 100 / whole) if whole else 0

    batches = all_batches.filter(
        quantity_available__gt=0
    ).order_by('expiry_date')[:100]

    context = {
        'today': today,
        'near_expiry_date': near_expiry_date,
        'total_medicines': total_medicines,
        'total_batches': all_batches.count(),
        'active_batches': active_batches,
        'total_stock_volume': total_stock_volume,
        'expired_batches': expired_batches,
        'expired_count': expired_count,
        'near_expiry_batches': near_expiry_batches,
        'near_expiry_count': near_expiry_count,
        'batches': batches,

        # Batch expiry distribution
        'active_batches_count': other_active_count,
        'expired_percentage': pct(expired_count, batch_total),
        'near_expiry_percentage': pct(near_expiry_count, batch_total),
        'active_batches_percentage': pct(other_active_count, batch_total),

        # Medicine stock availability distribution
        'adequate_stock_count': adequate_stock_count,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'adequate_stock_percentage': pct(adequate_stock_count, total_medicines),
        'low_stock_percentage': pct(low_stock_count, total_medicines),
        'out_of_stock_percentage': pct(out_of_stock_count, total_medicines),
    }

    return render(
        request,
        'hospital_admin/inventory_overview.html',
        context
    )

@role_required('Hospital Admin', 'Hospital Administrator')
def hospital_admin_process_po_view(request, po_id, action):
    if request.method != "POST":
        messages.error(request, "Purchase orders must be processed using a POST request.")
        return redirect("admin_dashboard")

    normalized_action = action.strip().casefold()
    if normalized_action not in ("approve", "reject"):
        messages.error(request, "Invalid purchase-order action.")
        return redirect("admin_dashboard")

    reason = request.POST.get("reason", "").strip()[:500]
    if normalized_action == "reject" and not reason:
        messages.error(request, "Enter a reason for rejecting the purchase order.")
        return redirect("procurement_review")

    with transaction.atomic():
        po = get_object_or_404(
            PurchaseOrder.objects.select_for_update(of=("self",)).select_related(
                "recommendation"
            ),
            id=po_id,
        )

        # A double-click or the browser Back button must not give a 404.
        if po.status != PurchaseOrder.Status.PENDING_ADMIN_REVIEW:
            messages.info(
                request,
                f"Purchase Order REQ #{po.pk} was already processed ({po.status}).",
            )
            return redirect("procurement_review")

        recommendation = po.recommendation
        if normalized_action == "approve":
            po.status = PurchaseOrder.Status.APPROVED
            success_message = f"Purchase Order REQ #{po.pk} authorized."

            if recommendation:
                recommendation.status = ProcurementRecommendation.Status.ACTIONED
                recommendation.is_actioned = True

        else:
            po.status = PurchaseOrder.Status.REJECTED
            success_message = f"Purchase Order REQ #{po.pk} declined."

            if recommendation:
                recommendation.status = ProcurementRecommendation.Status.REJECTED
                recommendation.is_actioned = False

        po.reviewed_by = request.user
        po.reviewed_at = timezone.now()
        po.decision_reason = reason
        po.save(update_fields=["status", "reviewed_by", "reviewed_at", "decision_reason"])

        if recommendation:
            recommendation.reviewed_by = request.user
            recommendation.save(
                update_fields=[
                    "status",
                    "is_actioned",
                    "reviewed_by",
                    "updated_at",
                ]
            )

        AuditLog.objects.create(
            user=request.user,
            action=(
                "Purchase order approved"
                if normalized_action == "approve"
                else "Purchase order rejected"
            ),
            entity_type="PurchaseOrder",
            details=(
                f"Purchase Order REQ #{po.pk}; "
                f"status={po.status}; "
                f"Recommendation ID="
                f"{recommendation.pk if recommendation else 'None'}; "
                f"Reason={reason or 'none given'}."
            ),
        )

    if normalized_action == "approve":
        messages.success(request, success_message)
    else:
        messages.warning(request, success_message)
    return redirect("procurement_review")

@role_required('Hospital Admin', 'Hospital Administrator')
def hospital_admin_procurement_review_view(request):
    purchase_orders = PurchaseOrder.objects.select_related(
        'medicine',
        'supplier',
        'raised_by',
        'recommendation'
    ).order_by('-order_date')

    pending_pos = purchase_orders.filter(
        status=PurchaseOrder.Status.PENDING_ADMIN_REVIEW
    )

    approved_pos = purchase_orders.filter(
        status=PurchaseOrder.Status.APPROVED
    )

    placed_pos = purchase_orders.filter(
        status=PurchaseOrder.Status.PLACED_WITH_SUPPLIER
    )

    rejected_pos = purchase_orders.filter(
        status=PurchaseOrder.Status.REJECTED
    )

    pending_recommendations = ProcurementRecommendation.objects.filter(
        status=ProcurementRecommendation.Status.PENDING,
        purchase_order__isnull=True
    ).select_related(
        'medicine',
        'raised_by'
    ).order_by('-created_at')

    context = {
        'purchase_orders': purchase_orders,
        'pending_pos': pending_pos,
        'pending_review_count': pending_pos.count(),
        'approved_orders': approved_pos,
        'approved_orders_count': approved_pos.count(),
        'placed_orders': placed_pos,
        'placed_orders_count': placed_pos.count(),
        'rejected_orders': rejected_pos,
        'rejected_orders_count': rejected_pos.count(),
        'pending_recommendations': pending_recommendations,
        'pending_recommendations_count': pending_recommendations.count(),
        'today': timezone.localdate(),
    }

    return render(
        request,
        'hospital_admin/procurement_review.html',
        context
    )

@role_required('Hospital Admin', 'Hospital Administrator')
def hospital_admin_purchase_orders_view(request):
    today = timezone.localdate()

    orders = PurchaseOrder.objects.select_related(
        'medicine', 'supplier', 'raised_by', 'reviewed_by'
    ).order_by('-order_date')

    awaiting_approval_orders = list(
        orders.filter(status=PurchaseOrder.Status.PENDING_ADMIN_REVIEW))
    approved_orders = list(orders.filter(status=PurchaseOrder.Status.APPROVED))
    placed_orders = list(
        orders.filter(status=PurchaseOrder.Status.PLACED_WITH_SUPPLIER))
    rejected_orders = list(orders.filter(status=PurchaseOrder.Status.REJECTED))

    # Approved (waiting to be placed) plus placed (waiting for delivery).
    awaiting_delivery_orders = approved_orders + placed_orders

    # Usable stock per medicine, shown beside each order awaiting approval.
    usable_stock = dict(
        MedicineBatch.objects.filter(
            quantity_available__gt=0,
            expiry_date__gt=today,
            status="Active",
        )
        .order_by()
        .values_list('medicine_id')
        .annotate(total=Sum('quantity_available'))
    )
    for order in awaiting_approval_orders:
        order.current_stock = usable_stock.get(order.medicine_id, 0)

    pending_recommendations = ProcurementRecommendation.objects.filter(
        status=ProcurementRecommendation.Status.PENDING,
        purchase_order__isnull=True,
    ).select_related('medicine', 'raised_by').order_by('-created_at')

    context = {
        'pending_recommendations': pending_recommendations,
        'pending_recommendations_count': pending_recommendations.count(),

        'pending_orders': awaiting_approval_orders,
        'pending_orders_count': len(awaiting_approval_orders),
        'awaiting_approval_orders': awaiting_approval_orders,
        'awaiting_approval_count': len(awaiting_approval_orders),

        'approved_orders': approved_orders,
        'approved_orders_count': len(approved_orders),

        'awaiting_delivery_orders': awaiting_delivery_orders,
        'awaiting_delivery_count': len(awaiting_delivery_orders),

        'rejected_orders': rejected_orders,
        'rejected_orders_count': len(rejected_orders),
        'today': today,
    }
    return render(request, 'hospital_admin/purchase_orders.html', context)

@role_required('Hospital Admin', 'Hospital Administrator')
def hospital_admin_reports_view(request):
    today = timezone.localdate()
    default_start_date = today - timedelta(days=365)

    start_date = parse_date(request.GET.get('start_date', '')) or default_start_date
    end_date = parse_date(request.GET.get('end_date', '')) or today

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    all_batches = MedicineBatch.objects.filter(
        quantity_available__gt=0
    )

    active_batches = all_batches.filter(
        expiry_date__gte=today,
        medicine__is_active=True
    )

    expired_batches = all_batches.filter(
        expiry_date__lt=today
    )

    expiry_30 = all_batches.filter(
        expiry_date__gte=today,
        expiry_date__lte=today + timedelta(days=30)
    )

    expiry_60 = all_batches.filter(
        expiry_date__gte=today,
        expiry_date__lte=today + timedelta(days=60)
    )

    expiry_90 = all_batches.filter(
        expiry_date__gte=today,
        expiry_date__lte=today + timedelta(days=90)
    )

    transactions = DispensingTransaction.objects.filter(
        dispensed_at__date__gte=start_date,
        dispensed_at__date__lte=end_date
    ).select_related(
        'medicine',
        'batch',
        'dispensed_by'
    ).order_by('-dispensed_at')

    dispensing_summary = transactions.aggregate(
        total_quantity=Sum('quantity_dispensed'),
        total_transactions=Count('id')
    )

    pending_admin_review_count = PurchaseOrder.objects.filter(
        status=PurchaseOrder.Status.PENDING_ADMIN_REVIEW
    ).count()

    approved_order_count = PurchaseOrder.objects.filter(
        status=PurchaseOrder.Status.APPROVED
    ).count()

    placed_with_supplier_count = PurchaseOrder.objects.filter(
        status=PurchaseOrder.Status.PLACED_WITH_SUPPLIER
    ).count()

    rejected_order_count = PurchaseOrder.objects.filter(
        status=PurchaseOrder.Status.REJECTED
    ).count()

    context = {
        'today': today,
        'start_date': start_date,
        'end_date': end_date,

        # Inventory
        'total_medicines': Medicine.objects.filter(
            is_active=True
        ).count(),

        'active_batches': active_batches.count(),

        'total_stock_volume': active_batches.aggregate(
            total=Sum('quantity_available')
        )['total'] or 0,

        # Expiry
        'expiry_risk_count': expiry_30.count(),

        'expired_batch_count': expired_batches.count(),

        'expired_quantity': expired_batches.aggregate(
            total=Sum('quantity_available')
        )['total'] or 0,

        'expiry_30_days_count': expiry_30.count(),

        'expiry_30_days_quantity': expiry_30.aggregate(
            total=Sum('quantity_available')
        )['total'] or 0,

        'expiry_60_days_count': expiry_60.count(),

        'expiry_60_days_quantity': expiry_60.aggregate(
            total=Sum('quantity_available')
        )['total'] or 0,

        'expiry_90_days_count': expiry_90.count(),

        'expiry_90_days_quantity': expiry_90.aggregate(
            total=Sum('quantity_available')
        )['total'] or 0,

        # Dispensing
        'transactions': transactions,
        'dispensing_transactions': dispensing_summary['total_transactions'] or 0,
        'total_dispensed_quantity': dispensing_summary['total_quantity'] or 0,

        # Procurement
        'pending_admin_review_count': pending_admin_review_count,
        'approved_order_count': approved_order_count,
        'placed_with_supplier_count': placed_with_supplier_count,
        'rejected_order_count': rejected_order_count,
    }
    return render(request,'hospital_admin/reports.html',context)

# HOSPITAL ADMIN: ALERTS CENTRE
ADMIN_ALERT_EXPIRY_URGENT_DAYS = 30      # expires within this many days: High
ADMIN_ALERT_EXPIRY_WATCH_DAYS = 90       # expires within this many days: Medium
ADMIN_ALERT_REVIEW_OVERDUE_DAYS = 3      # order waiting this long for the admin: Critical
ADMIN_ALERT_DELIVERY_CRITICAL_DAYS = 7   # placed order this many days late: Critical
ADMIN_ALERT_OVERRIDE_DAYS = 30           # FEFO overrides this recent are listed
ADMIN_ALERT_OVERRIDE_LIMIT = 40          # at most this many overrides are listed
ADMIN_ALERT_OVERRIDE_REPEAT = 3          # this many overrides by one user: High

ADMIN_ALERT_CATEGORIES = [
    ("decision", "Decisions"),
    ("expiry", "Expiry"),
    ("stock", "Stock"),
    ("procurement", "Procurement"),
    ("oversight", "Oversight"),
]
ADMIN_ALERT_SEVERITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def _plural_days(n):
    n = abs(int(n))
    return f"{n} day" if n == 1 else f"{n} days"


@role_required('Hospital Admin', 'Hospital Administrator')
def hospital_admin_alerts_view(request):
    """Everything that needs the Hospital Admin's attention, in one register."""
    # procurement_views imports from this module, so import it here and not at the top.
    from .procurement_views import _delivery_rows

    today = timezone.localdate()
    PO = PurchaseOrder.Status
    category_label = dict(ADMIN_ALERT_CATEGORIES)
    category_order = {key: i for i, (key, _) in enumerate(ADMIN_ALERT_CATEGORIES)}
    alerts = []

    def as_date(value):
        if value is None:
            return None
        if hasattr(value, "date"):                      # a datetime
            if timezone.is_aware(value):
                value = timezone.localtime(value)
            return value.date()
        return value

    def po_ref(po):
        return po.purchase_order_id or po.pk

    def add(category, severity, title, detail, *, medicine="", batch="", when="",
            when_date=None, status="Open", url_name="", action="Open", order=0):
        alerts.append({
            "category": category,
            "category_label": category_label[category],
            "severity": severity,
            "title": title,
            "detail": detail,
            "medicine": medicine,
            "batch": batch,
            "when": when,
            "when_date": when_date,
            "status": status,
            "action_url": reverse(url_name) if url_name else "",
            "action_label": action,
            "sort": (ADMIN_ALERT_SEVERITY_RANK[severity], category_order[category], order),
        })

    # ---- 1. DECISIONS: purchase orders waiting for this admin ------------
    pending_orders = (
        PurchaseOrder.objects
        .filter(status=PO.PENDING_ADMIN_REVIEW)
        .select_related("medicine", "supplier")
        .order_by("order_date")
    )
    for po in pending_orders:
        raised_on = as_date(po.order_date)
        waited = (today - raised_on).days
        supplier = po.supplier.supplier_name if po.supplier else "no supplier"
        value = f" Value KSh {po.total_cost:,.2f}." if po.total_cost else ""
        add("decision",
            "Critical" if waited >= ADMIN_ALERT_REVIEW_OVERDUE_DAYS else "High",
            f"Purchase order {po_ref(po)} needs your decision",
            f"{po.quantity_ordered} units from {supplier}.{value}",
            medicine=po.medicine.medicine_name if po.medicine else "Unknown medicine",
            when=f"Waiting {_plural_days(waited)}" if waited else "Raised today",
            when_date=raised_on,
            url_name="procurement_review", action="Review",
            order=-waited)

    # ---- 2. EXPIRY: batches with stock that are expired or close to it ----
    # A batch that expires today counts as expired: usable stock only
    # includes batches that expire after today.
    watch_until = today + timedelta(days=ADMIN_ALERT_EXPIRY_WATCH_DAYS)
    acknowledged = {
        (item.batch_id, item.alert_type)
        for item in ExpiryAlert.objects.filter(is_acknowledged=True, is_resolved=False)
    }
    risky_batches = (
        MedicineBatch.objects
        .filter(quantity_available__gt=0, expiry_date__lte=watch_until)
        .select_related("medicine")
        .order_by("expiry_date")
    )
    for batch in risky_batches:
        days_left = (batch.expiry_date - today).days
        if days_left <= 0:
            kind, severity = "EXPIRED", "Critical"
            title = "Expired stock must not be dispensed"
            detail = (f"{batch.quantity_available} units still in stock. "
                      "Refer the batch for quarantine and disposal.")
            when = "Expired today" if days_left == 0 else f"Expired {_plural_days(days_left)} ago"
        elif batch.status == "Active":
            kind = "NEAR"
            severity = "High" if days_left <= ADMIN_ALERT_EXPIRY_URGENT_DAYS else "Medium"
            title = "Batch nearing expiry"
            detail = (f"{batch.quantity_available} units left. "
                      "Dispensing follows FEFO, so this batch goes out first.")
            when = f"Expires in {_plural_days(days_left)}"
        else:
            continue
        add("expiry", severity, title, detail,
            medicine=batch.medicine.medicine_name,
            batch=batch.batch_number,
            when=when,
            when_date=batch.expiry_date,
            status="Acknowledged" if (batch.pk, kind) in acknowledged else "Open",
            url_name="inventory_overview", action="Inventory",
            order=days_left)

    # ---- 3. STOCK: active medicines that are out of stock or low ----------
    usable_stock = dict(
        MedicineBatch.objects
        .filter(quantity_available__gt=0, expiry_date__gt=today, status="Active")
        .order_by()
        .values_list("medicine_id")
        .annotate(total=Sum("quantity_available"))
    )
    on_order = {}
    open_orders = (
        PurchaseOrder.objects
        .filter(medicine__isnull=False,
                status__in=[PO.PENDING_ADMIN_REVIEW, PO.APPROVED, PO.PLACED_WITH_SUPPLIER])
        .order_by("order_date")
    )
    for po in open_orders:
        on_order.setdefault(po.medicine_id, []).append(po)

    for medicine in Medicine.objects.filter(is_active=True).order_by("medicine_name"):
        stock = usable_stock.get(medicine.pk, 0)
        reorder = medicine.reorder_level or 0
        if stock <= 0:
            is_out = True
        elif reorder and stock <= reorder:
            is_out = False
        else:
            continue

        orders = on_order.get(medicine.pk, [])
        if orders:
            first = orders[0]
            cover = f"On order: {po_ref(first)} ({first.status})."
            severity = "High" if is_out else "Medium"
        else:
            cover = "Nothing on order."
            severity = "Critical" if is_out else "High"

        if is_out:
            title = "Out of stock"
            detail = f"No usable units. {cover}"
        else:
            title = "Low stock"
            detail = f"{stock} usable units against a reorder level of {reorder}. {cover}"
        add("stock", severity, title, detail,
            medicine=medicine.medicine_name, when="Now",
            url_name="inventory_overview", action="Inventory",
            order=stock)

    # ---- 4. PROCUREMENT: work that is stuck or late ------------------------
    recommendations = (
        ProcurementRecommendation.objects
        .filter(status=ProcurementRecommendation.Status.PENDING, purchase_order__isnull=True)
        .select_related("medicine", "raised_by")
        .order_by("created_at")
    )
    for rec in recommendations:
        urgency = str(rec.urgency_level or "").upper()
        severity = ("High" if urgency in {"HIGH", "CRITICAL", "URGENT"}
                    else "Medium" if urgency == "MEDIUM" else "Low")
        raised_on = as_date(rec.created_at)
        waited = (today - raised_on).days if raised_on else 0
        source = rec.raised_by.get_username() if rec.raised_by else "the system forecast"
        add("procurement", severity,
            "Replenishment recommended, no order raised yet",
            f"{rec.recommended_quantity} units suggested by {source}.",
            medicine=rec.medicine.medicine_name if rec.medicine else "Unknown medicine",
            when=f"Waiting {_plural_days(waited)}" if waited else "Raised today",
            when_date=raised_on,
            url_name="procurement_review", action="Review",
            order=-waited)

    approved_orders = (
        PurchaseOrder.objects
        .filter(status=PO.APPROVED)
        .select_related("medicine", "supplier")
        .order_by("reviewed_at", "order_date")
    )
    for po in approved_orders:
        approved_on = as_date(po.reviewed_at or po.order_date)
        waited = (today - approved_on).days
        supplier = po.supplier.supplier_name if po.supplier else "no supplier"
        add("procurement",
            "High" if waited >= ADMIN_ALERT_REVIEW_OVERDUE_DAYS else "Medium",
            f"Approved order {po_ref(po)} not yet placed with the supplier",
            f"{po.quantity_ordered} units from {supplier}.",
            medicine=po.medicine.medicine_name if po.medicine else "Unknown medicine",
            when=f"Approved {_plural_days(waited)} ago" if waited else "Approved today",
            when_date=approved_on,
            url_name="admin_purchase_orders", action="Orders",
            order=-waited)

    placed_orders = (
        PurchaseOrder.objects
        .filter(status=PO.PLACED_WITH_SUPPLIER)
        .select_related("medicine", "supplier")
    )
    for row in _delivery_rows(placed_orders):       # same overdue rule the Procurement Officer sees
        if not row["overdue"]:
            continue
        po = row["po"]
        late = (today - row["expected"]).days
        supplier = po.supplier.supplier_name if po.supplier else "no supplier"
        add("procurement",
            "Critical" if late >= ADMIN_ALERT_DELIVERY_CRITICAL_DAYS else "High",
            f"Delivery overdue: order {po_ref(po)}",
            f"{row['balance']} of {po.quantity_ordered} units still due from {supplier}.",
            medicine=po.medicine.medicine_name if po.medicine else "Unknown medicine",
            when=f"{_plural_days(late)} late",
            when_date=row["expected"],
            url_name="admin_purchase_orders", action="Orders",
            order=-late)

    # ---- 5. OVERSIGHT: FEFO overrides at the dispensing counter ------------
    override_qs = DispensingTransaction.objects.filter(
        is_override=True,
        dispensed_at__date__gte=today - timedelta(days=ADMIN_ALERT_OVERRIDE_DAYS),
    )
    override_total = override_qs.count()
    per_user = {}
    for user_id in override_qs.values_list("dispensed_by_id", flat=True):
        per_user[user_id] = per_user.get(user_id, 0) + 1

    recent_overrides = list(
        override_qs
        .select_related("medicine", "batch__medicine", "dispensed_by")
        .order_by("-dispensed_at")[:ADMIN_ALERT_OVERRIDE_LIMIT]
    )
    for tx in recent_overrides:
        happened_on = as_date(tx.dispensed_at)
        ago = (today - happened_on).days
        who = tx.dispensed_by.get_username() if tx.dispensed_by else "an unknown user"
        repeats = per_user.get(tx.dispensed_by_id, 0)
        detail = f"{tx.quantity_dispensed} units dispensed by {who} outside the FEFO order."
        if tx.notes:
            detail += f" Note: {tx.notes[:90]}"
        if tx.dispensed_by_id and repeats >= ADMIN_ALERT_OVERRIDE_REPEAT:
            detail += f" {repeats} overrides by this user in {ADMIN_ALERT_OVERRIDE_DAYS} days."
        medicine = tx.medicine or tx.batch.medicine
        add("oversight",
            "High" if tx.dispensed_by_id and repeats >= ADMIN_ALERT_OVERRIDE_REPEAT else "Medium",
            "FEFO override at the dispensing counter", detail,
            medicine=medicine.medicine_name if medicine else "Unknown medicine",
            batch=tx.batch.batch_number,
            when="Today" if ago == 0 else f"{_plural_days(ago)} ago",
            when_date=happened_on,
            url_name="admin_reports", action="Reports",
            order=ago)

    # ---- Notifications addressed to this admin ------------------------------
    notifications = []
    mine = UserAlert.objects.filter(recipient=request.user)
    for item in mine.order_by("is_resolved", "-created_at")[:50]:
        state = "Resolved" if item.is_resolved else "Acknowledged" if item.is_read else "Open"
        notifications.append({
            "id": item.pk,
            "title": item.title,
            "message": item.message,
            "severity": item.severity or "Medium",
            "status": state,
            "created_at": item.created_at,
            "action_url": item.action_url if (item.action_url or "").startswith("/") else "",
            "can_acknowledge": state == "Open",
            "can_resolve": state != "Resolved",
        })

    # ---- Totals, sorting and the page context -------------------------------
    alerts.sort(key=lambda a: a["sort"])
    counts = {key: 0 for key, _ in ADMIN_ALERT_CATEGORIES}
    for alert in alerts:
        counts[alert["category"]] += 1

    rules = [
        {"title": "Decisions",
         "text": f"Purchase orders waiting for you. High, and Critical after "
                 f"{ADMIN_ALERT_REVIEW_OVERDUE_DAYS} days."},
        {"title": "Expiry",
         "text": f"Batches with stock that are expired (Critical), or expire within "
                 f"{ADMIN_ALERT_EXPIRY_URGENT_DAYS} days (High) or "
                 f"{ADMIN_ALERT_EXPIRY_WATCH_DAYS} days (Medium)."},
        {"title": "Stock",
         "text": "Active medicines with no usable stock, or at or below their reorder level. "
                 "Raised a level when nothing is on order."},
        {"title": "Procurement",
         "text": f"Recommendations with no order, approved orders not yet placed, and placed "
                 f"orders past the supplier's expected delivery date (Critical after "
                 f"{ADMIN_ALERT_DELIVERY_CRITICAL_DAYS} days late)."},
        {"title": "Oversight",
         "text": f"FEFO overrides in the last {ADMIN_ALERT_OVERRIDE_DAYS} days. A user with "
                 f"{ADMIN_ALERT_OVERRIDE_REPEAT} or more is raised to High."},
    ]

    context = {
        "alerts": alerts,
        "alert_total": len(alerts),
        "categories": [
            {"key": key, "label": label, "count": counts[key]}
            for key, label in ADMIN_ALERT_CATEGORIES
        ],
        "critical_count": sum(1 for a in alerts if a["severity"] == "Critical"),
        "decision_count": counts["decision"],
        "expiry_count": counts["expiry"],
        "stock_count": counts["stock"],
        "notifications": notifications,
        "notifications_open": mine.filter(is_resolved=False).count(),
        "override_total": override_total,
        "override_listed": len(recent_overrides),
        "expiry_watch_days": ADMIN_ALERT_EXPIRY_WATCH_DAYS,
        "rules": rules,
        "today": today,
        "now": timezone.localtime(),
    }
    return render(request, "hospital_admin/alerts.html", context)


@login_required(login_url="/login/")
def alerts_entry_view(request):
    """One /alerts/ address for everyone: the Hospital Admin gets the admin
    Alerts Centre, every other role keeps the shared alerts page."""
    role_name = (getattr(getattr(request.user, "role", None), "name", "") or "").strip().casefold()
    if not request.user.is_superuser and role_name in {"hospital admin", "hospital administrator"}:
        return hospital_admin_alerts_view(request)
    return alerts_view(request)

#System admin views based on their roles ( Access control, user's management, system settings,audit logs*,System health)

#SYSTEM ADMINISTRATOR ACCESS CONTROL
def _require_system_admin(request):
    role = getattr(request.user, "role", None)
    role_name = ((getattr(role, "name", "") or "").strip().casefold())
    if not (request.user.is_superuser or role_name == "system administrator"
    ): raise PermissionDenied("Only System Administrators may access this page.")


# Roles the Roles page offers, with what each one does.
SYSTEM_ADMIN_ROLE_DIRECTORY = [
    ("System Administrator", "Manages accounts, application configuration, access governance and audit review."),
    ("Hospital Administrator", "Reviews hospital-level operations and processes purchase-order approvals."),
    ("Pharmacist", "Handles dispensing and medicine-related pharmacy operations."),
    ("Store Manager", "Manages inventory, batch information and stock monitoring."),
    ("Procurement Officer", "Reviews demand forecasts, procurement recommendations and orders."),
]
# "Hospital Admin" and "Hospital Administrator" are the same role under two names.
HOSPITAL_ADMIN_ROLE_NAMES = {"hospital admin", "hospital administrator"}


def _send_activation_email(request, account):
    """Email a fresh activation link to an account that has not been activated yet."""
    from django.conf import settings as django_settings

    uid = urlsafe_base64_encode(force_bytes(account.pk))
    token = default_token_generator.make_token(account)
    activation_url = request.build_absolute_uri(
        reverse("activate_account", kwargs={"uidb64": uid, "token": token})
    )

    # The link lives as long as Django's PASSWORD_RESET_TIMEOUT says, so say that.
    hours = int(django_settings.PASSWORD_RESET_TIMEOUT) // 3600
    lifetime = f"{hours // 24} days" if hours >= 48 and hours % 24 == 0 else f"{hours} hours"

    send_mail(
        subject="Activate Your Medicine FEFO System Account",
        message=(
            f"Hello {account.first_name},\n\n"
            "A System Administrator has created an account for you.\n\n"
            "Use the link below to establish your password and activate "
            "your account:\n\n"
            f"{activation_url}\n\n"
            f"This link can be used once and expires after {lifetime}.\n\n"
            "If you were not expecting this account, contact your "
            "System Administrator."
        ),
        from_email=None,
        recipient_list=[account.email],
        fail_silently=False,
    )


@login_required(login_url="/login/")
def system_admin_dashboard_view(request):
    _require_system_admin(request)
    user = get_user_model()

    # The role, user and setting forms now post to their own pages.
    if request.method == "POST":
        messages.error(request, "That form has moved to its own page. Please try again from there.")
        return redirect("system_admin_dashboard")

    accounts = user.objects.aggregate(
        total=Count("pk"),
        active=Count("pk", filter=Q(is_active=True)),
        pending=Count("pk", filter=Q(is_active=False, password__startswith="!")),
    )
    context = {
        "total_users": accounts["total"],
        "active_users": accounts["active"],
        "pending_users": accounts["pending"],
        "inactive_users": accounts["total"] - accounts["active"] - accounts["pending"],
        "total_medicines": Medicine.objects.count(),
        "total_batches": MedicineBatch.objects.count(),
        "settings_count": SystemSetting.objects.count(),
        "recent_logs": AuditLog.objects.select_related("user").order_by("-created_at")[:20],
    }
    return render(request, "system_admin/dashboard.html", context)


# SYSTEM ADMINISTRATOR USER MANAGEMENT
@login_required(login_url="/login/")
def system_admin_users_view(request):
    _require_system_admin(request)
    user = get_user_model()

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        ip_address = request.META.get("REMOTE_ADDR")

        try:
            # CREATE USER ACCOUNT
            if action == "create_user":
                import re
                username = request.POST.get("username", "").strip()
                first_name = request.POST.get("first_name", "").strip()
                last_name = request.POST.get("last_name", "").strip()
                other_name = request.POST.get("other_name", "").strip()
                email = request.POST.get("email", "").strip()
                phone_number = request.POST.get("phone_number", "").strip()
                role_id = request.POST.get("role_id", "").strip()

                if not all([username, first_name, last_name, email, phone_number, role_id]):
                    raise ValueError(
                        "Username, first name, surname, email, "
                        "phone number and role are required."
                    )

                if not re.fullmatch(r"\+?[0-9 ()-]{7,15}", phone_number):
                    raise ValueError("Enter a valid phone number (7 to 15 digits, for example 0700 123 456).")

                if user.objects.filter(username__iexact=username).exists():
                    raise ValueError("That username already exists.")

                if user.objects.filter(email__iexact=email).exists():
                    raise ValueError("That email address is already registered.")

                assigned_role = get_object_or_404(Role, pk=role_id)

                # Nothing is kept unless the email goes out: a failed send rolls the new account back.
                with transaction.atomic():
                    new_user = user(
                        username=username,
                        first_name=first_name,
                        last_name=last_name,
                        other_name=other_name,
                        email=email,
                        phone_number=phone_number,
                        role=assigned_role,
                        is_active=False,
                    )
                    new_user.set_unusable_password()
                    try:
                        new_user.full_clean(exclude=["password"])
                    except ValidationError as exc:
                        raise ValueError(" ".join(exc.messages))
                    new_user.save()

                    try:
                        _send_activation_email(request, new_user)
                    except Exception as exc:
                        raise ValueError(
                            "The account was not created because the activation email "
                            "could not be sent. Check the email settings and try again."
                        ) from exc

                    AuditLog.objects.create(
                        user=request.user,
                        action="User account created",
                        entity_type="User",
                        details=(
                            f"Created inactive account {username}; "
                            f"email={email}; role={assigned_role.name}."
                        ),
                        ip_address=ip_address,
                    )

                messages.success(
                    request,
                    f"Account for {username} created. An activation email was sent to {email}; "
                    "the account stays inactive until it is used.",
                )
                return redirect("system_admin_users")

            # EXISTING ACCOUNT MANAGEMENT
            target = get_object_or_404(user, pk=request.POST.get("user_id"))

            # ACTIVATE OR DEACTIVATE ACCOUNT
            if action == "toggle_active":
                if target.pk == request.user.pk:
                    raise ValueError("You cannot deactivate your own account.")

                # An account that never completed activation has no password yet. Switching it on
                # would also make its activation link unusable, so the user could never sign in.
                if not target.is_active and not target.has_usable_password():
                    raise ValueError(
                        f"{target.username} has not activated the account yet. "
                        "Resend the activation email instead of reactivating it."
                    )

                is_system_admin = (
                    target.role is not None
                    and target.role.name.strip().casefold() == "system administrator"
                )

                if target.is_active and is_system_admin:
                    active_admins = user.objects.filter(
                        is_active=True, role__name__iexact="System Administrator"
                    ).count()

                    if active_admins <= 1:
                        raise ValueError(
                            "The last active System Administrator "
                            "cannot be deactivated. Activate another "
                            "administrator first."
                        )

                target.is_active = not target.is_active
                target.save(update_fields=["is_active"])

                AuditLog.objects.create(
                    user=request.user,
                    action=("User account activated" if target.is_active else "User account deactivated"),
                    entity_type="User",
                    details=f"Account {target.username}; active={target.is_active}.",
                    ip_address=ip_address,
                )
                messages.success(
                    request,
                    f"Account {target.username} is now {'active' if target.is_active else 'inactive'}.",
                )

            # SEND A NEW ACTIVATION EMAIL
            elif action == "resend_activation":
                if target.is_active or target.has_usable_password():
                    raise ValueError("Only accounts that are waiting for activation can be sent a new activation email.")
                if not target.email:
                    raise ValueError("This account has no email address.")

                try:
                    _send_activation_email(request, target)
                except Exception as exc:
                    raise ValueError(
                        "The activation email could not be sent. Check the email settings and try again."
                    ) from exc

                AuditLog.objects.create(
                    user=request.user,
                    action="Activation email resent",
                    entity_type="User",
                    details=f"Account {target.username}; email={target.email}.",
                    ip_address=ip_address,
                )
                messages.success(request, f"A new activation email was sent to {target.email}.")

            # UPDATE USER ROLE
            elif action == "update_role":
                if target.pk == request.user.pk:
                    raise ValueError("Use another System Administrator to change your own role.")

                assigned_role = get_object_or_404(Role, pk=request.POST.get("role_id"))
                old_role = target.role.name if target.role else "No Role"
                new_role = assigned_role.name

                removing_admin_role = (
                    target.is_active
                    and old_role.strip().casefold() == "system administrator"
                    and new_role.strip().casefold() != "system administrator"
                )

                if removing_admin_role:
                    active_admins = user.objects.filter(
                        is_active=True, role__name__iexact="System Administrator"
                    ).count()

                    if active_admins <= 1:
                        raise ValueError(
                            "The last active System Administrator "
                            "cannot be reassigned. Assign another "
                            "administrator first."
                        )

                target.role = assigned_role
                target.save(update_fields=["role"])

                AuditLog.objects.create(
                    user=request.user,
                    action="User role changed",
                    entity_type="User",
                    details=f"Account {target.username}: {old_role} -> {new_role}.",
                    ip_address=ip_address,
                )
                messages.success(request, f"Role updated for {target.username}.")

            else:
                messages.error(request, "Invalid user management action.")

        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("system_admin_users")

    # Each account is active, waiting for activation (no password yet) or switched off.
    accounts = list(user.objects.select_related("role").order_by("username"))
    for account in accounts:
        if account.is_active:
            account.state = "active"
        elif not account.has_usable_password():
            account.state = "pending"
        else:
            account.state = "inactive"

    context = {
        "users": accounts,
        "roles": Role.objects.order_by("name"),
        "total_users": len(accounts),
        "active_users": sum(1 for a in accounts if a.state == "active"),
        "pending_users": sum(1 for a in accounts if a.state == "pending"),
        "inactive_users": sum(1 for a in accounts if a.state == "inactive"),
    }
    return render(request, "system_admin/users.html", context)
#SYSTEM ADMINISTRATOR ROLES AND ACCESS CONTROL
@login_required(login_url="/login/")
def system_admin_roles_view(request):
    _require_system_admin(request)

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        try:
            if action == "create_role":
                role_name_input = request.POST.get("role_name", "").strip()
                description = request.POST.get("role_description", "").strip()

                if not role_name_input:
                    raise ValueError("Role name is required.")
                role_definition = Role.SUPPORTED_ROLES.get(role_name_input.casefold())

                if role_definition is None:
                    raise ValueError(
                        "Choose a supported application role: "
                        "System Administrator, Hospital Administrator, "
                        "Pharmacist, Store Manager, or Procurement Officer."
                    )
                canonical_name, default_description = role_definition

                if Role.objects.filter(name__iexact=canonical_name).exists():
                    raise ValueError("A role with that name already exists.")

                if canonical_name.casefold() in HOSPITAL_ADMIN_ROLE_NAMES and any(
                    Role.objects.filter(name__iexact=alias).exists() for alias in HOSPITAL_ADMIN_ROLE_NAMES
                ):
                    raise ValueError("A Hospital Admin role already exists.")

                if len(description) > 500:
                    raise ValueError("Keep the role description under 500 characters.")

                new_role = Role.objects.create(
                    name=canonical_name,
                    description=description or default_description,
                )
                AuditLog.objects.create(
                    user=request.user,
                    action="Role created",
                    entity_type="Role",
                    details=f"Created role {new_role.name}.",
                    ip_address=request.META.get("REMOTE_ADDR"),
                )
                messages.success(request, f"Role {new_role.name} created.")
            else:
                raise ValueError("Unknown role action.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("system_admin_roles")

    # One row per supported role (created or not), then any other roles found in the database.
    db_roles = {
        role.name.strip().casefold(): role
        for role in Role.objects.annotate(
            user_count=Count("user"),
            active_count=Count("user", filter=Q(user__is_active=True)),
        ).order_by("name")
    }
    used = set()
    role_rows = []
    for name, responsibility in SYSTEM_ADMIN_ROLE_DIRECTORY:
        keys = HOSPITAL_ADMIN_ROLE_NAMES if name.casefold() in HOSPITAL_ADMIN_ROLE_NAMES else {name.casefold()}
        found = next((db_roles[k] for k in keys if k in db_roles), None)
        used.update(k for k in keys if k in db_roles)
        role_rows.append({
            "name": found.name if found else name,
            "description": (found.description if found and found.description else responsibility),
            "exists": found is not None,
            "custom": False,
            "user_count": found.user_count if found else 0,
            "active_count": found.active_count if found else 0,
        })
    for key, role in db_roles.items():
        if key not in used:
            role_rows.append({
                "name": role.name,
                "description": role.description or "No description provided.",
                "exists": True,
                "custom": True,
                "user_count": role.user_count,
                "active_count": role.active_count,
            })

    creatable_roles = [row["name"] for row in role_rows if not row["exists"]]
    context = {
        "role_rows": role_rows,
        "creatable_roles": creatable_roles,
        "role_count": len(db_roles),
    }
    return render(request, "system_admin/roles.html", context)


#SYSTEM ADMINISTRATOR SYSTEM SETTINGS
@login_required(login_url="/login/")
def system_admin_settings_view(request):
    _require_system_admin(request)

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        try:
            if action == "save_setting":
                key = request.POST.get("key", "").strip()
                value = request.POST.get("value", "").strip()
                description = request.POST.get("description", "").strip()

                if not key or not value:
                    raise ValueError("Setting key and value are required.")
                if len(key) > 100:
                    raise ValueError("A setting key can be at most 100 characters.")
                if len(value) > 255:
                    raise ValueError("A setting value can be at most 255 characters.")

                setting, created = SystemSetting.objects.update_or_create(
                    key=key,
                    defaults={
                        "setting_key": key,
                        "value": value,
                        "setting_value": value,
                        "description": description,
                    },
                )

                AuditLog.objects.create(
                    user=request.user,
                    action="System setting saved",
                    entity_type="SystemSetting",
                    details=f"Setting {key} {'created' if created else 'updated'}.",
                    ip_address=request.META.get("REMOTE_ADDR"),
                )
                messages.success(request, f"System setting '{key}' {'created' if created else 'updated'}.")
            else:
                raise ValueError("Unknown settings action.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("system_admin_settings")

    context = {
        "settings": SystemSetting.objects.order_by("key"),
        "settings_count": SystemSetting.objects.count(),
    }
    return render(request, "system_admin/settings.html", context)


#SYSTEM ADMINISTRATOR AUDIT LOGS
@login_required(login_url="/login/")
def system_admin_audit_logs_view(request):
    _require_system_admin(request)
    entity_types = sorted(
        {e for e in AuditLog.objects.order_by().values_list("entity_type", flat=True).distinct() if e}
    )
    context = {
        "recent_logs": list(AuditLog.objects.select_related("user").order_by("-created_at")[:200]),
        "log_total": AuditLog.objects.count(),
        "entity_types": entity_types,
    }
    return render(request, "system_admin/audit.html", context)


# SYSTEM ADMINISTRATOR SYSTEM HEALTH
@login_required(login_url="/login/")
def system_admin_health_view(request):
    """Live checks of the things this application can actually see."""
    _require_system_admin(request)

    import time
    import django
    from django.conf import settings as django_settings
    from django.db import connection

    today = timezone.localdate()
    user = get_user_model()
    checks = []

    def add(component, what, result, status):          # status: ok, attention or info
        checks.append({"component": component, "what": what, "result": result, "status": status})

    # Database
    db_ms = None
    started = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        db_ms = round((time.perf_counter() - started) * 1000, 1)
        vendor = {"postgresql": "PostgreSQL", "sqlite": "SQLite", "mysql": "MySQL"}.get(
            connection.vendor, connection.vendor)
        add("Database", "Connection and response time",
            f"{vendor} answered in {db_ms} ms.", "ok" if db_ms < 500 else "attention")
    except Exception as exc:
        add("Database", "Connection and response time", f"The database did not answer: {exc}", "attention")

    # Application
    add("Application", "Framework version and debug mode",
        f"Django {django.get_version()}. DEBUG is {'on: turn it off before real use' if django_settings.DEBUG else 'off'}.",
        "attention" if django_settings.DEBUG else "ok")

    # Email (account activation depends on it)
    backend = django_settings.EMAIL_BACKEND.rsplit(".", 2)[-2]
    add("Email", "Delivery of activation emails",
        (f"Sending through {backend.upper()}." if backend == "smtp"
         else f"The '{backend}' backend is in use, so activation emails are not delivered to real inboxes."),
        "ok" if backend == "smtp" else "attention")

    # Accounts
    active_admins = user.objects.filter(is_active=True, role__name__iexact="System Administrator").count()
    add("Accounts", "Active System Administrators",
        f"{active_admins} active." + ("" if active_admins >= 2 else " Add a second one so nobody can be locked out."),
        "ok" if active_admins >= 2 else "attention")

    no_role = user.objects.filter(role__isnull=True, is_superuser=False).count()
    add("Accounts", "Accounts without a role",
        f"{no_role} without a role." if no_role else "Every account has a role.",
        "attention" if no_role else "ok")

    pending = user.objects.filter(is_active=False, password__startswith="!").count()
    add("Accounts", "Accounts waiting for activation",
        f"{pending} waiting for the user to open the activation email." if pending else "None waiting.",
        "info" if pending else "ok")

    # Inventory
    negative = MedicineBatch.objects.filter(quantity_available__lt=0).count()
    add("Inventory", "Batches with a negative quantity",
        f"{negative} found." if negative else "None found.", "attention" if negative else "ok")

    expired_stock = MedicineBatch.objects.filter(expiry_date__lte=today, quantity_available__gt=0).count()
    add("Inventory", "Expired batches still holding stock",
        f"{expired_stock} batches still hold stock." if expired_stock else "None.",
        "attention" if expired_stock else "ok")

    # Expiry monitoring
    open_alerts = ExpiryAlert.objects.filter(is_resolved=False)
    open_count = open_alerts.count()
    unacknowledged = open_alerts.filter(is_acknowledged=False).count()
    add("Expiry monitoring", "Open expiry alerts",
        (f"{open_count} open, {unacknowledged} not yet acknowledged." if open_count else "No open alerts."),
        "attention" if unacknowledged else ("info" if open_count else "ok"))

    # Forecasting
    latest = DemandForecast.objects.order_by("-generated_at").first()
    if latest is None:
        add("Forecasting", "Demand forecasts", "No forecasts have been generated yet.", "attention")
    else:
        current = DemandForecast.objects.filter(forecast_period_end__gte=today).count()
        add("Forecasting", "Demand forecasts",
            f"Last generated {timezone.localtime(latest.generated_at):%d %b %Y}. "
            + (f"{current} forecasts cover today or later." if current
               else "Every forecast period has ended; generate new forecasts."),
            "ok" if current else "attention")

    # Audit trail
    last_event = AuditLog.objects.order_by("-created_at").first()
    add("Audit trail", "Recording of administrative events",
        (f"Last event: {last_event.action}, {timezone.localtime(last_event.created_at):%d %b %Y, %H:%M}."
         if last_event else "No events recorded yet."),
        "ok" if last_event else "info")

    # Backups
    add("Backups", "Last successful backup", "The application cannot see backups. Confirm them with the database host.", "info")

    context = {
        "checks": checks,
        "ok_count": sum(1 for c in checks if c["status"] == "ok"),
        "attention_count": sum(1 for c in checks if c["status"] == "attention"),
        "check_count": len(checks),
        "db_ms": db_ms,
        "last_event": last_event,
        "checked_at": timezone.localtime(),
    }
    return render(request, "system_admin/health.html", context)
@login_required(login_url="/login/")
def alerts_view(request): #Role based alerts definitions
    today = timezone.localdate()
    role = (getattr(getattr(request.user, "role", None), "name", "") or "").strip().casefold()

    if request.user.is_superuser: role = "system administrator"
    allowed_roles = {"pharmacist","store manager","procurement officer","hospital admin","hospital administrator","system administrator", "system admin",}

    if role not in allowed_roles:
        raise PermissionDenied("Permission denied")

    # Standardize alerts so they can be displayed in one template.
    alerts = []

    def add_alert(
        *,
        alert_type,
        title,
        severity="Medium",
        medicine=None,
        batch=None,
        created_at=None,
        days_to_expiry=None,
        status="Open",
        reasoning="",
        source_id=None,
        source_type="",
        action_url="",
    ):
        is_resolved = status.casefold() == "resolved"
        is_acknowledged = status.casefold() == "acknowledged"

        alerts.append({
            "alert_type": alert_type,
            "title": title,
            "severity": severity,
            "medicine": medicine,
            "batch": batch,
            "created_at": created_at,
            "generated_at": created_at,
            "days_to_expiry": days_to_expiry,
            "status": status,
            "is_resolved": is_resolved,
            "is_acknowledged": is_acknowledged,
            "reasoning": reasoning,
            "source_id": source_id,
            "source_type": source_type,
            "action_url": action_url,
        })

    # Retrieve alerts assigned specifically to the logged-in user.
    personal_alerts = UserAlert.objects.filter(recipient=request.user).order_by("-created_at")
    for user_alert in personal_alerts:
        if user_alert.is_resolved: alert_status = "Resolved"
        elif user_alert.is_read: alert_status = "Acknowledged"
        else: alert_status = "Open"

        add_alert(
            alert_type=user_alert.alert_type,
            title=user_alert.title,
            severity=user_alert.severity,
            created_at=user_alert.created_at,
            status=alert_status,
            reasoning=user_alert.message,
            source_id=user_alert.source_id,
            source_type="UserAlert",
            action_url=user_alert.action_url,
        )

    #Existing persistent expiry alerts
    expiry_alerts = ExpiryAlert.objects.select_related("medicine", "batch", "batch__medicine"
    ).filter(Q(medicine__isnull=False) | Q(batch__isnull=False)).order_by("-generated_at")

    for item in expiry_alerts:
        batch = item.batch
        medicine = item.medicine or (batch.medicine if batch else None)

        # A resolved alert remains visible in the register.
        days = item.days_to_expiry
        severity = item.severity or "Medium"

        if item.alert_type == "EXPIRED":
            title = "Expired medicine batch"
            severity = "Critical"
        else: title = "Medicine nearing expiry"

        # Only roles responsible for clinical stock and oversight see
        # medicine expiry alerts.
        if role not in {
            "pharmacist",
            "store manager",
            "hospital admin",
            "hospital administrator",
            "system administrator",
            "system admin",
        }:
            continue

        status = ("Resolved" if item.is_resolved
            else "Acknowledged" if item.is_acknowledged
            else "Open"
        )

        add_alert(
            alert_type=item.alert_type,
            title=title,
            severity=severity,
            medicine={"name": medicine.medicine_name,} if medicine else None,
            batch={"batch_number": batch.batch_number,"expiry_date": batch.expiry_date,} if batch else None,
            created_at=item.generated_at,
            days_to_expiry=days,
            status=status,
            reasoning=f"Expiry alert for batch {batch.batch_number}" if batch else "Medicine expiry alert.",
            source_id=item.pk,
            source_type="expiry",
            action_url="/inventory/alerts/",
        )

    #Batch stock risks
    if role in {
        "pharmacist",
        "store manager",
        "hospital admin",
        "hospital administrator",
        "system administrator",
        "system admin",
    }:
        batches = MedicineBatch.objects.select_related("medicine").filter(
            quantity_available__gte=0)

        for batch in batches:
            medicine = batch.medicine
            if not medicine: continue

            # An expired batch with remaining stock needs review.
            if (batch.expiry_date <= today
                    and batch.quantity_available > 0):

                add_alert(
                    alert_type="EXPIRED",
                    title="Expired stock requires review",
                    severity="Critical",
                    medicine={"name": medicine.medicine_name},
                    batch={"batch_number": batch.batch_number,"expiry_date": batch.expiry_date,},
                    created_at=None,
                    days_to_expiry=(batch.expiry_date - today).days,
                    reasoning="Remaining stock must not be dispensed. "
                              "Refer the batch for the approved quarantine "
                              "and disposal process.",
                    source_id=batch.pk,
                    source_type="batch",
                    action_url="/inventory/alerts/",
                )

            # Near-expiry warning, limited to batches still in stock.
            elif (
                0 < (batch.expiry_date - today).days <= 90
                and batch.quantity_available > 0
                and batch.status == "Active"
            ):
                days_left = (batch.expiry_date - today).days

                add_alert(
                    alert_type="NEAR",
                    title="Medicine nearing expiry",
                    severity=("High" if days_left <= 30 else "Medium"),
                    medicine={"name": medicine.medicine_name},
                    batch={"batch_number": batch.batch_number,"expiry_date": batch.expiry_date,},
                    created_at=None,
                    days_to_expiry=days_left,
                    reasoning=f"Batch expires in {days_left} days.",
                    source_id=batch.pk,
                    source_type="batch",
                    action_url="/inventory/alerts/",
                )

            # Depleted stock is operationally relevant to stock handlers.
            if (
                role in {
                    "store manager",
                    "pharmacist",
                    "hospital admin",
                    "hospital administrator",
                    "system administrator",
                    "system admin",
                }
                and batch.quantity_available <= 0
                and batch.status == "Active"
            ):
                add_alert(
                    alert_type="STOCK_DEPLETED",
                    title="Batch stock depleted",
                    severity="Medium",
                    medicine={"name": medicine.medicine_name},
                    batch={"batch_number": batch.batch_number},
                    reasoning=("This batch has no available stock. Check other eligible batches before declaring a medicine stock-out."),
                    source_id=batch.pk,
                    source_type="batch",
                    action_url="/inventory/",
                )

    # 3. Procurement recommendations
    if role in {
        "procurement officer",
        "hospital admin",
        "hospital administrator",
        "system administrator",
        "system admin",
    }:
        recommendations = ProcurementRecommendation.objects.select_related("medicine").filter(
            Q(status__iexact="Pending")
            | Q(is_actioned=False)
        ).order_by("-created_at")

        for recommendation in recommendations:
            medicine = recommendation.medicine
            urgency = (getattr(recommendation, "urgency_level", "Medium") or "Medium")
            urgency_key = str(urgency).casefold()

            severity = (
                "Critical" if urgency_key in {"critical", "urgent"}
                else "High" if urgency_key in {"high", "high priority"}
                else "Medium"
            )

            add_alert(
                alert_type="PROCUREMENT",
                title="Pending procurement recommendation",
                severity=severity,
                medicine={"name": medicine.medicine_name} if medicine else None,
                created_at=getattr(
                    recommendation, "created_at", None
                ) or getattr(recommendation, "generated_at", None),
                status="Open",
                reasoning=getattr(recommendation, "reasoning", "")
                or (
                    "Recommended quantity: "
                    f"{recommendation.recommended_quantity}"
                ),
                source_id=recommendation.pk,
                source_type="procurement",
                action_url="/procurement/",
            )

    #Purchase orders awaiting attention
    if role in {
        "procurement officer",
        "hospital admin",
        "hospital administrator",
        "system administrator",
        "system admin",
    }:
        purchase_orders = PurchaseOrder.objects.select_related("medicine", "supplier").order_by("-order_date")

        for po in purchase_orders:
            status_text = (po.status or "").strip()
            status_key = status_text.casefold()

            if status_key in {"completed", "received", "cancelled", "rejected"}: continue

            # Procurement users handle orders; hospital administrators
            if role in {"hospital admin", "hospital administrator"}:
                if not any(marker in status_key
                    for marker in ("pending admin", "awaiting approval","pending approval", "review")):
                    continue

            add_alert(
                alert_type="PURCHASE_ORDER",
                title="Purchase order requires attention",
                severity="High" if "approval" in status_key or "review" in status_key
                else "Medium",
                medicine={"name": po.medicine.medicine_name,} if po.medicine else None,
                created_at=po.order_date,
                status="Open",
                reasoning=(
                    f"Order status: {status_text}. "
                    f"Supplier: {po.supplier.supplier_name if po.supplier else 'Not assigned'}."),
                source_id=po.pk,
                source_type="purchase_order",
                action_url=("/hospital_admin/dashboard/" if role in {"hospital admin", "hospital administrator"}
                    else "/procurement/"
                ),
            )

#Deduplicate generated batch warnings against persistent expiry alerts for the same batch and alert type.
    seen = set()
    unique_alerts = []

    for alert in alerts:
        batch = alert.get("batch") or {}
        batch_number = batch.get("batch_number")
        key = (alert.get("source_type"),alert.get("source_id"),alert.get("alert_type"),)

#Generated batch alerts and saved ExpiryAlert records use different source types, so deduplicate them by batch and alert type as well.
        cross_source_key = (batch_number,alert.get("alert_type"),)

        if key in seen:continue
        if batch_number and cross_source_key in seen: continue
        seen.add(key)
        if batch_number:seen.add(cross_source_key)
        unique_alerts.append(alert)

#Sort newest first; generated stock alerts without timestamps appear last.
    unique_alerts.sort(
        key=lambda a: a.get("created_at") or timezone.make_aware(timezone.datetime.min),
        reverse=True,)

    total_alerts = len(unique_alerts)
    critical_alerts = sum(1 for a in unique_alerts if str(a.get("severity", "")).casefold() in {"critical", "high"})
    unacknowledged_alerts = sum(1 for a in unique_alerts if a.get("status") == "Open")
    resolved_alerts = sum(1 for a in unique_alerts if a.get("status") == "Resolved")

    context = {
        "alerts": unique_alerts,
        "role_name": role,
        "total_alerts": total_alerts,
        "critical_alerts": critical_alerts,
        "unacknowledged_alerts": unacknowledged_alerts,
        "resolved_alerts": resolved_alerts,
    }
    return render(request, "alerts.html", context)

@login_required(login_url="/login/")
@require_POST
def acknowledge_user_alert(request, alert_id):
    alert = get_object_or_404(UserAlert,pk=alert_id,recipient=request.user)

    if not alert.is_resolved:
        alert.is_read = True
        alert.save(update_fields=["is_read"])

    messages.success(request, "Alert acknowledged successfully.")
    return redirect("/alerts/")

@login_required(login_url="/login/")
@require_POST
def resolve_user_alert(request, alert_id):
    alert = get_object_or_404(UserAlert,pk=alert_id,recipient=request.user)
    alert.is_read = True
    alert.is_resolved = True
    alert.save(update_fields=["is_read", "is_resolved"])

    messages.success(request, "Alert marked as resolved.")
    return redirect("/alerts/")