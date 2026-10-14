from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponseForbidden
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.db import transaction
from django.db.models import Sum
from django.contrib.auth import get_user_model
from datetime import timedelta
from .models import (Role, Medicine, MedicineBatch, ExpiryAlert, DemandForecast,
                     ProcurementRecommendation, DispensingTransaction, PurchaseOrder)

def route_user_by_role(user):
    if user.is_superuser:
        return redirect("admin_dashboard")

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
    if destination:
        return redirect(destination)
    return HttpResponseForbidden(
        f"No page is configured for role: {role_name or 'no role assigned'}."
    )

def is_pharmacist(user) ->bool:
    if not user.is_authenticated:return False
    if user.is_superuser: return True
    role = getattr(user, 'role', None)
    role_name = (getattr(role, "name", "") or "").strip().casefold()
    return role_name == "pharmacist"

def is_store_manager(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False) or getattr(user, 'is_staff', False):
        return True
    user_role = getattr(user, 'role', None)
    if user_role is not None:
        return str(user_role.name).strip().lower() == 'store manager'
    return False

def is_procurement_officer(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False) or getattr(user, 'is_staff', False):
        return True
    user_role = getattr(user, 'role', None)
    if user_role is not None:
        return 'procurement' in str(user_role.name).strip().lower()
    return False

def is_hospital_admin(user):
    if not user or not user.is_authenticated: return False
    if getattr(user, 'is_superuser', False): return True
    return bool(user.role and user.role.name in ['Hospital Admin', 'Hospital Administrator'])

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
        if request.user.is_authenticated: return route_user_by_role(request.user)

        if request.method == "POST":
            username_input = request.POST.get("username", "").strip()
            password_input = request.POST.get("password", "")
            user = authenticate(request,username=username_input,password=password_input )

            if user is not None:
                login(request, user)
                login(request, user)
                print("LOGIN CHECK:", {
                    "authenticated": request.user.is_authenticated,
                    "user_id": user.pk,
                    "session_key": request.session.session_key,
                })
                request.session.set_expiry(0)
                messages.success(request,f"Welcome, {user.username}. Login successful.")
                # IMPORTANT: Redirect according to the user's role.
                return route_user_by_role(user)
            messages.error(request,"Invalid username or password credentials.")
        return render(request, "core/login.html")


def logout_view(request):
    logout(request)
    messages.info(request, "Logged out successfully.")
    return redirect('login')
def home_redirect(request):
    if request.user.is_authenticated:
        return route_user_by_role(request.user)
    return render(request, 'core/index.html')

def about(request):
    return render(request, 'core/about.html')

def features(request):
    return render(request, 'core/features.html')

def contact(request):
    return render(request, 'core/contact.html')

@login_required (login_url='/login/')
@user_passes_test(is_pharmacist, login_url='/login/')
def dispense_view(request):
    @login_required(login_url="/login/")
    def auth_debug_view(request):
        return JsonResponse({
            "authenticated": request.user.is_authenticated,
            "username": request.user.username,
            "session_key_exists": request.session.session_key is not None,
            "role": (
                request.user.role.name
                if getattr(request.user, "role", None)
                else None
            ),
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

                if not available_batches.exists():
                    raise ValueError(f"No active stock available for {medicine.name}.")

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

    # MATCHES: core/templates/dispense.html
    return render(request, "dispense.html", {"medicines": medicines, "batches": batches})

@login_required(login_url='/login/')
@user_passes_test(is_store_manager, login_url='login', redirect_field_name=None)
def store_manager_inventory_view(request):
    if request.method == 'POST':
        medicine_id = request.POST.get('medicine_id')
        batch_num = request.POST.get('batch_number', '').strip()
        quantity = int(request.POST.get('quantity', 0))
        mfg_date = request.POST.get('manufacturing_date')
        exp_date = request.POST.get('expiry_date')

        try:
            medicine = Medicine.objects.get(id=medicine_id)
            MedicineBatch.objects.create(
                medicine=medicine, batch_number=batch_num, quantity_initially_received=quantity,
                quantity_available=quantity, manufacturing_date=mfg_date, expiry_date=exp_date, status="Active"
            )
            messages.success(request, f"Batch {batch_num} for {medicine.name} registered into inventory.")
            return redirect('inventory')
        except Exception as e:messages.error(request, f"Stock intake operation failed: {str(e)}")
        return redirect('inventory')
        medicines = Medicine.objects.filter(is_active=True).order_by('name')
        active_batches = MedicineBatch.objects.filter(quantity_available__gt=0, expiry_date__gt=timezone.now().date()
            ).select_related('medicine').order_by('expiry_date')
    return render(request, "inventory.html", {"medicines": medicines, "active_batches": active_batches})

@login_required(login_url='/login/')
@user_passes_test(is_store_manager, login_url='login', redirect_field_name=None)
def store_manager_recommendations_view(request):
    if request.method == 'POST':
        medicine_id = request.POST.get('medicine_id')
        qty = int(request.POST.get('recommended_quantity', 0))
        urgency = request.POST.get('urgency_level')
        justification = request.POST.get('justification', '').strip()

        try:
            medicine = Medicine.objects.get(id=medicine_id)
            ProcurementRecommendation.objects.create(
            medicine=medicine, recommended_quantity=qty, urgency_level=urgency,justification=justification, raised_by=request.user, status="Pending Review")
            messages.success(request, f"Procurement recommendation for {medicine.name} submitted successfully.")
            return redirect('inventory_recommendations')
        except Exception as e:(
            messages.error(request, f"Failed to submit recommendation: {str(e)}"))
    return redirect('inventory_recommendations')
medicines = Medicine.objects.filter(is_active=True).order_by('name')
recommendations = ProcurementRecommendation.objects.all().select_related('medicine', 'raised_by').order_by('-created_at')

# MATCHES: core/templates/inventory_recommendation.html
# return render(request, "inventory_recommendation.html", {"medicines": medicines, "recommendations": recommendations})

@login_required(login_url='/login/')
@user_passes_test(is_procurement_officer, login_url='login', redirect_field_name=None)
def procurement_dashboard_view(request):
    if request.method == 'POST':
        medicine_id = request.POST.get('medicine_id')
        quantity = int(request.POST.get('quantity', 0))
        supplier_name = request.POST.get('supplier_name', '').strip()
        rec_id = request.POST.get('recommendation_id')

        try:
            medicine = Medicine.objects.get(id=medicine_id)
            PurchaseOrder.objects.create(
                medicine=medicine, quantity=quantity, supplier_name=supplier_name,
                raised_by=request.user, status="Pending Admin Review"
            )
            if rec_id:
                ProcurementRecommendation.objects.filter(id=rec_id).update(status="Converted to PO")
            messages.success(request, f"Purchase order for {medicine.name} forwarded to Administration.")
            return redirect('procurement')
        except Exception as e:
            messages.error(request, f"Failed to record purchase order: {str(e)}")
            return redirect('procurement')

    # GET Request: Fetch formulations and calculate 3-Month Moving Average Demand Forecasts
    medicines = Medicine.objects.filter(is_active=True).order_by('name')
    recommendations = ProcurementRecommendation.objects.filter(status="Pending Review").select_related('medicine','raised_by')
    forecasts = []
    three_months_ago = timezone.now().date() - timedelta(days=90)

    for med in medicines:
        total_dispensed = DispensingTransaction.objects.filter(
            medicine=med,
            dispensed_at__date__gte=three_months_ago
        ).aggregate(total=Sum('quantity_dispensed'))['total'] or 0

        avg_monthly = total_dispensed / 3.0

        current_stock = MedicineBatch.objects.filter(
            medicine=med,
            quantity_available__gt=0,
            expiry_date__gt=timezone.now().date()
        ).aggregate(total=Sum('quantity_available'))['total'] or 0

        demand_forecast = max(0, int(round(avg_monthly * 1.2)) - current_stock)

        forecasts.append({
            "medicine": med,
            "current_stock": current_stock,
            "avg_monthly_dispensed": round(avg_monthly, 1),
            "forecasted_demand": demand_forecast if demand_forecast > 0 else int(round(avg_monthly))
        })

    return render(request, "procurement.html", {
        "medicines": medicines,
        "recommendations": recommendations,
        "forecasts": forecasts
    })


@login_required(login_url='/login/')
@user_passes_test(is_procurement_officer, login_url='login', redirect_field_name=None)
def place_supplier_order_view(request, po_id):
    if request.method == 'POST':
        po = get_object_or_404(PurchaseOrder, id=po_id, status="Approved")
        po.status = "Placed with Supplier"
        po.save()
        messages.success(request, f"Purchase Order #{po.id} successfully placed with {po.supplier_name}.")
    return redirect('procurement')

@login_required(login_url='/login/')
@user_passes_test(is_hospital_admin, login_url='login', redirect_field_name=None)
def hospital_admin_dashboard_view(request):
    total_batches = MedicineBatch.objects.filter(quantity_available__gt=0).count()
    active_alerts_count = ExpiryAlert.objects.filter(is_resolved=False).count()
    total_dispenses = DispensingTransaction.objects.count()
    pending_pos = PurchaseOrder.objects.filter(status="Pending Admin Review").select_related('medicine', 'raised_by').order_by('created_at')
    global_transactions = DispensingTransaction.objects.all().select_related('medicine', 'batch', 'dispensed_by').order_by('-dispensed_at')[:10]
    context = {"total_batches": total_batches,"active_alerts_count": active_alerts_count,"total_dispenses": total_dispenses,"pending_pos": pending_pos,"global_transactions": global_transactions,}

    #MATCHES: core/templates/admin_dashboard.html
    return render(request, "admin_dashboard.html", context)

@login_required(login_url='/login/')
@user_passes_test(is_hospital_admin, login_url='login', redirect_field_name=None)
def hospital_admin_process_po_view(request, po_id, action):
    if request.method == 'POST':
        po = get_object_or_404(PurchaseOrder, id=po_id, status="Pending Admin Review")
        if action == 'Approve':
            po.status = "Approved"
            messages.success(request, f"Purchase Order REQ #{po.id} authorized.")

        elif action == 'Reject':
            po.status = "Rejected"
            messages.warning(request, f"Purchase Order REQ #{po.id} declined.")
            po.save()
    return redirect('admin_dashboard')