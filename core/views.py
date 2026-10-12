from django.shortcuts import render, redirect
from urllib import request
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.csrf import csrf_protect
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from datetime import timedelta
from django.contrib.auth import get_user_model
from .models import ( Role,Medicine,MedicineBatch,ExpiryAlert,DemandForecast,ProcurementRecommendation,DispensingTransaction)

#CRUDE operations pipeline
def register_view(request):
    User = get_user_model()
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        role_id = request.POST.get('role')
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')

    # Validation
        if password != password_confirm:
            messages.error(request, "Password validation failed. Values do not match.")
            return render(request, 'core/register.html', {'roles': Role.objects.all()})

        if User.objects.filter(username=username).exists():
            messages.error(request, "A user account with that username already exists.")
            return render(request, 'core/register.html', {'roles': Role.objects.all()})

        try:
            #Fetch linked structural Role object
            selected_role = Role.objects.get(id=role_id)

            #user database entry but suspend immediate save tracking
            user = User(
                username=username,
                email=email,
                role=selected_role
            )

            # 3. Hash password using Django PBKDF2 cryptography functions
            user.set_password(password)
            user.save()

            messages.success(request, f"Account profile {username} created successfully.")
            return redirect('core/login')

        except Role.DoesNotExist:
            messages.error(request, "Selected operational title is invalid.")
        except Exception as e:
            messages.error(request, f"Database transaction failed: {str(e)}")

    #GET Handler: Extracts role vectors to feed the dropdown layout
    roles = Role.objects.all()
    return render(request, 'core/register.html', {'roles': roles})
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
@csrf_protect
def login_view(request):
    if request.user.is_authenticated:
        return route_user_by_role(request.user)

    if request.method == 'POST':
        username = request.POST.get('username','').strip()
        password = request.POST.get('password','')
        user = authenticate(request, username=username, password=password)

        if user is not None: login(request, user)
        messages.success(request, f"Welcome, {user.username}. Session initialized.")
        request.session.set_expiry(0)  # Session cookie drops instantly on browser close

        if user.is_superuser:
            messages.success(request, f"Welcome Administrator {user.username}.")
            return redirect('dashboard')
        elif user.role and user.role.name == 'Pharmacist':
         messages.success(request, f"Welcome Pharmacist {user.username}.")
         return redirect('dispense')
        elif user.role and user.role.name == 'Store Manager':
         messages.success(request, f"Welcome Store Manager {user.username}.")
         return redirect('inventory')
        elif user.Role and user.Role.name == 'Procurement Officer':
         messages.success(request, f"Welcome Procurement Officer {user.username}. Procurement console active.")
         return redirect('procurement')
        elif user.Role and user.Role.name == 'Hospital Admin':
         messages.success(request, f"Welcome Hospital Admin {user.username}. Hospital Admin console active.")
         return redirect('hospital_admin')
        else:
            messages.warning(request, f"Welcome {user.username}. Profile has no assigned role.")
            return redirect('index')
    else: messages.error(request, "Invalid credentials.")
    return render(request, 'core/login.html')

def logout_view(request):
    logout(request)
    messages.info(request, "Logged out successfully.")
    return redirect('login')

def home_redirect(request):
    if request.user.is_authenticated: return route_user_by_role(request.user)
    return redirect('login')

def is_pharmacist_or_admin(user):
    if user.is_superuser: return True
    return bool(user.is_authenticated and user.role is not None and user.role.name == "Pharmacist")

def is_pharmacist(user):
    if user.is_superuser:
        return True
    return bool(user.is_authenticated and user.role and user.role.name == 'Pharmacist')

def is_store_manager(user):
    if user.is_superuser:
        return True
    return bool(user.is_authenticated and user.role and user.role.name == 'Store Manager')
#FEFO algorithmic dispensing
@login_required
@user_passes_test(is_pharmacist, login_url='login', redirect_field_name=None)
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

            #Fetch valid stock pools prioritized by earliest expiration date first(FEFO)
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

            #Verification that the cumulative stock can fulfil the order else the pharmacist should request for procurement
            total_available = sum(b.quantity_available for b in available_batches)
            if total_available < qty_to_dispense:
                raise ValueError(f"Insufficient stock available for {medicine.name}. Request:{qty_to_dispense}, Total Hand: {total_available}")

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
            return redirect('dashboard'if request.user.is_superuser else 'dispense')

        except Exception as e:
            messages.error(request, f"Transaction aborted: {str(e)}")
            return redirect('dispense')

 #GET request handler-fetches the context to feed the interface
 medicines = Medicine.objects.filter(is_active=True)
 batches = MedicineBatch.objects.filter(quantity_available__gt=0,status="Active").select_related('medicine').order_by('expiry_date')
 return render(request,"dispense.html",{ "medicines": medicines, "batches": batches})

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
    return render(request, 'dashboard.html', context)

#MANAGEMENT LEDGERS & ANALYTICS REPORTS
def batch_list_view(request):
    batches = MedicineBatch.objects.all().select_related('medicine').order_by('expiry_date')
    return render(request, "batch_list.html", {"batches": batches})

@login_required
def alerts_view(request):
    alerts = ExpiryAlert.objects.filter(is_resolved=False).select_related('batch__medicine').order_by('-created_at')
    return render(request, "expiry_alerts.html", {"alerts": alerts})

@login_required
def reports_view(request):
    forecasts = DemandForecast.objects.all().select_related('medicine')
    recommendations = ProcurementRecommendation.objects.all().select_related('medicine')
    transactions = DispensingTransaction.objects.all().select_related('medicine', 'dispensed_by').order_by('-dispensed_at')[:10]
    context = {'forecasts': forecasts,'recommendations': recommendations,'transactions': transactions}
    return render(request, "reports.html", context)

@login_required
@user_passes_test(is_store_manager, login_url='login', redirect_field_name=None)
def inventory_view(request):
    available_batches = MedicineBatch.objects.filter(quantity_available__gt=0).select_related('medicine').order_by('expiry_date')
    return render(request, 'inventory.html', {'Available_batches': available_batches})

@login_required
@user_passes_test(is_pharmacist, login_url='login', redirect_field_name=None)
def pharmacist_reports_view(request):
    transactions = DispensingTransaction.objects.all().select_related('medicine', 'batch', 'dispensed_by').order_by('-dispensed_at')
    return render(request, "reports.html", {"transactions": transactions})

@login_required
@user_passes_test(is_pharmacist, login_url='login', redirect_field_name=None)
def pharmacist_alerts_view(request):
    alerts = ExpiryAlert.objects.filter(is_resolved=False).select_related('batch__medicine').order_by('batch__expiry_date')
    return render(request, "expiry_alert.html", {"alerts": alerts})

#PUBLIC PUBLIC-FACING LANDING ROUTING ENDPOINTS
def index(request):
    return render(request, 'core/index.html')

def about(request):
    return render(request, 'core/about.html')

def features(request):
    return render(request, 'core/features.html')

def contact(request):
    return render(request, 'core/contact.html')