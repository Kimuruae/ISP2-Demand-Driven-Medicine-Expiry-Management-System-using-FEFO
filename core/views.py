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
from django.db.models import Count, Sum, Q
from decimal import Decimal, InvalidOperation
from functools import wraps
from datetime import timedelta
from django.views.decorators.http import require_POST
from .fefo_engine import FEFOEngine
from .forecasting_engine import ForecastingEngine

from .models import (AuditLog,DemandForecast,DispensingTransaction,ExpiryAlert,Medicine,MedicineBatch,
                     ProcurementRecommendation,PurchaseOrder,Role,Supplier,SystemSetting,)

def route_user_by_role(user):
    if user.is_superuser:return redirect("system_admin_dashboard")
    role = getattr(user, "role", None)
    role_name = (getattr(role, "name", "") or "").strip().casefold()

    destinations = {
        "system administrator": "system_admin_dashboard",
        "pharmacist": "dispense",
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

def register_view(request):
        user = get_user_model()
        if request.user.is_authenticated:
            return route_user_by_role(request.user)

        if request.method == "POST":
            first_name = request.POST.get("first_name", "").strip()
            last_name = request.POST.get("last_name", "").strip()
            other_name = request.POST.get("other_name", "").strip()
            phone_number = request.POST.get("phone_number", "").strip()
            email = request.POST.get("email", "").strip().lower()
            username = request.POST.get("username", "").strip()
            password = request.POST.get("password", "")
            password_confirm = request.POST.get("password_confirm", "")

            form_data = {
                "first_name": first_name,
                "last_name": last_name,
                "other_name": other_name,
                "phone_number": phone_number,
                "email": email,
                "username": username,
            }
            errors = []

            if not first_name: errors.append("First name is required.")
            if not last_name: errors.append("Surname is required.")
            if not phone_number:errors.append("Phone number is required.")
            if not username: errors.append("Username is required.")
            if not email:errors.append("Email address is required.")
            if not password: errors.append("Password is required.")

            elif password != password_confirm: errors.append("The passwords do not match.")
            if username and user.objects.filter(username__iexact=username).exists():
                errors.append("That username is already registered.")

            if email and user.objects.filter(email__iexact=email).exists():
                errors.append("That email address is already registered.")

            if phone_number and len(phone_number) > 15:
                errors.append("Phone number must not exceed 15 characters.")

            if not errors and password:
                candidate = user( username=username,first_name=first_name,last_name=last_name, email=email,phone_number=phone_number,other_name=other_name,)

                try:
                    validate_password(password, user=candidate)
                except ValidationError as exc:
                    errors.extend(exc.messages)

            if errors:
                for error in errors: messages.error(request, error)
                return render( request,"core/register.html",{"form_data": form_data},)

            new_user = user(
                username=username,
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone_number=phone_number,
                other_name=other_name,
                role=None,
                is_active=False,
            )
            new_user.set_password(password)
            new_user.save()

            messages.success(request,"Registration submitted successfully. Awaiting System Administrator approval ")
            return redirect("login")
        return render(request, "core/register.html", {"form_data": {}})

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

                print("LOGIN CHECK:", {
                    "authenticated": request.user.is_authenticated,
                    "user_id": user.pk,
                    "session_key": request.session.session_key,
                })
                messages.success(request,f"Welcome, {user.username}. Login successful.")
                return route_user_by_role(user)  #Redirect according to the user's role.
            messages.error(request,"Invalid username or password credentials.")
        return render(request, "core/login.html")

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
    return render(request, 'core/index.html')

def about(request):
    return render(request, 'core/about.html')

def features(request):
    return render(request, 'core/features.html')

def contact(request):
    return render(request, 'core/contact.html')

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
        return redirect("dispense")

    today = timezone.localdate()
    medicines = Medicine.objects.filter(is_active=True).order_by("name")
    batches = (MedicineBatch.objects.filter(
        quantity_available__gt=0,
        status="Active",
        expiry_date__gt=today,
        medicine__is_active=True,)
        .select_related("medicine")
        .order_by("expiry_date", "id")
    )
    return render(request,"dispense.html",{"medicines": medicines,"batches": batches,},)

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

    return render(request, "pharmacist_dashboard.html", context)

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
    return render(request, "inventory.html", context)

@login_required(login_url="/login/")
@role_required("Store Manager")
def inventory_reports_view(request):
    today = timezone.localdate()
    all_batches = (MedicineBatch.objects.select_related("medicine").order_by("expiry_date", "medicine__name"))
    total_units = (all_batches.filter(quantity_available__gt=0).aggregate(total=Sum("quantity_available"))["total"] or 0)
    context = {
        "all_batches": all_batches,
        "total_batches": all_batches.count(),
        "total_units": total_units,
        "expired_batches": all_batches.filter(expiry_date__lt=today,quantity_available__gt=0,).count(),
        "expiring_soon": all_batches.filter(expiry_date__gte=today,expiry_date__lte=today + timedelta(days=30),quantity_available__gt=0,).count(),
        "today": today,
    }
    return render(request, "inventory_reports.html", context)

@login_required(login_url="/login/")
@role_required("Store Manager")
def inventory_alerts_view(request):
    today = timezone.localdate()
    warning_date = today + timedelta(days=30)

    context = {
        "expired_batches": (
            MedicineBatch.objects.filter(
                expiry_date__lte=today,
                quantity_available__gt=0,
            )
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

    return render(request, "inventory_alerts.html", context)

@login_required(login_url="/login/")
@role_required("Store Manager")
def inventory_recommendations_view(request):
    today = timezone.localdate()
    recommendations = []

    medicines = Medicine.objects.filter(
        is_active=True
    ).order_by("name")

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
    return render(request,"inventory_recommendations.html",context,)

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
                f"Medicine: {medicine.name}; "
                f"Quantity: {quantity}; "
                f"Urgency: {urgency}"
            ),
        )
        messages.success(request,f"Recommendation for {medicine.name} submitted to Procurement.",)
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
                        ProcurementRecommendation.objects.select_for_update().filter(
                            id=rec_id,
                            medicine=medicine,
                            status=ProcurementRecommendation.Status.PENDING,
                            purchase_order__isnull=True,
                        )
                    )

                supplier, _ = Supplier.objects.get_or_create(supplier_name=supplier_name,defaults={"name": supplier_name},)
                PurchaseOrder.objects.create(
                    medicine=medicine,
                    supplier=supplier,
                    recommendation=recommendation,
                    quantity_ordered=quantity,
                    raised_by=request.user,
                    status=PurchaseOrder.Status.PENDING_ADMIN_REVIEW,
                )

            messages.success(request,f"Purchase order for {medicine.name} forwarded to hospital admin.",)
        except (ValueError, TypeError) as exc:messages.error(request, str(exc))
        return redirect("procurement")

    medicines = Medicine.objects.filter(is_active=True).order_by("name")
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
    return render(request,"procurement.html",{"medicines": medicines,"recommendations": recommendations,"forecasts": forecasts,},)

@login_required(login_url="/login/")
@role_required("Procurement Officer")
def place_supplier_order_view(request, po_id):
    if request.method != "POST":
        messages.error(request,"Supplier orders must be submitted using POST.",)
        return redirect("procurement")

    po = get_object_or_404(
        PurchaseOrder.objects.select_related("supplier"),id=po_id,status=PurchaseOrder.Status.APPROVED,)
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
    return render(request, "admin_dashboard.html", context)

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
            PurchaseOrder.objects.select_for_update().select_related(
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
    return redirect("admin_dashboard")

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
    return render(request,"procurement_reports.html",context,)

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
            #Create new user
            if action == "create_user":
                username = request.POST.get("username", "").strip()
                email = request.POST.get("email", "").strip()
                password = request.POST.get("password", "")
                role_id = request.POST.get("role_id", "").strip()

                if not username or not email or len(password) < 10: raise ValueError( "Enter a username, email, and password of at least 10 characters.")
                if user.objects.filter(username=username).exists(): raise ValueError("That username already exists.")

                assigned_role = get_object_or_404(Role, pk=role_id)
                new_user = user(username=username,email=email,role=assigned_role,is_active=True,)
                new_user.set_password(password)
                new_user.save()

                AuditLog.objects.create(user=request.user,action="User account created",entity_type="User",
                    details=( f"Created account {username} with role "
                              f"{assigned_role.name}."),
                )
                messages.success( request,f"Account {username} created and assigned to "f"{assigned_role.name}.",)

            #Updating user's role
            elif action == "update_role":
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

#SYSTEM ADMINISTRATOR USER MANAGEMENT
@login_required(login_url="/login/")
def system_admin_users_view(request):
        _require_system_admin(request)
        user = get_user_model()

        if request.method == "POST":
            action = request.POST.get("action", "").strip()

            try:
                target = get_object_or_404(
                    user,
                    pk=request.POST.get("user_id"),
                )

                if action == "toggle_active":
                    if target.pk == request.user.pk:
                        raise ValueError("You cannot deactivate your own account.")

                    is_system_admin = (target.role is not None and target.role.name.strip().casefold()== "system administrator")
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
                        action=("User account activated" if target.is_active else "User account deactivated"),
                        entity_type="User",
                        details=(f"Account {target.username}; " f"active={target.is_active}."
                        ),
                    )
                    messages.success(request,f"Account {target.username} is now " f"{'active' if target.is_active else 'inactive'}.",)

                elif action == "update_role":
                    if target.pk == request.user.pk:
                        raise ValueError("Use another System Administrator to change your own role.")
                    assigned_role = get_object_or_404(Role,pk=request.POST.get("role_id"),)
                    old_role = (target.role.name if target.role else "No Role")
                    new_role = assigned_role.name
                    removing_admin_role = (target.is_active
                            and old_role.strip().casefold() == "system administrator" and new_role.strip().casefold() != "system administrator")

                    if removing_admin_role:
                        active_admins = user.objects.filter(is_active=True, role__name__iexact="System Administrator",).count()

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
                    )
                    messages.success(request,f"Role updated for {target.username}.",)

                else: messages.error(request,"Invalid user management action.",)
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

    #Existing persistent expiry alerts
    expiry_alerts = ExpiryAlert.objects.select_related("medicine", "batch", "batch__medicine"
    ).filter(Q(medicine__isnull=False) | Q(batch__isnull=False)).order_by("-created_at")

    for item in expiry_alerts:
        batch = item.batch
        medicine = item.medicine or (batch.medicine if batch else None)

        # A resolved alert remains visible in the register.
        days = item.days_to_expiry
        severity = item.severity or "Medium"

        if item.alert_type == "EXPIRED":
            title = "Expired medicine batch"
            severity = "Critical"
        else:
            title = "Medicine nearing expiry"

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
            medicine={"name": medicine.name,} if medicine else None,
            batch={"batch_number": batch.batch_number,"expiry_date": batch.expiry_date,} if batch else None,
            created_at=item.created_at,
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
                    medicine={"name": medicine.name},
                    batch={
                        "batch_number": batch.batch_number,
                        "expiry_date": batch.expiry_date,
                    },
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
                    severity=(
                        "High" if days_left <= 30
                        else "Medium"
                    ),
                    medicine={"name": medicine.name},
                    batch={
                        "batch_number": batch.batch_number,
                        "expiry_date": batch.expiry_date,
                    },
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
                    medicine={"name": medicine.name},
                    batch={"batch_number": batch.batch_number},
                    reasoning=(
                        "This batch has no available stock. Check other "
                        "eligible batches before declaring a medicine stock-out."
                    ),
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
        recommendations = ProcurementRecommendation.objects.select_related(
            "medicine"
        ).filter(
            Q(status__iexact="Pending")
            | Q(is_actioned=False)
        ).order_by("-created_at")

        for recommendation in recommendations:
            medicine = recommendation.medicine
            urgency = (
                getattr(recommendation, "urgency_level", "Medium")
                or "Medium"
            )
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
                medicine={"name": medicine.name} if medicine else None,
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

            if status_key in {"completed", "received", "cancelled", "rejected"}:
                continue

            # Procurement users handle orders; hospital administrators
            # see orders requiring their review.
            if role in {"hospital admin", "hospital administrator"}:
                if not any(
                    marker in status_key
                    for marker in ("pending admin", "awaiting approval","pending approval", "review")
                ):
                    continue

            add_alert(
                alert_type="PURCHASE_ORDER",
                title="Purchase order requires attention",
                severity="High" if "approval" in status_key or "review" in status_key
                else "Medium",
                medicine={"name": po.medicine.name,} if po.medicine else None,
                created_at=po.order_date,
                status="Open",
                reasoning=(
                    f"Order status: {status_text}. "
                    f"Supplier: {po.supplier.supplier_name if po.supplier else 'Not assigned'}."),
                source_id=po.pk,
                source_type="purchase_order",
                action_url=("/dashboard/" if role in {"hospital admin", "hospital administrator"}
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