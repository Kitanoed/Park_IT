# Park_IT/Park_IT/views.py
from django.shortcuts import render, redirect
from django.contrib import messages
from django.views import View
from .forms import RegisterForm, LoginForm
from utils import supabase
import time


class HomeView(View):
    def get(self, request):
        return render(request, 'home.html')


class SignInView(View):
    def get(self, request):
        return render(request, 'signIn.html')


class RegisterView(View):
    def get(self, request):
        form = RegisterForm()
        return render(request, 'register.html', {'form': form})

    def post(self, request):
        form = RegisterForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            if data['password1'] != data['password2']:
                messages.error(request, 'Passwords do not match.')
                return render(request, 'register.html', {'form': form})

            max_attempts = 3
            for attempt in range(max_attempts):
                response = supabase.auth.sign_up({"email": data['email'], "password": data['password1']})
                if response.user:
                    break
                elif "Too Many Requests" in str(response.error.message) or "after 56 seconds" in str(
                        response.error.message):
                    if attempt < max_attempts - 1:
                        time.sleep(60)
                        continue
                messages.error(request, response.error.message if response.error else 'Sign-up failed.')
                return render(request, 'register.html', {'form': form})

            if response.user:
                print(f"Sign-up successful, user ID: {response.user.id}")  # Debug
                role_response = supabase.table('roles').select('role_id').eq('role_name', data['role']).execute()
                if role_response.data:
                    role_id = role_response.data[0]['role_id']
                    status = 'active'  # Simplified status, no session check needed here
                    try:
                        insert_result = supabase.table('users').insert({
                            'id': response.user.id,
                            'first_name': data['first_name'],
                            'last_name': data['last_name'],
                            'email': data['email'],
                            'student_employee_id': data['student_id'],
                            'role_id': role_id,
                            'status': status
                        }).execute()
                        print(f"Insert result: {insert_result.data}")  # Debug
                        messages.success(request, 'Account created! Please check your email for confirmation.')
                        return redirect('signin', portal='student')
                    except Exception as e:
                        error_details = str(e) if hasattr(e, 'args') else str(e)
                        messages.error(request, f'Registration failed due to a database error: {error_details}')
                        print(f"Database error during insert: {error_details}")  # Enhanced debug
                else:
                    messages.error(request, 'Invalid role selected.')
            else:
                messages.error(request, response.error.message if response.error else 'Registration failed.')
        return render(request, 'register.html', {'form': form})


class LoginView(View):
    def get(self, request, portal='student'):  # Accept portal from URL kwargs
        form = LoginForm()
        template = f'signin_{portal}.html' if portal in ['admin', 'student'] else 'signin.html'
        return render(request, template, {'form': form})

    def post(self, request, portal='student'):
        form = LoginForm(request.POST)
        if form.is_valid():
            id_input = form.cleaned_data['id']
            password = form.cleaned_data['password']
            user_response = supabase.table('users').select('email, role_id').eq('student_employee_id',
                                                                                id_input).execute()
            if user_response.data:
                email = user_response.data[0]['email']
                role_id = user_response.data[0]['role_id']
                auth_response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                if auth_response.session:
                    request.session['access_token'] = auth_response.session.access_token
                    request.session['user_id'] = auth_response.user.id
                    role_response = supabase.table('roles').select('role_name').eq('role_id', role_id).execute()
                    role_name = role_response.data[0]['role_name'] if role_response.data else 'student'
                    messages.success(request, 'Login successful!')
                    return redirect('dashboard')  # Single dashboard for now
                else:
                    messages.error(request, 'Invalid credentials.')
            else:
                messages.error(request, 'ID not found.')
        template = f'signin_{portal}.html' if portal in ['admin', 'student'] else 'signin.html'
        return render(request, template, {'form': form})


def logout_view(request):
    supabase.auth.sign_out()
    request.session.flush()
    messages.success(request, 'Logged out successfully.')
    return redirect('home')


class DashboardView(View):
    def get(self, request):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return redirect('signin', portal='student')

        user_id = request.session.get('user_id')

        # Fetch user data from Supabase
        user_response = supabase.table('users').select('first_name, last_name, email, student_employee_id, role_id').eq(
            'id', user_id).execute()

        if user_response.data:
            user_data = user_response.data[0]
            role_id = user_data['role_id']

            # Get role name
            role_response = supabase.table('roles').select('role_name').eq('role_id', role_id).execute()
            role_name = role_response.data[0]['role_name'] if role_response.data else 'student'

            # Create context with user information
            context = {
                'role': role_name,
                'full_name': f"{user_data['first_name']} {user_data['last_name']}",
                'first_name': user_data['first_name'],
                'last_name': user_data['last_name'],
                'email': user_data['email'],
                'username': user_data['student_employee_id'],  # Using student/employee ID as username
            }
        else:
            # Fallback if user data not found
            context = {
                'role': 'student',
                'full_name': 'User',
                'email': 'No email',
                'username': 'No username'
            }

        return render(request, 'dashboard.html', context)


class ParkingSpacesView(View):
    def get(self, request):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return redirect('signin', portal='student')

        user_id = request.session.get('user_id')

        # Fetch user data from Supabase
        user_response = supabase.table('users').select('first_name, last_name, email, student_employee_id, role_id').eq(
            'id', user_id).execute()

        if user_response.data:
            user_data = user_response.data[0]
            role_id = user_data['role_id']

            # Get role name
            role_response = supabase.table('roles').select('role_name').eq('role_id', role_id).execute()
            role_name = role_response.data[0]['role_name'] if role_response.data else 'student'

            # Create context with user information
            context = {
                'role': role_name,
                'full_name': f"{user_data['first_name']} {user_data['last_name']}",
                'first_name': user_data['first_name'],
                'last_name': user_data['last_name'],
                'email': user_data['email'],
                'username': user_data['student_employee_id'],
            }
        else:
            context = {
                'role': 'student',
                'full_name': 'User',
                'email': 'No email',
                'username': 'No username'
            }

        return render(request, 'parking_spaces.html', context)
