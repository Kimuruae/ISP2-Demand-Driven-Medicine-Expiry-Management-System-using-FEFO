from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test

from django.utils import timezone
from datetime import timedelta
from .models import Medicine, MedicineBatch, ExpiryAlert

def login_view(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('dashboard')
    return render(request, 'core/login.html')

def is_pharmacist(user):
    return user.role.name == 'Pharmacist'

@user_passes_test(is_pharmacist)
def dispense_view(request):
    # Only pharmacists can access this
    pass

def home_redirect(request):
    return redirect('dashboard')


@login_required
def dashboard(request):
    #Fetch data from the database
    total_batches = MedicineBatch.objects.all().order_by('expiry_date')
    total_medicines = Medicine.objects.count()

    #Calculate expiring soon (within 90 days)
    today = timezone.now().date()
    ninety_days_from_now = today + timedelta(days=90)

    expiring_soon = MedicineBatch.objects.filter(
        expiry_date__lte=ninety_days_from_now,
        expiry_date__gte=today,
        quantity_available__gt=0
    ).count()

    #Get user role (safely)
    user_role = request.user.role.name if request.user.role else "No Role Assigned"

    #Pass data to the template via context dictionary
    context = {'Total medicine:': total_medicines,
               'Total Batches:': total_batches,
               'Expiring soon:': expiring_soon,
               'User Role:': user_role,
               'Total Alerts': 0,  # Placeholder for now
               }
    return render(request, 'dashboard.html', context)