from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from authentication.decorators import role_required

@login_required
def warden_dashboard(request):
    return redirect('dynamic_dashboard')
