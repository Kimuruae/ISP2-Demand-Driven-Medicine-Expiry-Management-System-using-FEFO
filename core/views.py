from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.contrib import messages
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.http import HttpResponseForbidden
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.db import transaction
from django.db.models import Sum
from decimal import Decimal, InvalidOperation
from functools import wraps
from datetime import timedelta
from .fefo_engine import FEFOEngine
from .forecasting_engine import ForecastingEngine

from .models import (AuditLog,DemandForecast,DispensingTransaction,ExpiryAlert,Medicine,MedicineBatch,
                     ProcurementRecommendation,PurchaseOrder,Role,Supplier,SystemSetting,)

def route_user_by_role(user):
    if user.is_superuser:return redirect("system_admin_dashboard")
    role = getattr(user, "role", None)
    role_name = (getattr(role, "name", "") or "").strip().casefold()

    destinations = {
        "pharmacist": "dispense",
        "store manager": "inventory",
        "procurement officer": "procurement",
        "hospital admin": "admin_dashboard",
        "hospital administrator": "admin_dashboard",
    }
    destination = destinations.get(role_name)
    if destination: return redirect(destination)
    return HttpResponseForbidden(f"No page is configured for role: {role_name or 'no role assigned'}.")

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
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        role_id = request.POST.get('role')
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')

        if password != password_confirm:
            messages.error(request, "Password validation failed. Values do not match.")
            return render(request, 'core/register.html', {'roles': Role.objects.all()})

        if user.objects.filter(username=username).exists():
            messages.error(request, "A user account with that username already exists.")
            return render(request, 'core/register.html', {'roles': Role.objects.all()})

        try:
            selected_role = Role.objects.get(id=role_id)
            new_user = user(username=username, email=email, role=selected_role)
            new_user.set_password(password)
            new_user.save()
            messages.success(request, f"Account profile for {username} created successfully.")
            return redirect('login')
        except Role.DoesNotExist:
            messages.error(request, "Selected operational title is invalid.")
        except Exception as e:
            messages.error(request, f"Database transaction failed: {str(e)}")

    roles = Role.objects.all()
    # MATCHES: core/templates/core/register.html
    return render(request, 'core/register.html', {'roles': roles})

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
                #Redirect according to the user's role.
                return route_user_by_role(user)
            messages.error(request,"Invalid username or password credentials.")
        return render(request, "core/login.html")

def logout_view(request):
    logout(request)
    messages.info(request, "Logged out successfully.")
    return redirect('login')
def home_redirect(request):
    if request.user.is_authenticated: return route_user_by_role(request.user)
    return render(request, 'core/index.html')

def about(request):
    return render(request, 'core/about.html')

def features(request):
    return render(request, 'core/features.html')

def contact(request):
    return render(request, 'core/contact.html')

@role_required('pharmacist')
@user_passes_test(is_pharmacist, login_url='/login/')
def dispense_view(request):
    @login_required(login_url="/login/")
    def auth_debug_view(request):
        return JsonResponse({
            "authenticated": request.user.is_authenticated,
            "username": request.user.username,
            "session_key_exists": request.session.session_key is not None,
            "role": ( request.user.role.name
                      if getattr(request.user, "role", None)else None),
        })
    print("DISPENSE CHECK:", {"authenticated": request.user.is_authenticated,
        "user_id": request.user.pk if request.user.is_authenticated else None,
        "session_key": request.session.session_key,
    })
    if not is_pharmacist(request.user):
        return HttpResponseForbidden( "Access denied. A pharmacist account is required.")
    if request.method == "POST":
        medicine_id = request.POST.get('medicine_id')
        qty_to_dispense = int(request.POST.get('quantity', 0))
        patient_id = request.POST.get('patient_identifier', '').strip()

        if qty_to_dispense <= 0:
            messages.error(request, "Quantity must be greater than zero.")
            return redirect('dispense')

        try:
            with transaction.atomic():
                medicine = get_object_or_404(Medicine, id=medicine_id)
                available_batches = MedicineBatch.objects.filter(
                    medicine=medicine, quantity_available__gt=0,
                    status="Active", expiry_date__gt=timezone.now().date()
                ).order_by('expiry_date')
                if not available_batches.exists():raise ValueError(f"No active stock available for {medicine.name}.")

                remaining_qty = qty_to_dispense
                total_available = sum(b.quantity_available for b in available_batches)
                if total_available < qty_to_dispense:
                    raise ValueError(f"Insufficient stock available. Total Hand: {total_available}")

                for batch in available_batches:
                    if remaining_qty <= 0: break
                    dispense_amount = min(batch.quantity_available, remaining_qty)
                    batch.quantity_available -= dispense_amount
                    if batch.quantity_available == 0: batch.status = "Depleted"
                    batch.save()

                    DispensingTransaction.objects.create(
                        medicine=medicine, batch=batch, dispensed_by=request.user,
                        quantity_dispensed=dispense_amount, is_override=False,
                        patient_identifier=patient_id, notes="Automated FEFO system processing."
                    )
                    remaining_qty -= dispense_amount

            messages.success(request, f"Successfully dispensed {qty_to_dispense} units of {medicine.name}.")
            return redirect('dispense')
        except Exception as e:
            messages.error(request, f"Transaction aborted: {str(e)}")
            return redirect('dispense')

    medicines = Medicine.objects.filter(is_active=True).order_by('name')
    batches = MedicineBatch.objects.filter(quantity_available__gt=0, status="Active", expiry_date__gt=timezone.now().date()
    ).select_related('medicine').order_by('expiry_date')
    return render(request, "dispense.html", {"medicines": medicines, "batches": batches})

@role_required('Store Manager')
def store_manager_inventory_view(request):
    if request.method == "POST":
        medicine_id = request.POST.get("medicine_id")
        batch_num = request.POST.get("batch_number", "").strip()
        mfg_date = request.POST.get("manufacturing_date")
        exp_date = request.POST.get("expiry_date")

        try:
            quantity = int(request.POST.get("quantity", 0))

            if quantity <= 0: raise ValueError("Quantity must be greater than zero.")
            medicine = Medicine.objects.get(id=medicine_id,is_active=True)

            MedicineBatch.objects.create(
                medicine=medicine,
                batch_number=batch_num,
                quantity_initially_received=quantity,
                quantity_available=quantity,
                manufacturing_date=mfg_date,
                expiry_date=exp_date,
                status="Active",
            )
            messages.success(request,f"Batch {batch_num} for {medicine.name} registered into inventory.")

        except (Medicine.DoesNotExist, ValueError) as e:
            messages.error(request, f"Stock intake failed: {e}")
        except Exception as e:
            messages.error(request, f"Stock intake operation failed: {e}")
        return redirect("inventory")
#Loading inventory data for GET requests
    medicines = Medicine.objects.filter(is_active=True ).order_by("name")
    active_batches = (MedicineBatch.objects.filter(quantity_available__gt=0,expiry_date__gt=timezone.now().date(),
    ).select_related("medicine").order_by("expiry_date"))
    return render(request,"inventory.html",{"medicines": medicines,"active_batches": active_batches,},)

@login_required(login_url="/login/")
@role_required("Store Manager")
def inventory_reports_view(request):
    today = timezone.now().date()
    all_batches = (
        MedicineBatch.objects
        .select_related("medicine")
        .order_by("expiry_date")
    )

    context = {
        "all_batches": all_batches,
        "total_batches": all_batches.count(),
        "total_units": (
            all_batches.aggregate(total=Sum("quantity_available"))["total"] or 0
        ),
        "expired_batches": all_batches.filter(
            expiry_date__lt=today
        ).count(),
        "expiring_soon": all_batches.filter(
            expiry_date__gte=today,
            expiry_date__lte=today + timedelta(days=30),
            quantity_available__gt=0,
        ).count(),
    }
    return render(request, "inventory_reports.html", context)

@login_required(login_url="/login/")
@role_required("Store Manager")
def inventory_alerts_view(request):
    today = timezone.now().date()
    warning_date = today + timedelta(days=30)
    context = {"expired_batches": ( MedicineBatch.objects.filter(expiry_date__lt=today, quantity_available__gt=0,)
            .select_related("medicine")
            .order_by("expiry_date")
        ),
        "expiring_batches": ( MedicineBatch.objects.filter(
                expiry_date__gte=today,
                expiry_date__lte=warning_date,
                quantity_available__gt=0,
            )
            .select_related("medicine")
            .order_by("expiry_date")
        ),
        "out_of_stock_batches": (
            MedicineBatch.objects
            .filter(quantity_available__lte=0)
            .select_related("medicine")
            .order_by("expiry_date")
        ),
        "today": today,
    }
    return render(request, "inventory_alerts.html", context)

@login_required(login_url="/login/")
@role_required("Store Manager")
def inventory_recommendations_view(request):
    low_stock_threshold = 20
    today = timezone.now().date()
    recommendations = []
    medicines = Medicine.objects.filter(is_active=True).order_by("name")

    for medicine in medicines:
        available_stock = (
            MedicineBatch.objects
            .filter(
                medicine=medicine,
                expiry_date__gte=today,
                quantity_available__gt=0,
                status="Active",
            )
            .aggregate(total=Sum("quantity_available"))["total"] or 0
        )

        if available_stock <= low_stock_threshold:
            recommendations.append({
                "medicine": medicine,
                "available_stock": available_stock,
                "recommended_action": (
                    "Review procurement urgently"
                    if available_stock == 0
                    else "Review stock and procurement needs"
                ),
            })

    context = {"recommendations": recommendations,"low_stock_threshold": low_stock_threshold,}
    return render(request, "inventory_recommendations.html", context)

@login_required
@role_required("Store Manager")
def store_manager_recommendations_view(request):
    if request.method != "POST":  return redirect("inventory_recommendations")

    try:
        medicine_id = request.POST.get("medicine_id", "").strip()
        quantity = int(request.POST.get("recommended_quantity", "0"))
        urgency = request.POST.get("urgency_level", "").strip()
        reasoning = request.POST.get("justification", "").strip()

        if quantity <= 0: raise ValueError("Recommended quantity must be greater than zero.")
        if not urgency: raise ValueError("Please select an urgency level.")

        medicine = get_object_or_404( Medicine, id=medicine_id,is_active=True,)
        ProcurementRecommendation.objects.create(
            medicine=medicine,
            recommended_quantity=quantity,
            urgency_level=urgency,
            reasoning=reasoning,
            raised_by=request.user,
            status="Pending Review",
        )
        messages.success( request,f"Procurement recommendation for {medicine.name} submitted successfully.",)
    except (ValueError, TypeError) as exc: messages.error(request, str(exc))
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

            if quantity <= 0:
                raise ValueError("Quantity must be greater than zero.")

            if not supplier_name:
                raise ValueError("Supplier name is required.")

            medicine = get_object_or_404(
                Medicine,
                id=medicine_id,
                is_active=True,
            )

            supplier, _ = Supplier.objects.get_or_create(
                supplier_name=supplier_name,
                defaults={"name": supplier_name},
            )

            PurchaseOrder.objects.create(
                medicine=medicine,
                supplier=supplier,
                quantity_ordered=quantity,
                raised_by=request.user,
                status="Pending Admin Review",
            )

            if rec_id:
                ProcurementRecommendation.objects.filter(
                    id=rec_id,
                    medicine=medicine,
                    status="Pending Review",
                ).update(status="Converted to PO")

            messages.success(
                request,
                f"Purchase order for {medicine.name} "
                "forwarded to Administration.",
            )

        except (ValueError, TypeError) as exc:
            messages.error(request, str(exc))
        return redirect("procurement")

    medicines = Medicine.objects.filter(is_active=True).order_by("name")
    recommendations = (ProcurementRecommendation.objects.filter(status="Pending Review")
        .select_related("medicine")
        .order_by("-created_at"))

    forecasts = []
    three_months_ago = timezone.now() - timedelta(days=90)

    for medicine in medicines:
        total_dispensed = (
            DispensingTransaction.objects.filter(
                medicine=medicine,dispensed_at__gte=three_months_ago,).aggregate(
                total=Sum("quantity_dispensed"))["total"] or 0)
        average_monthly = total_dispensed / 3.0
        current_stock = (
            MedicineBatch.objects.filter(
                medicine=medicine,
                quantity_available__gt=0,
                expiry_date__gt=timezone.localdate(),
                status="Active",
            ).aggregate(
                total=Sum("quantity_available")
            )["total"]
            or 0
        )

        forecasted_demand = max(
            0,
            int(round(average_monthly * 1.2)) - current_stock,
        )

        forecasts.append({
            "medicine": medicine,
            "current_stock": current_stock,
            "avg_monthly_dispensed": round(average_monthly, 1),
            "forecasted_demand": (
                forecasted_demand
                if forecasted_demand > 0
                else int(round(average_monthly))
            ),
        })

    return render(
        request,
        "procurement.html",
        {
            "medicines": medicines,
            "recommendations": recommendations,
            "forecasts": forecasts,
        },
    )


@login_required(login_url="/login/")
@role_required("Procurement Officer")
def place_supplier_order_view(request, po_id):
    if request.method != "POST":
        messages.error(
            request,
            "Supplier orders must be submitted using POST.",
        )
        return redirect("procurement")

    po = get_object_or_404(
        PurchaseOrder.objects.select_related("supplier"),
        id=po_id,
        status="Approved",
    )

    po.status = "Placed with Supplier"
    po.save(update_fields=["status"])

    messages.success(
        request,
        f"Purchase Order #{po.id} placed with "
        f"{po.supplier.supplier_name}.",
    )
    return redirect("procurement")

@role_required('Hospital Admin','Hospital Administrator')
def hospital_admin_dashboard_view(request):
    total_batches = MedicineBatch.objects.filter(quantity_available__gt=0).count()
    active_alerts_count = ExpiryAlert.objects.filter(is_resolved=False).count()
    total_dispenses = DispensingTransaction.objects.count()
    pending_pos = PurchaseOrder.objects.filter(status="Pending Admin Review").select_related('medicine', 'raised_by').order_by('-order_date')
    global_transactions = DispensingTransaction.objects.all().select_related('medicine', 'batch', 'dispensed_by').order_by('-dispensed_at')[:10]
    context = {"total_batches": total_batches,"active_alerts_count": active_alerts_count,"total_dispenses": total_dispenses,"pending_pos": pending_pos,"global_transactions": global_transactions,}

    #MATCHES: core/templates/admin_dashboard.html
    return render(request, "admin_dashboard.html", context)

@role_required('Hospital Admin', 'Hospital Administrator')
def hospital_admin_process_po_view(request, po_id, action):
    if request.method != "POST":
        messages.error( request,"Purchase orders must be processed using a POST request.",)
        return redirect("admin_dashboard")

    po = get_object_or_404( PurchaseOrder, id=po_id,status="Pending Admin Review",)
    normalized_action = action.strip().casefold()

    if normalized_action == "approve":
        po.status = "Approved"
        success_message = (
            f"Purchase Order REQ #{po.pk} authorized."
        )

    elif normalized_action == "reject":
        po.status = "Rejected"
        success_message = (
            f"Purchase Order REQ #{po.pk} declined."
        )

    else:
        messages.error(request, "Invalid purchase-order action.")
        return redirect("admin_dashboard")

    po.save(update_fields=["status"])
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
            f"status={po.status}."
        ),
    )

    if normalized_action == "approve":
        messages.success(request, success_message)
    else:
        messages.warning(request, success_message)
    return redirect("admin_dashboard")

@login_required(login_url="/login/")
def system_admin_dashboard_view(request):
    role = getattr(request.user, "role", None)
    role_name = ((getattr(role, "name", "") or "").strip().casefold())

    if not ( request.user.is_superuser or role_name == "system administrator"): raise PermissionDenied( "Only System Administrators may access this page.")
    user = get_user_model()

    if request.method == "POST":
        action = request.POST.get("action", "").strip()

        try:
            # CREATE USER
            if action == "create_user":
                username = request.POST.get("username", "").strip()
                email = request.POST.get("email", "").strip()
                password = request.POST.get("password", "")
                role_id = request.POST.get("role_id", "").strip()

                if not username or not email or len(password) < 10: raise ValueError( "Enter a username, email, and password of at least 10 characters.")
                if user.objects.filter(username=username).exists(): raise ValueError("That username already exists.")

                assigned_role = get_object_or_404(Role, pk=role_id)
                new_user = user(
                    username=username,
                    email=email,
                    role=assigned_role,
                    is_active=True,
                )
                new_user.set_password(password)
                new_user.save()

                AuditLog.objects.create(
                    user=request.user,
                    action="User account created",
                    entity_type="User",
                    details=(
                        f"Created account {username} with role "
                        f"{assigned_role.name}."
                    ),
                )
                messages.success( request,f"Account {username} created and assigned to "f"{assigned_role.name}.",)

            # UPDATE USER ROLE
            elif action == "update_role":
                target = get_object_or_404(
                    user,
                    pk=request.POST.get("user_id"),
                )

                if target.pk == request.user.pk:
                    raise ValueError(
                        "Use another System Administrator to change "
                        "your own role."
                    )

                assigned_role = get_object_or_404(
                    Role,
                    pk=request.POST.get("role_id"),
                )

                old_role = ( target.role.name if target.role else "No Role")
                new_role = assigned_role.name

                removing_admin_role = (
                    target.is_active
                    and old_role.strip().casefold()
                    == "system administrator"
                    and new_role.strip().casefold()
                    != "system administrator"
                )

                if removing_admin_role:
                    active_admins = user.objects.filter(
                        is_active=True,
                        role__name__iexact="System Administrator",
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
                    details=(
                        f"Account {target.username}: "
                        f"{old_role} -> {new_role}."
                    ),
                )
                messages.success(request,f"Role updated for {target.username}.",)

            # ACTIVATE OR DEACTIVATE USER
            elif action == "toggle_active":
                target = get_object_or_404(
                    user,
                    pk=request.POST.get("user_id"),
                )

                if target.pk == request.user.pk: raise ValueError( "You cannot deactivate your own account.")
                is_system_admin = ( target.role is not None and target.role.name.strip().casefold() == "system administrator")

                if target.is_active and is_system_admin:
                    active_admins = user.objects.filter(
                        is_active=True,
                        role__name__iexact="System Administrator",
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
        return redirect("system_admin_dashboard")

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
    return render(request,"system_admin_dashboard.html",context,)