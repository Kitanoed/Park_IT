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
        if not form.is_valid():
            return render(request, 'register.html', {'form': form})

        data = form.cleaned_data

        # Validate password match
        if data['password1'] != data['password2']:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'register.html', {'form': form})

        # === Supabase Sign-Up with Retry Logic ===
        max_attempts = 3
        response = None
        for attempt in range(max_attempts):
            response = supabase.auth.sign_up({
                "email": data['email'],
                "password": data['password1']
            })

            if response.user:
                break
            elif response.error:
                error_msg = str(response.error.message)
                if "Too Many Requests" in error_msg or "after" in error_msg:
                    if attempt < max_attempts - 1:
                        time.sleep(60)
                        continue
                messages.error(request, response.error.message or 'Sign-up failed.')
                return render(request, 'register.html', {'form': form})

        # === If sign-up failed after retries ===
        if not response.user:
            messages.error(request, 'Sign-up failed. Please try again later.')
            return render(request, 'register.html', {'form': form})

        # === Insert into `users` table ===
        try:
            # Get role_id from roles table
            role_resp = supabase.table('roles')\
                .select('role_id')\
                .eq('role_name', data['role'])\
                .execute()

            if not role_resp.data:
                messages.error(request, 'Invalid role selected.')
                return render(request, 'register.html', {'form': form})

            role_id = role_resp.data[0]['role_id']

            # Insert user profile
            supabase.table('users').insert({
                'id': response.user.id,
                'first_name': data['first_name'],
                'last_name': data['last_name'],
                'email': data['email'],
                'student_employee_id': data['student_id'],
                'role_id': role_id,
                'status': 'active'
            }).execute()

            messages.success(
                request,
                'Account created successfully! Please check your email for confirmation.'
            )

            # === REDIRECT TO CORRECT PORTAL BASED ON ROLE ===
            redirect_portal = 'admin' if data['role'] == 'admin' else 'student'
            return redirect('signin', portal=redirect_portal)

        except Exception as e:
            # If DB insert fails, optionally delete the auth user (cleanup)
            try:
                supabase.auth.admin.delete_user(response.user.id)
            except:
                pass  # ignore cleanup errors
            messages.error(request, f'Registration failed: {str(e)}')
            return render(request, 'register.html', {'form': form})

class LoginView(View):
    def get(self, request, portal='student'):
        form = LoginForm()
        template = f'signin_{portal}.html' if portal in ['admin', 'student'] else 'signin.html'
        return render(request, template, {'form': form})

    def post(self, request, portal='student'):
        form = LoginForm(request.POST)
        if not form.is_valid():
            tmpl = f'signin_{portal}.html' if portal in ['admin', 'student'] else 'signin.html'
            return render(request, tmpl, {'form': form})

        id_input = form.cleaned_data['id']
        password = form.cleaned_data['password']

        user_resp = supabase.table('users')\
            .select('email, role_id')\
            .eq('student_employee_id', id_input)\
            .execute()

        if not user_resp.data:
            messages.error(request, 'ID not found.')
            tmpl = f'signin_{portal}.html' if portal in ['admin', 'student'] else 'signin.html'
            return render(request, tmpl, {'form': form})

        email   = user_resp.data[0]['email']
        role_id = user_resp.data[0]['role_id']


        auth_resp = supabase.auth.sign_in_with_password(
            {"email": email, "password": password}
        )

        if not auth_resp.session:
            messages.error(request, 'Invalid credentials.')
            tmpl = f'signin_{portal}.html' if portal in ['admin', 'student'] else 'signin.html'
            return render(request, tmpl, {'form': form})


        request.session['access_token'] = auth_resp.session.access_token
        request.session['user_id']      = auth_resp.user.id


        role_resp = supabase.table('roles')\
            .select('role_name')\
            .eq('role_id', role_id)\
            .execute()

        role_name = role_resp.data[0]['role_name'] if role_resp.data else 'student'


        if portal == 'student' and role_name == 'admin':
            # Admin was forced into the student form – give a nice message and redirect
            messages.success(request, 'Admin account detected – redirecting to Admin Portal.')
            return redirect('signin', portal='admin')

        if portal == 'admin' and role_name != 'admin':
            # Wrong portal – log out and push to the right one
            supabase.auth.sign_out()
            request.session.flush()
            messages.error(request, 'Please use the Academic Portal to log in.')
            return redirect('signin', portal='student')


        messages.success(request, 'Login successful!')
        return redirect('dashboard')

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
        user_response = supabase.table('users').select('first_name, last_name, email, student_employee_id, role_id').eq('id', user_id).execute()

        if not user_response.data:
            messages.error(request, 'User not found.')
            return redirect('home')

        user_data = user_response.data[0]
        role_response = supabase.table('roles').select('role_name').eq('role_id', user_data['role_id']).execute()
        role_name = role_response.data[0]['role_name'] if role_response.data else 'student'

        # Only allow admins to access this dashboard
        if role_name != 'admin':
            messages.error(request, 'Access denied. Admins only.')
            return redirect('home')

        context = {
            'role': role_name,
            'full_name': f"{user_data['first_name']} {user_data['last_name']}",
            'first_name': user_data['first_name'],
            'last_name': user_data['last_name'],
            'email': user_data['email'],
            'username': user_data['student_employee_id'],
        }
        return render(request, 'dashboard.html', context)

class ParkingSpacesView(View):
    def get(self, request):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return redirect('signin', portal='student')
        user_id = request.session.get('user_id')
        user_response = supabase.table('users').select('first_name, last_name, email, student_employee_id, role_id').eq('id', user_id).execute()
        if user_response.data:
            user_data = user_response.data[0]
            role_id = user_data['role_id']
            role_response = supabase.table('roles').select('role_name').eq('role_id', role_id).execute()
            role_name = role_response.data[0]['role_name'] if role_response.data else 'student'
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

class ManageUsersView(View):
    def get(self, request):
        # Example user list for template demonstration
        users = [
            {
                "full_name": "Jane Doe",
                "username": "jdoe",
                "role": "Admin",
                "status": "Active",
                "date_added": "09/17/2025",
            },
            {
                "full_name": "John Doe",
                "username": "jndoe",
                "role": "Attendant",
                "status": "Active",
                "date_added": "09/17/2025",
            },
            {
                "full_name": "Person 1",
                "username": "prsn1",
                "role": "Attendant",
                "status": "Inactive",
                "date_added": "09/17/2025",
            }
        ]
        return render(request, 'manage_users.html', {'users': users})
