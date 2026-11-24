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
        return redirect("public/login.html")

    if target_user.is_active:
        messages.info(request, "This account has already been activated.")
        return redirect("public/login.html")

    if not default_token_generator.check_token(target_user, token):
        messages.error(
            request,
            "This activation link is invalid or has expired. "
            "Contact your System Administrator."
        )
        return redirect("public/login.html")

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
                return redirect("public/login.html")

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
            if not medicine_id:raise ValueError("Select a medicine.")
            try:
                duration_days = int(duration_raw)
            except(TypeError,ValueError):
                raise ValueError("Enter a valid prescription duration in days.")
            if duration_days <= 0:
                raise ValueError("Prescription duration must  be greater than zero")

            transactions = FEFOEngine.dispense_medicine(
                medicine_id=medicine_id,
                total_qty_to_dispense=quantity_raw,
                user=request.user,
                selected_batch_id=selected_batch_id,
                notes=override_reason,
                patient_identifier=patient_identifier,
                prescription_duration_days = duration_days,
            )
            total_dispensed = sum(tx.quantity_dispensed for tx in transactions)

            #Auditing the completed operation after dispensing succeeds.
            AuditLog.objects.create(
                user=request.user,
                action="Medicine dispensed",
                entity_type="DispensingTransaction",
                details=(
                    f"Medicine ID={medicine_id}; "
                    f"quantity={total_dispensed}; "
                    f"prescription_duration_days={duration_days};"
                    f"transaction IDs="
                    f"{', '.join(str(tx.pk) for tx in transactions)}"
                ),
            )
            messages.success(request,f"Dispensing completed: {total_dispensed} units recorded.",)
        except (ValueError, TypeError) as exc: messages.error(request, str(exc))
        except Medicine.DoesNotExist: messages.error(request, "The selected medicine was not found.")
        return redirect("pharmacist/dispense.html")

    today = timezone.localdate()
    medicines = Medicine.objects.filter(is_active=True).order_by("medicine_name")
    batches = (MedicineBatch.objects.filter(
        quantity_available__gt=0,
        status="Active",
        expiry_date__gt=today,
        medicine__is_active=True,)
        .select_related("medicine")
        .order_by("expiry_date", "id")
    )
    return render(request,"pharmacist/dispense.html",{"medicines": medicines,"batches": batches,},)

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
@user_passes_test(is_procurement_officer,login_url="login",redirect_field_name=None,)
def procurement_dashboard_view(request):
    if request.method == "POST":
        medicine_id = request.POST.get("medicine_id", "").strip()
        quantity_text = request.POST.get("quantity", "").strip()
        supplier_name = request.POST.get("supplier_name", "").strip()
        rec_id = request.POST.get("recommendation_id", "").strip()

        try:
            quantity = int(quantity_text)
            if quantity <= 0: raise ValueError("Quantity must be greater than zero.")
            if not supplier_name:raise ValueError("Supplier name is required.")

            medicine = get_object_or_404(Medicine,id=medicine_id,is_active=True,)

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

            messages.success(request,f"Purchase order for {medicine.medicine_name} forwarded to hospital admin.",)
        except (ValueError, TypeError) as exc:messages.error(request, str(exc))
        return redirect("procurement/procurement.html")

    medicines = Medicine.objects.filter(is_active=True).order_by("medicine_name")
    recommendations = (ProcurementRecommendation.objects.filter(
        status=ProcurementRecommendation.Status.PENDING,
        purchase_order__isnull = True,) #Recommendation disappears from pending lists once PO is placed
    .select_related("medicine", "forecast").order_by("-created_at"))

    # Retrieve saved forecasts for the procurement dashboard.
    latest_forecasts = (DemandForecast.objects.filter(medicine__is_active=True)
        .select_related("medicine").order_by("medicine_id", "-generated_at"))
    forecasts = []
    seen_medicines = set()

    for forecast in latest_forecasts:
        if forecast.medicine_id in seen_medicines: continue

        seen_medicines.add(forecast.medicine_id)
        forecasts.append({
            "medicine": forecast.medicine,
            "forecast": forecast,
            "current_stock": sum(batch.quantity_available for batch in forecast.medicine.get_fefo_batches()),
            "avg_monthly_dispensed": forecast.moving_avg_3month,
            "forecasted_demand": forecast.forecasted_demand_quantity,
        })
    return render(request,"procurement/procurement.html",{"medicines": medicines,"recommendations": recommendations,"forecasts": forecasts,},)

@login_required(login_url="/login/")
@role_required("Procurement Officer")
def place_supplier_order_view(request, po_id):
    if request.method != "POST":
        messages.error(request,"Supplier orders must be submitted using POST.",)
        return redirect("procurement")

    po = get_object_or_404(PurchaseOrder.objects.select_related("supplier"),id=po_id,status=PurchaseOrder.Status.APPROVED,)
    po.status = PurchaseOrder.Status.PLACED_WITH_SUPPLIER
    po.save(update_fields=["status"])

    messages.success(request,f"Purchase Order #{po.id} placed with "
        f"{po.supplier.supplier_name}.",)
    return redirect("procurement")

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
    active_batches_count = active_batches.count()

    total_stock_volume = active_batches.aggregate(
        total=Sum('quantity_available')
    )['total'] or 0

    expired_count = expired_batches.count()
    near_expiry_count = near_expiry_batches.count()

    out_of_stock_count = all_batches.filter(
        quantity_available__lte=0
    ).count()

    low_stock_count = 0

    for medicine in active_medicines:
        current_stock = MedicineBatch.objects.filter(
            medicine=medicine,
            quantity_available__gt=0,
            expiry_date__gte=today
        ).aggregate(
            total=Sum('quantity_available')
        )['total'] or 0

        if current_stock < medicine.reorder_level:
            low_stock_count += 1

    batches = all_batches.filter(
        quantity_available__gt=0
    ).order_by('expiry_date')[:100]

    context = {
        'today': today,
        'near_expiry_date': near_expiry_date,
        'total_medicines': total_medicines,
        'total_batches': all_batches.count(),
        'active_batches': active_batches,
        'active_batches_count': active_batches_count,
        'total_stock_volume': total_stock_volume,
        'expired_batches': expired_batches,
        'expired_count': expired_count,
        'near_expiry_batches': near_expiry_batches,
        'near_expiry_count': near_expiry_count,
        'out_of_stock_count': out_of_stock_count,
        'low_stock_count': low_stock_count,
        'batches': batches,
    }

    return render(
        request,
        'hospital_admin/inventory_overview.html',
        context
    )

@role_required('Hospital Admin', 'Hospital Administrator')
def hospital_admin_process_po_view(request, po_id, action):
    if request.method != "POST":
        messages.error(request,"Purchase orders must be processed using a POST request.",)
        return redirect("admin_dashboard")

    normalized_action = action.strip().casefold()
    if normalized_action not in ("approve", "reject"):
        messages.error(request, "Invalid purchase-order action.")
        return redirect("admin_dashboard")

    with transaction.atomic():
        po = get_object_or_404(
            PurchaseOrder.objects.select_for_update(of=("self",)).select_related(
                "recommendation"
            ),
            id=po_id,
            status=PurchaseOrder.Status.PENDING_ADMIN_REVIEW,
        )

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
        po.save(update_fields=["status"])

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
            action=("Purchase order approved"if normalized_action == "approve"else "Purchase order rejected"),
            entity_type="PurchaseOrder",
            details=(
                f"Purchase Order REQ #{po.pk}; "
                f"status={po.status}; "
                f"Recommendation ID="
                f"{recommendation.pk if recommendation else 'None'}."
            ),
        )
    if normalized_action == "approve": messages.success(request, success_message)
    else:messages.warning(request, success_message)
    return redirect("hospital_admin/purchase_orders.html")

@login_required(login_url="/login/")
@role_required("Procurement Officer")
@user_passes_test(is_procurement_officer,login_url="login",redirect_field_name=None,)
def procurement_reports_view(request):
    purchase_orders = (PurchaseOrder.objects.select_related("medicine", "supplier", "raised_by").order_by("-order_date"))
    status_filter = request.GET.get("status", "").strip()
    valid_statuses = (PurchaseOrder.objects.values_list("status", flat=True).distinct())

    if status_filter and status_filter in valid_statuses:
        purchase_orders = purchase_orders.filter(status=status_filter)

    context = {
        "purchase_orders": purchase_orders,
        "statuses": valid_statuses,
        "selected_status": status_filter,
        "total_orders": purchase_orders.count(),
    }
    return render(request,"procurement/procurement_reports.html",context,)

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
    pending_recommendations = ProcurementRecommendation.objects.filter(
        status=ProcurementRecommendation.Status.PENDING,
        purchase_order__isnull=True
    ).select_related(
        'medicine',
        'raised_by'
    ).order_by('-created_at')

    awaiting_approval_orders = PurchaseOrder.objects.filter(
        status=PurchaseOrder.Status.PENDING_ADMIN_REVIEW
    ).select_related(
        'medicine',
        'supplier',
        'raised_by'
    ).order_by('-order_date')

    approved_orders = PurchaseOrder.objects.filter(
        status=PurchaseOrder.Status.APPROVED
    ).select_related(
        'medicine',
        'supplier',
        'raised_by'
    ).order_by('-order_date')

    awaiting_delivery_orders = PurchaseOrder.objects.filter(
        status=PurchaseOrder.Status.PLACED_WITH_SUPPLIER
    ).select_related(
        'medicine',
        'supplier',
        'raised_by'
    ).order_by('-order_date')

    rejected_orders = PurchaseOrder.objects.filter(
        status=PurchaseOrder.Status.REJECTED
    ).select_related(
        'medicine',
        'supplier',
        'raised_by'
    ).order_by('-order_date')

    context = {
        'pending_recommendations': pending_recommendations,
        'pending_recommendations_count': pending_recommendations.count(),

        'awaiting_approval_orders': awaiting_approval_orders,
        'awaiting_approval_count': awaiting_approval_orders.count(),

        'approved_orders': approved_orders,
        'approved_orders_count': approved_orders.count(),

        'awaiting_delivery_orders': awaiting_delivery_orders,
        'awaiting_delivery_count': awaiting_delivery_orders.count(),

        'rejected_orders': rejected_orders,
        'rejected_orders_count': rejected_orders.count(),

        'today': timezone.localdate(),
    }
    return render(request,'hospital_admin/purchase_orders.html',context)

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

#System admin views based on their roles ( Access control, user's management, system settings,audit logs*,System health)
@login_required(login_url="/login/")
def system_admin_dashboard_view(request):
    role = getattr(request.user, "role", None)
    role_name = ((getattr(role, "name", "") or "").strip().casefold())

    if not ( request.user.is_superuser or role_name == "system administrator"): raise PermissionDenied( "Only System Administrators may access this page.")
    user = get_user_model()

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        try:

            #Updating user's role
            if action == "update_role":
                target = get_object_or_404( user,pk=request.POST.get("user_id"),)

                if target.pk == request.user.pk:raise ValueError("Use another System Administrator to change your own role.")
                assigned_role = get_object_or_404(Role, pk=request.POST.get("role_id"),)
                old_role = ( target.role.name if target.role else "No Role")
                new_role = assigned_role.name

                removing_admin_role = (target.is_active and old_role.strip().casefold() == "system administrator"
                    and new_role.strip().casefold() != "system administrator")

                if removing_admin_role:
                    active_admins = user.objects.filter(is_active=True,role__name__iexact="System Administrator",).count()

                    if active_admins <= 1:
                        raise ValueError( "The last active System Administrator cannot be reassigned. Assign another administrator first.")

                target.role = assigned_role
                target.save(update_fields=["role"])

                AuditLog.objects.create(
                    user=request.user,
                    action="User role changed",
                    entity_type="User",
                    details=(f"Account {target.username}: "f"{old_role} -> {new_role}."
                    ),
                )
                messages.success(request,f"Role updated for {target.username}.",)

            # ACTIVATE OR DEACTIVATE USER
            elif action == "toggle_active":
                target = get_object_or_404(user,pk=request.POST.get("user_id"),)

                if target.pk == request.user.pk: raise ValueError( "You cannot deactivate your own account.")
                is_system_admin = ( target.role is not None and target.role.name.strip().casefold() == "system administrator")

                if target.is_active and is_system_admin:
                    active_admins = user.objects.filter(is_active=True,role__name__iexact="System Administrator",).count()

                    if active_admins <= 1:
                        raise ValueError("The last active System Administrator cannot be deactivated. Activate another administrator first.")

                target.is_active = not target.is_active
                target.save(update_fields=["is_active"])
                AuditLog.objects.create(
                    user=request.user,
                    action=( "User account activated" if target.is_active else "User account deactivated"),
                    entity_type="User",
                    details=( f"Account {target.username}; " f"active={target.is_active}."
                    ),
                )
                messages.success(  request,f"Account {target.username} is now " f"{'active' if target.is_active else 'inactive'}.",)

            # CREATE A SUPPORTED ROLE
            elif action == "create_role":
                role_name_input = request.POST.get( "role_name", "").strip()
                description = request.POST.get( "role_description", "").strip()

                if not role_name_input: raise ValueError("Role name is required.")
                role_definition = Role.SUPPORTED_ROLES.get( role_name_input.casefold())

                if role_definition is None:
                    raise ValueError(
                        "Choose a supported application role: "
                        "System Administrator, Hospital Administrator, "
                        "Pharmacist, Store Manager, or Procurement Officer."
                    )
                canonical_name, default_description = role_definition

                if Role.objects.filter( name__iexact=canonical_name).exists():
                    raise ValueError("A role with that name already exists.")

                new_role = Role.objects.create( name=canonical_name, description=description or default_description,)
                AuditLog.objects.create(
                    user=request.user,
                    action="Role created",
                    entity_type="Role",
                    details=f"Created role {new_role.name}.",
                )
                messages.success( request,f"Role {new_role.name} created.",)

            # SAVE SYSTEM SETTING
            elif action == "save_setting":
                key = request.POST.get("key", "").strip()
                value = request.POST.get("value", "").strip()
                description = request.POST.get("description", "").strip()

                if not key or not value: raise ValueError( "Setting key and value are required.")
                setting, created = (
                    SystemSetting.objects.update_or_create(
                        key=key,
                        defaults={
                            "setting_key": key,
                            "value": value,
                            "setting_value": value,
                            "description": description,
                        },
                    )
                )

                AuditLog.objects.create(
                    user=request.user,
                    action="System setting saved",
                    entity_type="SystemSetting",
                    details=(
                        f"Setting {key} "
                        f"{'created' if created else 'updated'}."
                    ),
                )
                messages.success( request,f"System setting '{key}' saved.",)
            else: raise ValueError( "Unknown administration action.")
        except ValueError as exc: messages.error(request, str(exc))
        return redirect("system_admin/dashboard.html")

    context = {
        "total_users": user.objects.count(),
        "active_users": user.objects.filter(is_active=True).count(),
        "inactive_users": user.objects.filter( is_active=False).count(),
        "total_medicines": Medicine.objects.count(),
        "total_batches": MedicineBatch.objects.count(),
        "recent_logs": AuditLog.objects.select_related("user").order_by("-created_at")[:20],
        "settings_count": SystemSetting.objects.count(),
        "users": user.objects.select_related("role").order_by("username"),
        "roles": Role.objects.order_by("name"),
        "settings": SystemSetting.objects.order_by("key"),
    }
    return render(request,"system_admin/dashboard.html",context,)

#SYSTEM ADMINISTRATOR ACCESS CONTROL
def _require_system_admin(request):
    role = getattr(request.user, "role", None)
    role_name = ((getattr(role, "name", "") or "").strip().casefold())
    if not (request.user.is_superuser or role_name == "system administrator"
    ): raise PermissionDenied("Only System Administrators may access this page.")

# SYSTEM ADMINISTRATOR USER MANAGEMENT
@transaction.atomic
@login_required(login_url="/login/")
def system_admin_users_view(request):
    _require_system_admin(request)
    user = get_user_model()

    if request.method == "POST":
        action = request.POST.get("action", "").strip()

        try:
            # CREATE USER ACCOUNT
            if action == "create_user":
                username = request.POST.get("username", "").strip()
                first_name = request.POST.get("first_name", "").strip()
                last_name = request.POST.get("last_name", "").strip()
                other_name = request.POST.get("other_name", "").strip()
                email = request.POST.get("email", "").strip()
                phone_number = request.POST.get("phone_number", "").strip()
                role_id = request.POST.get("role_id", "").strip()

                if not all([
                    username, first_name, last_name,
                    email, phone_number, role_id
                ]):
                    raise ValueError(
                        "Username, first name, surname, email, "
                        "phone number and role are required."
                    )

                if not phone_number or len(phone_number) >15:
                    raise ValueError("Enter a valid phone number")

                if user.objects.filter(username__iexact=username).exists():
                    raise ValueError("That username already exists.")

                if user.objects.filter(email__iexact=email).exists():
                    raise ValueError("That email address is already registered.")

                assigned_role = get_object_or_404(Role, pk=role_id)
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
                new_user.save()

                # GENERATE ACCOUNT ACTIVATION LINK
                uid = urlsafe_base64_encode(force_bytes(new_user.pk))
                token = default_token_generator.make_token(new_user)

                activation_url = request.build_absolute_uri(
                    reverse(
                        "activate_account",
                        kwargs={
                            "uidb64": uid,
                            "token": token,
                        },
                    )
                )

                # SEND ACTIVATION EMAIL
                send_mail(
                    subject="Activate Your Medicine FEFO System Account",
                    message=(
                        f"Hello {new_user.first_name},\n\n"
                        "A System Administrator has created an account for you.\n\n"
                        "Use the link below to establish your password and activate "
                        "your account:\n\n"
                        f"{activation_url}\n\n"
                        "This link expires after 24 hours and can only be used once.\n\n"
                        "If you were not expecting this account, contact your "
                        "System Administrator."
                    ),
                    from_email=None,
                    recipient_list=[new_user.email],
                    fail_silently=False,
                )

                AuditLog.objects.create(
                    user=request.user,
                    action="User account created",
                    entity_type="User",
                    details=(
                        f"Created inactive account {username}; "
                        f"email={email}; role={assigned_role.name}."
                    ),
                    ip_address=request.META.get("REMOTE_ADDR"),
                )

                messages.success(request,f"Account for {username} created successfully. "
                    "The account is inactive pending activation."
                )
                return redirect("system_admin/users")

            # EXISTING ACCOUNT MANAGEMENT
            target = get_object_or_404(user, pk=request.POST.get("user_id"),)

            # ACTIVATE OR DEACTIVATE ACCOUNT
            if action == "toggle_active":
                if target.pk == request.user.pk:
                    raise ValueError("You cannot deactivate your own account.")

                is_system_admin = (target.role is not None and target.role.name.strip().casefold() == "system administrator")

                if target.is_active and is_system_admin:
                    active_admins = user.objects.filter(is_active=True,role__name__iexact="System Administrator",).count()

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
                    action=("User account activated"if target.is_active else "User account deactivated"),
                    entity_type="User",
                    details=(
                        f"Account {target.username}; "
                        f"active={target.is_active}."),
                    ip_address=request.META.get("REMOTE_ADDR"),
                )
                messages.success( request,f"Account {target.username} is now " f"{'active' if target.is_active else 'inactive'}.", )

            # UPDATE USER ROLE
            elif action == "update_role":
                if target.pk == request.user.pk:
                    raise ValueError("Use another System Administrator to change your own role.")

                assigned_role = get_object_or_404(Role,pk=request.POST.get("role_id"),)
                old_role = ( target.role.name if target.role else "No Role")
                new_role = assigned_role.name

                removing_admin_role = (target.is_active and old_role.strip().casefold()
                    == "system administrator" and new_role.strip().casefold() != "system administrator")

                if removing_admin_role:
                    active_admins = user.objects.filter(is_active=True,role__name__iexact="System Administrator",).count()

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
                    details=(
                        f"Account {target.username}: "
                        f"{old_role} -> {new_role}."
                    ),
                    ip_address=request.META.get("REMOTE_ADDR"),
                )
                messages.success(request,f"Role updated for {target.username}.",)

            else:
                messages.error( request,"Invalid user management action.",)

        except ValueError as exc: messages.error(request, str(exc))
        return redirect("system_admin_users")

    context = {
        "users": user.objects.select_related("role").order_by("username"),
        "roles": Role.objects.order_by("name"),
        "total_users": user.objects.count(),
        "active_users": user.objects.filter(is_active=True).count(),
        "inactive_users": user.objects.filter(is_active=False).count(),
    }
    return render(request, "system_admin/users.html", context)

#SYSTEM ADMINISTRATOR ROLES AND ACCESS CONTROL
@login_required(login_url="/login/")
def system_admin_roles_view(request):
    _require_system_admin(request)
    user = get_user_model()
    context = {
        "roles": Role.objects.order_by("name"),
        "users": user.objects.select_related("role").order_by("username"),
    }
    return render(request,"system_admin/roles.html", context,)

#SYSTEM ADMINISTRATOR SYSTEM SETTINGS
@login_required(login_url="/login/")
def system_admin_settings_view(request):
    _require_system_admin(request)
    context = {
        "settings": SystemSetting.objects.order_by("key"),
        "settings_count": SystemSetting.objects.count(),
    }
    return render(request,"system_admin/settings.html",context,)

#SYSTEM ADMINISTRATOR AUDIT LOGS
@login_required(login_url="/login/")
def system_admin_audit_logs_view(request):
    _require_system_admin(request)
    context = { "recent_logs": (AuditLog.objects.select_related("user").order_by("-created_at")[:200]),}
    return render(request,"system_admin/audit.html",context,)

# SYSTEM ADMINISTRATOR SYSTEM HEALTH
@login_required(login_url="/login/")
def system_admin_health_view(request):
    _require_system_admin(request)
    return render(request,"system_admin/health.html",{},)

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
            is_resolved=user_alert.is_resolved,
            is_acknowledged=user_alert.is_read,
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