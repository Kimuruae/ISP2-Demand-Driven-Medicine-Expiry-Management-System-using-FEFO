from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from datetime import timedelta
from .models import ( Medicine,MedicineBatch,ExpiryAlert,DemandForecast,ProcurementRecommendation,DispensingTransaction)

def route_user_by_role(user):
    if user.is_superuser: return redirect('dashboard')
    # Dynamic Role Evaluation Strategy per TAM onboarding specifications
    role_name = user.role.name if user.role else None
    if role_name == 'Pharmacist':return redirect('dispense')
    elif role_name == 'Store Manager':return redirect('inventory')
    elif role_name == 'Procurement Officer':return redirect('procurement')
    elif role_name == 'Hospital Admin':return redirect('dashboard')
    elif role_name == 'System Admin':return redirect('logs')
    return redirect('index')

#Authentication and routing
def login_view(request):
    if request.user.is_authenticated:
        return route_user_by_role(request.user)

    if request.method == 'POST':
        username = request.POST('username','').strip()
        password = request.POST('password','')
        user = authenticate(request, username=username, password=password)

        if user is not None: login(request, user)
        messages.success(request, f"Welcome, {user.username}. Session initialized.")
        return route_user_by_role(user)

    else: messages.error(request, "Invalid credentials.")
    return render(request, 'core/login.html')

def logout_view(request):
    logout(request)
    messages.info(request, "Logged out successfully.")
    return redirect('login')

def home_redirect(request):
    if request.user.is_authenticated: return route_user_by_role(request.user)
    return redirect('login')

def is_pharmacist(user):
    if user.is_superuser: return True
    return user.is_authenticated and user.role is not None and user.role.name == "Pharmacist"

#FEFO algorithmic dispensing
@user_passes_test(is_pharmacist, login_url='dispense.html')
def dispense_view(request):
 if request.method == "POST":
        medicine_id = request.POST.get('medicine')
        selected_batch_id = request.POST.get('batch')
        qty_to_dispense = int(request.POST.get('quantity', 0))
        patient_id = request.POST.get('patient_identifier', '')
        override_reason = request.POST.get('override_reason', '').strip()

        if qty_to_dispense <= 0:
            messages.error(request, "Dispensed quantity must be greater than zero.")
            return redirect('dispense')

        try:
            with transaction.atomic(): medicine = Medicine.objects.get(id=medicine_id)

            #Fetch valid stock pools prioritized by earliest expiration date first
            available_batches = MedicineBatch.objects.filter(
                medicine=medicine,
                quantity_available__gt=0,
                status="Active",
                expiry_date__gt=timezone.now().date()
            ).order_by('expiry_date')

            if not available_batches.exists():
                messages.error(request, f"No active inventory stock pools available for {medicine.name}.")
                return redirect('dispense')

            optimal_batch = available_batches.first()
            remaining_qty = qty_to_dispense

            # Track if a manual override occurred
            is_override = False
            if selected_batch_id and int(selected_batch_id) != optimal_batch.id:
                    is_override = True
                    if not override_reason:
                        raise ValueError("Clinical justification reason required for manual batch override.")
                    batches_to_process = MedicineBatch.objects.filter(id=selected_batch_id)
            else: batches_to_process = available_batches

            for batch in batches_to_process:
                if remaining_qty <= 0:break

                dispense_amount = min(batch.quantity_available, remaining_qty)
                batch.quantity_available -= dispense_amount

                if batch.quantity_available == 0: batch.status = "Depleted"
                batch.save()

            # Commit transaction entry
            DispensingTransaction.objects.create(
                        medicine=batch.medicine,
                        batch=batch,
                        dispensed_by=request.user,
                        quantity_dispensed=dispense_amount,
                        is_override=is_override,
                        patient_identifier=patient_id,
                        notes=override_reason if is_override else "Automated FEFO system selection processing."
                        )
            remaining_qty -= dispense_amount

            if remaining_qty > 0:raise ValueError(f"Insufficient stock. Could not fulfill remaining {remaining_qty} units.")
            messages.success(request, f"Successfully dispensed {qty_to_dispense} units of {medicine.name}.")
            return redirect('core/templates/dashboard'if request.user.is_superuser else 'core/templates/dispense')

        except Exception as e:
            messages.error(request, f"Transaction aborted: {str(e)}")
            return redirect('dispense')

 #GET request handler
 medicines = Medicine.objects.filter(is_active=True)
 batches = MedicineBatch.objects.filter(quantity_available__gt=0,status="Active").select_related('medicine').order_by('expiry_date')
 return render(request,"core/templates/dispense.html",{ "medicines": medicines, "batches": batches})

#Dashboard metrics
@login_required
def dashboard(request):
    today = timezone.now().date()
    ninety_days_from_now = today + timedelta(days=90)

    # Database aggregations
    active_batches = MedicineBatch.objects.filter(quantity_available__gt=0, status="Active")
    total_medicines = Medicine.objects.filter(is_active=True).count()
    total_stock_volume = sum(batch.quantity_available for batch in active_batches)

    # Expiry tracking categories
    near_expiry_count = MedicineBatch.objects.filter(
        expiry_date__lte=ninety_days_from_now,
        expiry_date__gte=today,
        quantity_available__gt=0
    ).count()

    expired_count = MedicineBatch.objects.filter(
        expiry_date__lt=today,
        quantity_available__gt=0
    ).count()

    # User context fallback checks
    if request.user.is_superuser:user_role = "System Administrator"
    else:user_role = request.user.role.name if request.user.role else "No Role Assigned"

    # Pending system warnings metric count
    active_alerts_count = ExpiryAlert.objects.filter(is_resolved=False).count()

    context = {
        'total_medicines': total_medicines,
        'total_batches': active_batches.count(),
        'total_stock_volume': total_stock_volume,
        'near_expiry_count': near_expiry_count,
        'expired_count': expired_count,
        'user_role': user_role,
        'total_alerts': active_alerts_count,
    }
    return render(request, 'core/templates/dashboard.html', context)

#MANAGEMENT LEDGERS & ANALYTICS REPORTS
def batch_list_view(request):
    batches = MedicineBatch.objects.all().select_related('medicine').order_by('expiry_date')
    return render(request, "core/templates/batch_list.html", {"batches": batches})

@login_required
def alerts_view(request):
    alerts = ExpiryAlert.objects.filter(is_resolved=False).select_related('batch__medicine').order_by('-created_at')
    return render(request, "core/templates/expiry_alerts.html", {"alerts": alerts})

@login_required
def reports_view(request):
    forecasts = DemandForecast.objects.all().select_related('medicine')
    recommendations = ProcurementRecommendation.objects.all().select_related('medicine')
    transactions = DispensingTransaction.objects.all().select_related('medicine', 'dispensed_by').order_by('-dispensed_at')[:10]
    context = {'forecasts': forecasts,'recommendations': recommendations,'transactions': transactions}
    return render(request, "core/templates/reports.html", context)

@login_required
def inventory_view(request):
    available_batches = MedicineBatch.objects.filter(quantity_available__gt=0).select_related('medicine').order_by('expiry_date')
    return render(request, 'core/templates/inventory.html', {'Available_batches': available_batches})

#PUBLIC PUBLIC-FACING LANDING ROUTING ENDPOINTS
def index(request):
    return render(request, 'core/index.html')

def about(request):
    return render(request, 'core/about.html')

def features(request):
    return render(request, 'core/features.html')

def contact(request):
    return render(request, 'core/contact.html')