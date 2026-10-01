# core/views.py
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test

from django.utils import timezone
from datetime import timedelta
from .models import Medicine, MedicineBatch, Alert

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
    # 1. Fetch real data from the database
    total_medicines = Medicine.objects.count()
    total_batches = MedicineBatch.objects.count()

    # 2. Calculate expiring soon (within 90 days)
    today = timezone.now().date()
    ninety_days_from_now = today + timedelta(days=90)

    expiring_soon = MedicineBatch.objects.filter(
        expiry_date__lte=ninety_days_from_now,
        expiry_date__gte=today,
        quantity_available__gt=0
    ).count()

    # 3. Get user role (safely)
    user_role = request.user.role.name if request.user.role else "No Role Assigned"

    # 4. Pass data to the template via context dictionary
    context = {
        'total_medicines': total_medicines,
        'total_batches': total_batches,
        'expiring_soon': expiring_soon,
        'user_role': user_role,
        'total_alerts': 0,  # Placeholder for now
    }
    return render(request, 'dashboard.html', context)