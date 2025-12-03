from django.shortcuts import render, redirect
from django.contrib import messages
from django.views import View
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.urls import reverse
from django.http import JsonResponse
from .forms import RegisterForm, LoginForm, ChangePasswordForm, AdminPasswordResetForm
from utils import supabase
import time
from datetime import datetime, timedelta, timezone as dt_timezone
from collections import defaultdict

def fetch_parking_data():
    try:
        lots_resp = supabase.table('parking_lot').select('id, code, name, capacity').order('code').execute()
        lots = lots_resp.data or []
    except Exception:
        lots = []

    try:
        # Try to include extended columns; fall back to base columns if they don't exist yet
        try:
            slots_resp = supabase.table('parking_slot').select(
                'id, lot_id, slot_number, status, license_plate, check_in_time'
            ).execute()
        except Exception:
            slots_resp = supabase.table('parking_slot').select('id, lot_id, slot_number, status').execute()
        slots = slots_resp.data or []
        # Add default values for new columns if they don't exist in the response
        for slot in slots:
            if 'license_plate' not in slot:
                slot['license_plate'] = None
            if 'check_in_time' not in slot:
                slot['check_in_time'] = None
    except Exception:
        slots = []

    return lots, slots


def build_lot_display(lots, slots, selected_lot_id=None):
    slots_by_lot = defaultdict(list)
    for slot in slots:
        lot_id = slot.get('lot_id')
        if lot_id is None:
            continue
        # Ensure lot_id is stored as int for consistent lookup
        try:
            lot_id = int(lot_id)
        except (TypeError, ValueError):
            pass
        slots_by_lot[lot_id].append(slot)

    lot_options = []
    current_lot = None

    if selected_lot_id:
        try:
            selected_lot_id = int(selected_lot_id)
        except (TypeError, ValueError):
            selected_lot_id = None

    for lot in lots:
        lot_id = lot.get('id')
        # Ensure lot_id is int for consistent comparison
        try:
            lot_id = int(lot_id) if lot_id is not None else None
        except (TypeError, ValueError):
            pass
        entry = {
            'id': lot_id,
            'code': lot.get('code') or lot.get('name') or f'Lot {lot_id}',
            'name': lot.get('name') or lot.get('code') or 'Parking Lot',
            'capacity': lot.get('capacity') or len(slots_by_lot.get(lot_id, [])),
        }
        entry['is_active'] = (selected_lot_id == lot_id)
        lot_options.append(entry)
        if current_lot is None and (selected_lot_id is None or selected_lot_id == lot_id):
            current_lot = entry
            selected_lot_id = lot_id

    if current_lot is None and lot_options:
        current_lot = lot_options[0]
        selected_lot_id = current_lot['id']
        current_lot['is_active'] = True

    current_slots_raw = slots_by_lot.get(selected_lot_id, [])
    current_slots_raw.sort(key=lambda s: (s.get('slot_number') is None, s.get('slot_number')))

    counts = {'available': 0, 'occupied': 0, 'reserved': 0, 'unavailable': 0}
    slots_display = []
    status_map = ParkingSpacesView.STATUS_MAP

    for slot in current_slots_raw:
        status = (slot.get('status') or 'available').lower()
        if status not in counts:
            status = 'available'
        counts[status] += 1
        status_label, status_class = status_map.get(status, ('Available', 'status-available'))
        slots_display.append({
            'id': slot.get('id'),
            'slot_number': slot.get('slot_number'),
            'status': status,
            'status_label': status_label,
            'status_class': status_class,
            'license_plate': slot.get('license_plate'),
            'check_in_time': slot.get('check_in_time'),
        })

    total_slots = len(current_slots_raw)
    available_count = counts.get('available', 0)
    filled_count = total_slots - available_count

    return lot_options, current_lot, slots_display, filled_count, available_count, selected_lot_id


def summarize_lot_status(lots, slots):
    lot_map = {lot['id']: lot for lot in lots if lot.get('id') is not None}
    counts = defaultdict(lambda: {'occupied': 0, 'reserved': 0, 'available': 0, 'total': 0})
    overall_total = 0
    overall_occupied = 0

    def pct(part, total):
        try:
            return round((part / total) * 100) if total else 0
        except ZeroDivisionError:
            return 0

    for slot in slots:
        lot_id = slot.get('lot_id')
        if lot_id is None:
            continue
        status = (slot.get('status') or 'available').lower()
        counts[lot_id]['total'] += 1
        if status in ('occupied', 'taken', 'full', 'in_use', 'busy'):
            counts[lot_id]['occupied'] += 1
        elif status in ('reserved', 'hold', 'pending'):
            counts[lot_id]['reserved'] += 1
        else:
            counts[lot_id]['available'] += 1

    lot_status = []
    for lot_id, lot in lot_map.items():
        stats = counts.get(lot_id, {'occupied': 0, 'reserved': 0, 'available': 0, 'total': 0})
        total_slots = stats['total'] or lot.get('capacity') or 0
        occupied = stats['occupied']
        reserved = stats['reserved']

        if stats['total'] == 0 and total_slots:
            available = total_slots - occupied - reserved
            stats['available'] = max(available, 0)

        overall_total += total_slots
        overall_occupied += occupied

        occupancy_percent = pct(occupied, total_slots)
        red_pct = pct(occupied, total_slots)
        yellow_pct = pct(reserved, total_slots)
        green_pct = max(0, 100 - red_pct - yellow_pct)

        lot_status.append({
            'code': lot.get('code') or lot.get('name') or 'Lot',
            'name': lot.get('name') or lot.get('code') or 'Parking Lot',
            'occupancy_percent': occupancy_percent,
            'segment_red': red_pct,
            'segment_yellow': yellow_pct,
            'segment_green': green_pct,
        })

    lot_status.sort(key=lambda item: item['code'])
    overall_pct = pct(overall_occupied, overall_total)
    return lot_status, overall_pct

class HomeView(View):
    def get(self, request):
        return render(request, 'home.html')

class SignInView(View):
    """Legacy view - redirects to unified login"""
    def get(self, request):
        return redirect('login')

class UnifiedLoginView(View):
    """Unified login view for all users (replaces dual-portal system)"""
    def get(self, request):
        # If already logged in, redirect based on role
        if 'access_token' in request.session and 'user_id' in request.session:
            try:
                user_id = request.session.get('user_id')
                user_response = supabase.table('users').select('role').eq('id', user_id).execute()
                if user_response.data:
                    role = user_response.data[0].get('role', 'user')
                    if role == 'admin':
                        return redirect('dashboard')
                    else:
                        return redirect('user_dashboard')
            except:
                pass  # If error, show login form
        
        form = LoginForm()
        return render(request, 'login.html', {'form': form})

    def post(self, request):
        form = LoginForm(request.POST)
        if not form.is_valid():
            return render(request, 'login.html', {'form': form})

        id_input = form.cleaned_data['id']
        password = form.cleaned_data['password']

        try:
            # Look up user by student_employee_id
            user_resp = supabase.table('users')\
                .select('email, role')\
                .eq('student_employee_id', id_input)\
                .execute()
        except Exception as e:
            messages.error(request, f'Error connecting to database: {str(e)}')
            return render(request, 'login.html', {'form': form})

        if not user_resp.data:
            messages.error(request, 'ID not found.')
            return render(request, 'login.html', {'form': form})

        email = user_resp.data[0]['email']
        # Normalize role: convert to lowercase, handle NULL/empty, default to 'user'
        raw_role = user_resp.data[0].get('role') or 'user'
        user_role = str(raw_role).strip().lower() if raw_role else 'user'
        
        # Ensure role is either 'admin' or 'user'
        if user_role not in ['admin', 'user']:
            user_role = 'user'

        try:
            auth_resp = supabase.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
        except Exception as e:
            messages.error(request, f'Authentication error: {str(e)}')
            return render(request, 'login.html', {'form': form})

        if not auth_resp.session:
            error_msg = 'Invalid credentials.'
            if hasattr(auth_resp, 'error') and auth_resp.error:
                error_msg = auth_resp.error.message or error_msg
            messages.error(request, error_msg)
            return render(request, 'login.html', {'form': form})

        # Store session data
        request.session['access_token'] = auth_resp.session.access_token
        request.session['user_id'] = auth_resp.user.id
        request.session['role'] = user_role  # Store normalized role in session

        messages.success(request, 'Login successful!')
        
        # Role-based redirection (as per requirements)
        if user_role == 'admin':
            return redirect('dashboard')  # /admin/dashboard
        else:
            return redirect('user_dashboard')  # /users/attendant

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

        # === Supabase Sign-Up ===
        try:
            response = supabase.auth.sign_up({
                "email": data['email'],
                "password": data['password1']
            })
        except Exception as auth_error:
            error_msg = str(auth_error)
            messages.error(request, f'Sign-up failed: {error_msg}')
            return render(request, 'register.html', {'form': form})

        # === If sign-up failed ===
        if not response.user:
            messages.error(request, 'Sign-up failed. Please try again later.')
            return render(request, 'register.html', {'form': form})

        # === Insert into `users` table with default role "user" ===
        try:
            # All new registrations default to "user" role - no role selection allowed
            # Admin role can only be assigned by existing admins via server-side API
            
            # Insert user profile with role_id=1 (default "user" role)
            supabase.table('users').insert({
                'id': response.user.id,
                'first_name': data['first_name'],
                'last_name': data['last_name'],
                'email': data['email'],
                'student_employee_id': data['student_id'],
                'role': 'user',  # Default role - cannot be changed during registration
                'role_id': 1,  # Default role_id for "user" role
                'status': 'active'
            }).execute()

            messages.success(
                request,
                'Account created successfully!'
            )

            # Redirect to unified login page
            return redirect('login')

        except Exception as e:
            # If DB insert fails, optionally delete the auth user (cleanup)
            try:
                supabase.auth.admin.delete_user(response.user.id)
            except:
                pass  # ignore cleanup errors
            messages.error(request, f'Registration failed: {str(e)}')
            return render(request, 'register.html', {'form': form})

class LoginView(View):
    """Legacy portal-based login - redirects to unified login"""
    def get(self, request, portal='user'):
        return redirect('login')
    
    def post(self, request, portal='user'):
        return redirect('login')

def logout_view(request):
    supabase.auth.sign_out()
    request.session.flush()
    messages.success(request, 'Logged out successfully.')
    return redirect('home')

class DashboardView(View):
    def get(self, request):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return redirect('login')

        try:
            user_id = request.session.get('user_id')
            user_response = supabase.table('users').select('first_name, last_name, email, student_employee_id, role').eq('id', user_id).execute()

            if not user_response.data:
                messages.error(request, 'User not found.')
                return redirect('home')

            user_data = user_response.data[0]
            # Normalize role: convert to lowercase, handle NULL/empty, default to 'user'
            raw_role = user_data.get('role') or 'user'
            role_name = str(raw_role).strip().lower() if raw_role else 'user'
            if role_name not in ['admin', 'user']:
                role_name = 'user'
        except ValueError as e:
            # Supabase credentials not configured
            messages.error(request, 'Server configuration error. Please contact administrator.')
            return redirect('home')
        except Exception as e:
            # Other Supabase errors
            messages.error(request, f'Database error: {str(e)}')
            return redirect('home')

        # Only allow admins to access this dashboard
        if role_name != 'admin':
            messages.error(request, 'Access denied. Admins only.')
            return redirect('user_dashboard')

        now = timezone.now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        summary_date = now.strftime('%m/%d/%Y')

        def parse_timestamp(ts_value):
            if not ts_value:
                return '—'
            try:
                ts_clean = ts_value.replace('Z', '+00:00')
                dt_obj = datetime.fromisoformat(ts_clean)
                if dt_obj.tzinfo is None:
                    dt_obj = dt_obj.replace(tzinfo=dt_timezone.utc)
                local_dt = dt_obj.astimezone(timezone.get_current_timezone())
                return local_dt.strftime('%H:%M')
            except Exception:
                return ts_value[:5]

        lots, slots = fetch_parking_data()
        lot_status, overall_occupancy_pct = summarize_lot_status(lots, slots)
        lot_map = {lot['id']: lot for lot in lots if lot.get('id') is not None}

        # Entries and exits for the day
        try:
            entries_resp = (
                supabase.table('entries_exits')
                .select('id, time, vehicle_id, action, zone, lot_id')
                .gte('time', start_of_day.isoformat())
                .lt('time', end_of_day.isoformat())
                .order('time', desc=True)
                .limit(50)
                .execute()
            )
            entry_rows = entries_resp.data or []
        except Exception:
            entry_rows = []

        vehicle_ids = {row.get('vehicle_id') for row in entry_rows if row.get('vehicle_id')}
        vehicle_map = {}
        if vehicle_ids:
            try:
                vehicle_resp = (
                    supabase.table('vehicle')
                    .select('id, plate')
                    .in_('id', list(vehicle_ids))
                    .execute()
                )
                vehicle_map = {row['id']: row.get('plate') or '—' for row in (vehicle_resp.data or [])}
            except Exception:
                vehicle_map = {}

        total_entries = 0
        total_exits = 0
        recent_activity = []

        for row in entry_rows:
            action = (row.get('action') or '').lower()
            if action == 'entry' or action.startswith('enter'):
                total_entries += 1
            elif action == 'exit' or action.startswith('exit'):
                total_exits += 1

        for row in entry_rows[:6]:
            action_raw = (row.get('action') or '—').title()
            lot = lot_map.get(row.get('lot_id'))
            zone = row.get('zone') or (lot.get('code') if lot else '—')
            recent_activity.append({
                'time': parse_timestamp(row.get('time')),
                'plate': vehicle_map.get(row.get('vehicle_id'), '—'),
                'action': action_raw,
                'zone': zone,
            })

        # Weekly occupancy (average per day)
        weekly_start = start_of_day - timedelta(days=6)
        try:
            occ_resp = (
                supabase.table('daily_occupancy')
                .select('date, occupancy_percentage')
                .gte('date', weekly_start.date().isoformat())
                .order('date', ascending=True)
                .execute()
            )
            occ_rows = occ_resp.data or []
        except Exception:
            occ_rows = []

        daily_totals = defaultdict(lambda: {'sum': 0, 'count': 0})
        for row in occ_rows:
            date_val = row.get('date')
            if not date_val:
                continue
            day_key = date_val[:10]
            pct_val = row.get('occupancy_percentage') or 0
            daily_totals[day_key]['sum'] += pct_val
            daily_totals[day_key]['count'] += 1

        weekly_occupancy = []
        for day_key in sorted(daily_totals.keys()):
            data = daily_totals[day_key]
            avg = data['sum'] / data['count'] if data['count'] else 0
            try:
                label = datetime.strptime(day_key, '%Y-%m-%d').strftime('%b %d')
            except ValueError:
                label = day_key
            val = round(avg, 1)
            weekly_occupancy.append({
                'label': label,
                'value': val,
                'available': max(0, 100 - val),
            })

        if not weekly_occupancy:
            weekly_occupancy = [{
                'label': now.strftime('%b %d'),
                'value': overall_occupancy_pct,
                'available': max(0, 100 - overall_occupancy_pct),
            }]

        context = {
            'role': role_name,
            'full_name': f"{user_data['first_name']} {user_data['last_name']}",
            'first_name': user_data['first_name'],
            'last_name': user_data['last_name'],
            'email': user_data['email'],
            'username': user_data['student_employee_id'],
            'lot_status': lot_status,
            'summary_date': summary_date,
            'total_entries': total_entries,
            'total_exits': total_exits,
            'overall_occupancy_pct': overall_occupancy_pct,
            'recent_activity': recent_activity,
            'weekly_occupancy': weekly_occupancy,
        }
        return render(request, 'dashboard.html', context)

class UserDashboardView(View):
    def get(self, request):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return redirect('login')

        try:
            user_id = request.session.get('user_id')
            user_response = supabase.table('users').select(
                'first_name, last_name, email, student_employee_id, role'
            ).eq('id', user_id).execute()

            if not user_response.data:
                messages.error(request, 'User not found.')
                return redirect('home')

            user_data = user_response.data[0]
            # Normalize role: convert to lowercase, handle NULL/empty, default to 'user'
            raw_role = user_data.get('role') or 'user'
            role_name = str(raw_role).strip().lower() if raw_role else 'user'
            if role_name not in ['admin', 'user']:
                role_name = 'user'

            # Prevent admin from entering user dashboard
            if role_name == 'admin':
                return redirect('dashboard')

        except Exception as e:
            messages.error(request, f'Error loading dashboard: {str(e)}')
            return redirect('home')

        lots, slots = fetch_parking_data()
        lot_status, overall_occupancy_pct = summarize_lot_status(lots, slots)
        summary_date = timezone.now().strftime('%m/%d/%Y')
        recommended_lot = next((lot for lot in lot_status if lot['occupancy_percent'] < 85), lot_status[0] if lot_status else None)

        context = {
            'role': role_name,
            'full_name': f"{user_data['first_name']} {user_data['last_name']}",
            'first_name': user_data['first_name'],
            'last_name': user_data['last_name'],
            'email': user_data['email'],
            'username': user_data['student_employee_id'],
            'lot_status': lot_status,
            'summary_date': summary_date,
            'overall_occupancy_pct': overall_occupancy_pct,
            'recommended_lot': recommended_lot,
        }

        return render(request, 'user_dashboard.html', context)

class ParkingSpacesView(View):
    STATUS_MAP = {
        'available': ('Available', 'status-available'),
        'occupied': ('Occupied', 'status-occupied'),
        'reserved': ('Reserved', 'status-reserved'),
        'unavailable': ('Unavailable', 'status-unavailable'),
    }

    DEFAULT_LAYOUT = {
        'NGE': {
            'name': 'North Gate Extension',
            'capacity': 48,
            'slots': [
                {'slot_number': 1, 'left': 'available', 'right': 'available'},
                {'slot_number': 2, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 3, 'left': 'available', 'right': 'available'},
                {'slot_number': 4, 'left': 'available', 'right': 'available'},
                {'slot_number': 5, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 6, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 7, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 8, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 9, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 10, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 11, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 12, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 13, 'left': 'available', 'right': 'available'},
                {'slot_number': 14, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 15, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 16, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 17, 'left': 'available', 'right': 'available'},
                {'slot_number': 18, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 19, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 20, 'left': 'available', 'right': 'available'},
                {'slot_number': 21, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 22, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 23, 'left': 'available', 'right': 'available'},
                {'slot_number': 24, 'left': 'unavailable', 'right': 'available'},
            ],
        },
        'ACAD': {
            'name': 'Academic Lot',
            'capacity': 48,
            'slots': [
                {'slot_number': 1, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 2, 'left': 'available', 'right': 'available'},
                {'slot_number': 3, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 4, 'left': 'available', 'right': 'available'},
                {'slot_number': 5, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 6, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 7, 'left': 'available', 'right': 'available'},
                {'slot_number': 8, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 9, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 10, 'left': 'available', 'right': 'available'},
                {'slot_number': 11, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 12, 'left': 'available', 'right': 'available'},
                {'slot_number': 13, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 14, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 15, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 16, 'left': 'available', 'right': 'available'},
                {'slot_number': 17, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 18, 'left': 'available', 'right': 'available'},
                {'slot_number': 19, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 20, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 21, 'left': 'available', 'right': 'available'},
                {'slot_number': 22, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 23, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 24, 'left': 'available', 'right': 'available'},
            ],
        },
        'BC': {
            'name': 'BC Lot',
            'capacity': 48,
            'slots': [
                {'slot_number': 1, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 2, 'left': 'available', 'right': 'available'},
                {'slot_number': 3, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 4, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 5, 'left': 'available', 'right': 'available'},
                {'slot_number': 6, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 7, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 8, 'left': 'available', 'right': 'available'},
                {'slot_number': 9, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 10, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 11, 'left': 'available', 'right': 'available'},
                {'slot_number': 12, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 13, 'left': 'available', 'right': 'available'},
                {'slot_number': 14, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 15, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 16, 'left': 'available', 'right': 'available'},
                {'slot_number': 17, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 18, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 19, 'left': 'available', 'right': 'available'},
                {'slot_number': 20, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 21, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 22, 'left': 'available', 'right': 'available'},
                {'slot_number': 23, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 24, 'left': 'available', 'right': 'available'},
            ],
        },
        'GYM': {
            'name': 'Gym Lot',
            'capacity': 48,
            'slots': [
                {'slot_number': 1, 'left': 'available', 'right': 'available'},
                {'slot_number': 2, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 3, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 4, 'left': 'available', 'right': 'available'},
                {'slot_number': 5, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 6, 'left': 'available', 'right': 'available'},
                {'slot_number': 7, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 8, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 9, 'left': 'available', 'right': 'available'},
                {'slot_number': 10, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 11, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 12, 'left': 'available', 'right': 'available'},
                {'slot_number': 13, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 14, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 15, 'left': 'available', 'right': 'available'},
                {'slot_number': 16, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 17, 'left': 'available', 'right': 'available'},
                {'slot_number': 18, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 19, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 20, 'left': 'available', 'right': 'available'},
                {'slot_number': 21, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 22, 'left': 'available', 'right': 'available'},
                {'slot_number': 23, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 24, 'left': 'unavailable', 'right': 'available'},
            ],
        },
        'RTL': {
            'name': 'RTL Lot',
            'capacity': 48,
            'slots': [
                {'slot_number': 1, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 2, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 3, 'left': 'available', 'right': 'available'},
                {'slot_number': 4, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 5, 'left': 'available', 'right': 'available'},
                {'slot_number': 6, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 7, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 8, 'left': 'available', 'right': 'available'},
                {'slot_number': 9, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 10, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 11, 'left': 'available', 'right': 'available'},
                {'slot_number': 12, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 13, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 14, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 15, 'left': 'available', 'right': 'available'},
                {'slot_number': 16, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 17, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 18, 'left': 'available', 'right': 'available'},
                {'slot_number': 19, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 20, 'left': 'available', 'right': 'available'},
                {'slot_number': 21, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 22, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 23, 'left': 'available', 'right': 'available'},
                {'slot_number': 24, 'left': 'unavailable', 'right': 'unavailable'},
            ],
        },
        'BG': {
            'name': 'BG Lot',
            'capacity': 48,
            'slots': [
                {'slot_number': 1, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 2, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 3, 'left': 'available', 'right': 'available'},
                {'slot_number': 4, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 5, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 6, 'left': 'available', 'right': 'available'},
                {'slot_number': 7, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 8, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 9, 'left': 'available', 'right': 'available'},
                {'slot_number': 10, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 11, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 12, 'left': 'available', 'right': 'available'},
                {'slot_number': 13, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 14, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 15, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 16, 'left': 'available', 'right': 'available'},
                {'slot_number': 17, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 18, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 19, 'left': 'available', 'right': 'available'},
                {'slot_number': 20, 'left': 'unavailable', 'right': 'unavailable'},
                {'slot_number': 21, 'left': 'available', 'right': 'available'},
                {'slot_number': 22, 'left': 'available', 'right': 'unavailable'},
                {'slot_number': 23, 'left': 'unavailable', 'right': 'available'},
                {'slot_number': 24, 'left': 'available', 'right': 'available'},
            ],
        },
    }

    def _derive_seed_status(self, left_status, right_status):
        left = (left_status or 'available').lower()
        right = (right_status or 'available').lower()
        if left == 'available' and right == 'available':
            return 'available'
        if left == 'unavailable' and right == 'unavailable':
            return 'occupied'
        return 'reserved'

    def _seed_default_layout(self):
        layout = self.DEFAULT_LAYOUT
        try:
            lots_resp = supabase.table('parking_lot').select('id, code').execute()
            existing_lots = {lot['code']: lot for lot in (lots_resp.data or []) if lot.get('code')}
        except Exception:
            return False

        created_any = False

        for code, config in layout.items():
            lot_entry = existing_lots.get(code)
            if not lot_entry:
                try:
                    insert_resp = supabase.table('parking_lot').insert({
                        'code': code,
                        'name': config.get('name', code),
                        'capacity': config.get('capacity', len(config.get('slots', []))),
                    }).execute()
                except Exception:
                    continue
                if not insert_resp.data:
                    continue
                lot_entry = insert_resp.data[0]
                existing_lots[code] = lot_entry
                created_any = True

            lot_id = lot_entry.get('id')
            if lot_id is None:
                continue

            try:
                slots_resp = supabase.table('parking_slot').select('slot_number').eq('lot_id', lot_id).execute()
                existing_numbers = {
                    row['slot_number']
                    for row in (slots_resp.data or [])
                    if row.get('slot_number') is not None
                }
            except Exception:
                existing_numbers = set()

            new_slots = []
            for slot in config.get('slots', []):
                num = slot.get('slot_number')
                if num in existing_numbers:
                    continue
                status = self._derive_seed_status(slot.get('left'), slot.get('right'))
                new_slots.append({
                    'lot_id': lot_id,
                    'slot_number': num,
                    'status': status,
                })

            if new_slots:
                try:
                    supabase.table('parking_slot').insert(new_slots).execute()
                    created_any = True
                except Exception:
                    pass

        return created_any

    def get(self, request):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return redirect('login')

        try:
            user_id = request.session.get('user_id')
            user_response = supabase.table('users').select(
                'first_name, last_name, email, student_employee_id, role'
            ).eq('id', user_id).execute()

            if not user_response.data:
                messages.error(request, 'User not found.')
                return redirect('home')

            user_data = user_response.data[0]
            # Normalize role: convert to lowercase, handle NULL/empty, default to 'user'
            raw_role = user_data.get('role') or 'user'
            role_name = str(raw_role).strip().lower() if raw_role else 'user'
            if role_name not in ['admin', 'user']:
                role_name = 'user'
        except ValueError:
            messages.error(request, 'Server configuration error. Please contact administrator.')
            return redirect('home')
        except Exception as e:
            messages.error(request, f'Database error: {str(e)}')
            return redirect('home')

        # Only allow admins to manage parking slots
        if role_name != 'admin':
            messages.error(request, 'Access denied. Admins only.')
            return redirect('user_dashboard')

        lots, all_slots = fetch_parking_data()
        if not lots or not all_slots:
            if self._seed_default_layout():
                lots, all_slots = fetch_parking_data()

        lot_options, current_lot, slots_display, filled_count, available_count, selected_lot_id = build_lot_display(
            lots, all_slots, request.GET.get('lot')
        )

        context = {
            'role': role_name,
            'full_name': f"{user_data['first_name']} {user_data['last_name']}",
            'first_name': user_data['first_name'],
            'last_name': user_data['last_name'],
            'email': user_data['email'],
            'username': user_data['student_employee_id'],
            'lots': lot_options,
            'current_lot': current_lot,
            'slots': slots_display,
            'filled_count': filled_count,
            'available_count': available_count,
            'selected_lot_id': selected_lot_id,
        }
        return render(request, 'parking_spaces.html', context)


class UserParkingSpacesView(View):
    """Parking spaces view for regular users (non-admin)"""
    def get(self, request):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return redirect('login')

        try:
            user_id = request.session.get('user_id')
            user_response = supabase.table('users').select(
                'first_name, last_name, email, student_employee_id, role'
            ).eq('id', user_id).execute()

            if not user_response.data:
                messages.error(request, 'User not found.')
                return redirect('home')

            user_data = user_response.data[0]
            # Normalize role: convert to lowercase, handle NULL/empty, default to 'user'
            raw_role = user_data.get('role') or 'user'
            role_name = str(raw_role).strip().lower() if raw_role else 'user'
            if role_name not in ['admin', 'user']:
                role_name = 'user'
        except Exception as e:
            messages.error(request, f'Database error: {str(e)}')
            return redirect('home')

        if role_name == 'admin':
            return redirect('parking_spaces')

        lots, slots = fetch_parking_data()
        lot_options, current_lot, slots_display, filled_count, available_count, selected_lot_id = build_lot_display(
            lots, slots, request.GET.get('lot')
        )

        context = {
            'role': role_name,
            'full_name': f"{user_data['first_name']} {user_data['last_name']}",
            'first_name': user_data['first_name'],
            'last_name': user_data['last_name'],
            'email': user_data['email'],
            'username': user_data['student_employee_id'],
            'lots': lot_options,
            'current_lot': current_lot,
            'slots': slots_display,
            'filled_count': filled_count,
            'available_count': available_count,
            'selected_lot_id': selected_lot_id,
        }
        return render(request, 'stud_parking_spaces.html', context)

class ManageUsersView(View):
    def get(self, request):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return redirect('login')

        try:
            user_id = request.session.get('user_id')
            user_response = supabase.table('users').select('first_name, last_name, email, student_employee_id, role').eq('id', user_id).execute()

            if not user_response.data:
                messages.error(request, 'User not found.')
                return redirect('home')

            user_data = user_response.data[0]
            # Normalize role: convert to lowercase, handle NULL/empty, default to 'user'
            raw_role = user_data.get('role') or 'user'
            role_name = str(raw_role).strip().lower() if raw_role else 'user'
            if role_name not in ['admin', 'user']:
                role_name = 'user'
        except ValueError as e:
            # Supabase credentials not configured
            messages.error(request, 'Server configuration error. Please contact administrator.')
            return redirect('home')
        except Exception as e:
            # Other Supabase errors
            messages.error(request, f'Database error: {str(e)}')
            return redirect('home')

        # Only allow admins to access this page
        if role_name != 'admin':
            messages.error(request, 'Access denied. Admins only.')
            return redirect('user_dashboard')

        # Get search query parameter
        search_query = request.GET.get('q', '').strip()
        
        try:
            # Build query with optional search filter
            users_query = supabase.table('users').select(
                'id, first_name, last_name, student_employee_id, status, created_at, role, email'
            )
            
            # Apply search filter if provided
            if search_query:
                # Supabase doesn't support OR queries directly, so we'll filter in Python
                # But we can still order by created_at
                users_query = users_query.order('created_at', desc=True)
                users_response = users_query.execute()
                raw_users = users_response.data or []
                
                # Filter in Python for case-insensitive search across multiple fields
                search_lower = search_query.lower()
                filtered_users = []
                for user in raw_users:
                    first_name = (user.get('first_name') or '').lower()
                    last_name = (user.get('last_name') or '').lower()
                    username = (user.get('student_employee_id') or '').lower()
                    email = (user.get('email') or '').lower()
                    full_name = f"{first_name} {last_name}".strip()
                    
                    if (search_lower in first_name or 
                        search_lower in last_name or 
                        search_lower in username or 
                        search_lower in email or
                        search_lower in full_name):
                        filtered_users.append(user)
                
                raw_users = filtered_users
            else:
                users_query = users_query.order('created_at', desc=True)
                users_response = users_query.execute()
                raw_users = users_response.data or []
        except Exception as e:
            messages.error(request, f'Unable to load users: {str(e)}')
            raw_users = []

        def format_date(date_str):
            if not date_str:
                return '—'
            try:
                # Handle timestamps with or without timezone/Z suffix
                clean = date_str.rstrip('Z')
                dt = datetime.fromisoformat(clean)
                return dt.strftime('%m/%d/%Y')
            except ValueError:
                return date_str.split('T')[0] if 'T' in date_str else date_str

        users = []
        for item in raw_users:
            first = (item.get('first_name') or '').strip()
            last = (item.get('last_name') or '').strip()
            full_name = (f"{first} {last}").strip() or '—'
            role_label = (item.get('role') or 'user').title()
            status_label = (item.get('status') or 'unknown').title()
            date_added = format_date(item.get('created_at'))

            users.append({
                "id": item.get('id'),
                "full_name": full_name,
                "username": item.get('student_employee_id') or '—',
                "role": role_label,
                "status": status_label,
                "date_added": date_added,
            })

        context = {
            'users': users,
            'role': role_name,
            'full_name': f"{user_data['first_name']} {user_data['last_name']}",
            'first_name': user_data['first_name'],
            'last_name': user_data['last_name'],
            'email': user_data['email'],
            'username': user_data['student_employee_id'],
            'search_query': search_query,  # Pass search query to template
        }
        return render(request, 'manage_users.html', context)


class EditUserView(View):
    """Edit another user's full name, username, and role (admin only)."""

    def _require_admin(self, request):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return None, None, redirect('login')

        try:
            current_user_id = request.session.get('user_id')
            user_response = supabase.table('users').select(
                'first_name, last_name, email, student_employee_id, role'
            ).eq('id', current_user_id).execute()

            if not user_response.data:
                messages.error(request, 'User not found.')
                return None, None, redirect('home')

            current_user = user_response.data[0]
            role_name = current_user.get('role', 'user')
        except ValueError:
            messages.error(request, 'Server configuration error. Please contact administrator.')
            return None, None, redirect('home')
        except Exception as e:
            messages.error(request, f'Database error: {str(e)}')
            return None, None, redirect('home')

        if role_name != 'admin':
            messages.error(request, 'Access denied. Admins only.')
            return None, None, redirect('user_dashboard')

        return current_user, role_name, None

    def _load_target_user_and_roles(self, user_id):
        # Load target user
        user_resp = supabase.table('users').select(
            'id, first_name, last_name, student_employee_id, role, status'
        ).eq('id', user_id).execute()

        if not user_resp.data:
            return None, None

        target = user_resp.data[0]

        # Available roles (only "user" and "admin")
        roles = [
            {'role': 'user', 'role_name': 'User'},
            {'role': 'admin', 'role_name': 'Admin'}
        ]

        return target, roles

    def get(self, request, user_id):
        current_user, role_name, redirect_response = self._require_admin(request)
        if redirect_response:
            return redirect_response

        target_user, roles = self._load_target_user_and_roles(user_id)
        if not target_user:
            messages.error(request, 'Target user not found.')
            return redirect('manage_users')

        context = {
            'role': role_name,
            'full_name': f"{current_user['first_name']} {current_user['last_name']}",
            'first_name': current_user['first_name'],
            'last_name': current_user['last_name'],
            'email': current_user['email'],
            'username': current_user['student_employee_id'],
            'target_user': target_user,
            'roles': roles,
        }
        return render(request, 'edit_user.html', context)

    def post(self, request, user_id):
        current_user, role_name, redirect_response = self._require_admin(request)
        if redirect_response:
            return redirect_response

        target_user, roles = self._load_target_user_and_roles(user_id)
        if not target_user:
            messages.error(request, 'Target user not found.')
            return redirect('manage_users')

        first_name = (request.POST.get('first_name') or '').strip()
        last_name = (request.POST.get('last_name') or '').strip()
        username = (request.POST.get('username') or '').strip()
        role_raw = request.POST.get('role')

        if not first_name or not last_name or not username or not role_raw:
            messages.error(request, 'All fields are required.')
            context = {
                'role': role_name,
                'full_name': f"{current_user['first_name']} {current_user['last_name']}",
                'first_name': current_user['first_name'],
                'last_name': current_user['last_name'],
                'email': current_user['email'],
                'username': current_user['student_employee_id'],
                'target_user': target_user,
                'roles': roles,
            }
            return render(request, 'edit_user.html', context)

        # Normalize and validate role - only "user" or "admin" allowed
        normalized_role = str(role_raw).strip().lower() if role_raw else 'user'
        if normalized_role not in ['user', 'admin']:
            messages.error(request, 'Invalid role. Must be "user" or "admin".')
            context = {
                'role': role_name,
                'full_name': f"{current_user['first_name']} {current_user['last_name']}",
                'first_name': current_user['first_name'],
                'last_name': current_user['last_name'],
                'email': current_user['email'],
                'username': current_user['student_employee_id'],
                'target_user': target_user,
                'roles': roles,
            }
            return render(request, 'edit_user.html', context)

        try:
            supabase.table('users').update({
                'first_name': first_name,
                'last_name': last_name,
                'student_employee_id': username,
                'role': normalized_role,  # Always save as lowercase
            }).eq('id', user_id).execute()

            messages.success(request, 'User updated successfully.')
            return redirect('manage_users')
        except Exception as e:
            messages.error(request, f'Failed to update user: {str(e)}')
            context = {
                'role': role_name,
                'full_name': f"{current_user['first_name']} {current_user['last_name']}",
                'first_name': current_user['first_name'],
                'last_name': current_user['last_name'],
                'email': current_user['email'],
                'username': current_user['student_employee_id'],
                'target_user': target_user,
                'roles': roles,
            }
            return render(request, 'edit_user.html', context)


def _set_user_status(request, user_id, new_status, success_message):
    if 'access_token' not in request.session:
        messages.error(request, 'Please log in first.')
        return redirect('login')

    try:
        current_user_id = request.session.get('user_id')
        user_response = supabase.table('users').select(
            'role'
        ).eq('id', current_user_id).execute()

        if not user_response.data:
            messages.error(request, 'User not found.')
            return redirect('home')

        current_user = user_response.data[0]
        role_name = current_user.get('role', 'user')
    except Exception as e:
        messages.error(request, f'Database error: {str(e)}')
        return redirect('home')

    if role_name != 'admin':
        messages.error(request, 'Access denied. Admins only.')
        return redirect('user_dashboard')

    try:
        supabase.table('users').update({'status': new_status}).eq('id', user_id).execute()
        messages.success(request, success_message)
    except Exception as e:
        messages.error(request, f'Failed to update user status: {str(e)}')

    return redirect('manage_users')


@require_POST
def deactivate_user(request, user_id):
    return _set_user_status(request, user_id, 'inactive', 'User deactivated.')


@require_POST
def activate_user(request, user_id):
    return _set_user_status(request, user_id, 'active', 'User activated.')


class AddUserView(View):
    """Create a new user account (admin only)."""

    def _load_roles(self):
        # Available roles (only "user" and "admin")
        return [
            {'role': 'user', 'role_name': 'User'},
            {'role': 'admin', 'role_name': 'Admin'}
        ]

    def _render_form(self, request, template_user, role_name, roles, form_values=None):
        form_values = form_values or {}
        context = {
            'role': role_name,
            'full_name': f"{template_user['first_name']} {template_user['last_name']}",
            'first_name': template_user['first_name'],
            'last_name': template_user['last_name'],
            'email': template_user['email'],
            'username': template_user['student_employee_id'],
            'roles': roles,
            'form_first_name': form_values.get('first_name', ''),
            'form_last_name': form_values.get('last_name', ''),
            'form_username': form_values.get('username', ''),
            'form_email': form_values.get('email', ''),
            'form_role': form_values.get('role', ''),
        }
        return render(request, 'add_user.html', context)

    def _require_admin(self, request):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return None, None, redirect('login')

        try:
            current_user_id = request.session.get('user_id')
            user_response = supabase.table('users').select(
                'first_name, last_name, email, student_employee_id, role'
            ).eq('id', current_user_id).execute()

            if not user_response.data:
                messages.error(request, 'User not found.')
                return None, None, redirect('home')

            current_user = user_response.data[0]
            role_name = current_user.get('role', 'user')
        except ValueError:
            messages.error(request, 'Server configuration error. Please contact administrator.')
            return None, None, redirect('home')
        except Exception as e:
            messages.error(request, f'Database error: {str(e)}')
            return None, None, redirect('home')

        if role_name != 'admin':
            messages.error(request, 'Access denied. Admins only.')
            return None, None, redirect('user_dashboard')

        return current_user, role_name, None

    def get(self, request):
        current_user, role_name, redirect_response = self._require_admin(request)
        if redirect_response:
            return redirect_response

        roles = self._load_roles()
        return self._render_form(request, current_user, role_name, roles)

    def post(self, request):
        current_user, role_name, redirect_response = self._require_admin(request)
        if redirect_response:
            return redirect_response

        roles = self._load_roles()

        first_name = (request.POST.get('first_name') or '').strip()
        last_name = (request.POST.get('last_name') or '').strip()
        username = (request.POST.get('username') or '').strip()
        email = (request.POST.get('email') or '').strip()
        role_raw = request.POST.get('role')
        form_values = {
            'first_name': first_name,
            'last_name': last_name,
            'username': username,
            'email': email,
            'role': role_raw or '',
        }

        if not first_name or not last_name or not username or not email or not role_raw:
            messages.error(request, 'All fields are required.')
            return self._render_form(request, current_user, role_name, roles, form_values)

        # Normalize and validate role - only "user" or "admin" allowed
        normalized_role = str(role_raw).strip().lower() if role_raw else 'user'
        if normalized_role not in ['user', 'admin']:
            messages.error(request, 'Invalid role. Must be "user" or "admin".')
            return self._render_form(request, current_user, role_name, roles, form_values)

        try:
            auth_user = None
            admin_error = None

            # Try service-role creation first
            try:
                auth_resp = supabase.auth.admin.create_user({
                    "email": email,
                    "password": username,
                    "email_confirm": True,
                })
                auth_user = getattr(auth_resp, "user", None)
            except AttributeError as e:
                admin_error = str(e)
            except Exception as e:
                admin_error = str(e)

            # Fallback to standard sign-up if admin API unavailable
            if not auth_user:
                try:
                    signup_resp = supabase.auth.sign_up({
                        "email": email,
                        "password": username,
                        "options": {"email_confirm": True},
                    })
                    auth_user = getattr(signup_resp, "user", None)
                except Exception as signup_err:
                    detail = admin_error or str(signup_err)
                    messages.error(request, f'Failed to create auth user: {detail}')
                    return self._render_form(request, current_user, role_name, roles, form_values)

            if not auth_user:
                detail = admin_error or 'Unknown error from Supabase.'
                messages.error(request, f'Failed to create auth user: {detail}')
                return self._render_form(request, current_user, role_name, roles, form_values)

            # Insert into users profile table with role field (always lowercase)
            # Map role to role_id: 'user' = 1, 'admin' = 2
            role_id_map = {'user': 1, 'admin': 2}
            supabase.table('users').insert({
                'id': auth_user.id,
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'student_employee_id': username,
                'role': normalized_role,  # Always save as lowercase
                'role_id': role_id_map.get(normalized_role, 1),  # Default to user (1) if unknown
                'status': 'active',
            }).execute()

            messages.success(
                request,
                'New user created successfully. Temporary password set to their username.',
            )
            return redirect('manage_users')
        except Exception as e:
            messages.error(request, f'Failed to create user: {str(e)}')
            return self._render_form(request, current_user, role_name, roles, form_values)


from django.http import JsonResponse
import json

def update_user_role(request, user_id):
    """
    Admin-only API endpoint to update a user's role.
    Only authenticated users with role="admin" can access this endpoint.
    Supports both POST (form data) and PUT/PATCH (JSON) requests.
    """
    if request.method not in ['POST', 'PUT', 'PATCH']:
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    if 'access_token' not in request.session:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    try:
        # Verify current user is admin
        current_user_id = request.session.get('user_id')
        current_user_response = supabase.table('users').select('role').eq('id', current_user_id).execute()
        
        if not current_user_response.data:
            return JsonResponse({'error': 'User not found'}, status=404)
        
        # Normalize current user's role for comparison
        raw_current_role = current_user_response.data[0].get('role', 'user')
        current_role = str(raw_current_role).strip().lower() if raw_current_role else 'user'
        if current_role != 'admin':
            return JsonResponse({'error': 'Admin privileges required'}, status=403)
        
        # Get new role from request
        if request.content_type and 'application/json' in request.content_type:
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                return JsonResponse({'error': 'Invalid JSON'}, status=400)
        else:
            data = request.POST
        
        # Normalize new role to lowercase
        new_role = data.get('role', '').strip().lower()
        
        # Validate role
        if new_role not in ['user', 'admin']:
            return JsonResponse({'error': 'Invalid role. Must be "user" or "admin"'}, status=400)
        
        # Update user role
        supabase.table('users').update({'role': new_role}).eq('id', user_id).execute()
        
        return JsonResponse({'success': True, 'message': f'User role updated to {new_role}'})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_POST
def update_parking_slot_status(request, slot_id):
    if 'access_token' not in request.session:
        messages.error(request, 'Please log in first.')
        return redirect('login')

    try:
        current_user_id = request.session.get('user_id')
        user_response = supabase.table('users').select('role').eq('id', current_user_id).execute()
        if not user_response.data:
            messages.error(request, 'User not found.')
            return redirect('home')

        role_name = user_response.data[0].get('role', 'user')
    except Exception as e:
        messages.error(request, f'Database error: {str(e)}')
        return redirect('home')

    if role_name != 'admin':
        messages.error(request, 'Access denied. Admins only.')
        return redirect('user_dashboard')

    redirect_lot = request.POST.get('lot_id')
    status = (request.POST.get('status') or '').lower()
    allowed_statuses = {'available', 'occupied', 'reserved', 'unavailable'}
    if status not in allowed_statuses:
        messages.error(request, 'Invalid status.')
    else:
        try:
            supabase.table('parking_slot').update({'status': status}).eq('id', slot_id).execute()
            messages.success(request, 'Parking slot updated.')
        except Exception as e:
            messages.error(request, f'Failed to update slot: {str(e)}')

    redirect_url = reverse('parking_spaces')
    if redirect_lot:
        redirect_url = f"{redirect_url}?lot={redirect_lot}"
    return redirect(redirect_url)


class AdminParkingHistoryView(View):
    """Admin view for parking history with search, filter, and pagination"""
    def get(self, request):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return redirect('login')

        try:
            user_id = request.session.get('user_id')
            user_response = supabase.table('users').select('first_name, last_name, email, student_employee_id, role').eq('id', user_id).execute()

            if not user_response.data:
                messages.error(request, 'User not found.')
                return redirect('home')

            user_data = user_response.data[0]
            # Normalize role: convert to lowercase, handle NULL/empty, default to 'user'
            raw_role = user_data.get('role') or 'user'
            role_name = str(raw_role).strip().lower() if raw_role else 'user'
            if role_name not in ['admin', 'user']:
                role_name = 'user'
        except ValueError:
            messages.error(request, 'Server configuration error. Please contact administrator.')
            return redirect('home')
        except Exception as e:
            messages.error(request, f'Database error: {str(e)}')
            return redirect('home')

        # Only allow admins to access this page
        if role_name != 'admin':
            messages.error(request, 'Access denied. Admins only.')
            return redirect('user_dashboard')

        # Fetch parking lots for the filter dropdown
        try:
            lots_resp = supabase.table('parking_lot').select('name').order('name').execute()
            parking_lots = [lot.get('name') for lot in (lots_resp.data or []) if lot.get('name')]
        except Exception:
            parking_lots = []

        context = {
            'role': role_name,
            'full_name': f"{user_data['first_name']} {user_data['last_name']}",
            'first_name': user_data['first_name'],
            'last_name': user_data['last_name'],
            'email': user_data['email'],
            'username': user_data['student_employee_id'],
            'parking_lots': parking_lots,
        }
        return render(request, 'admin_parking_history.html', context)


def calculate_duration(entry_time, exit_time):
    """Calculate duration in 'Xh Ym' format"""
    if not exit_time:
        return '0h 0m'
    
    try:
        entry = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
        exit_dt = datetime.fromisoformat(exit_time.replace('Z', '+00:00'))
        
        if entry.tzinfo is None:
            entry = entry.replace(tzinfo=dt_timezone.utc)
        if exit_dt.tzinfo is None:
            exit_dt = exit_dt.replace(tzinfo=dt_timezone.utc)
        
        delta = exit_dt - entry
        total_seconds = int(delta.total_seconds())
        
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        
        return f'{hours}h {minutes}m'
    except Exception:
        return '0h 0m'


def parking_history_api(request):
    """
    API Endpoint: GET /api/admin/parking/history/
    
    Returns paginated parking session data with filtering capabilities.
    Admin-only endpoint.
    
    Query Parameters:
    - search_plate (string): Filter by vehicle plate (partial match)
    - date_from (date YYYY-MM-DD): Filter sessions with entry_time >= date_from
    - date_to (date YYYY-MM-DD): Filter sessions with entry_time <= date_to
    - lot_name (string): Filter by exact parking lot name
    - status (string): Filter by 'Active' or 'Completed'
    - page (int): Page number (default: 1)
    - page_size (int): Items per page (default: 10, max: 100)
    """
    # Authentication check
    if 'access_token' not in request.session:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        # Verify user is admin
        user_id = request.session.get('user_id')
        user_response = supabase.table('users').select('role').eq('id', user_id).execute()
        
        if not user_response.data:
            return JsonResponse({'error': 'User not found'}, status=404)
        
        raw_role = user_response.data[0].get('role') or 'user'
        role_name = str(raw_role).strip().lower() if raw_role else 'user'
        if role_name not in ['admin', 'user']:
            role_name = 'user'
        
        if role_name != 'admin':
            return JsonResponse({'error': 'Admin privileges required'}, status=403)
    except Exception as e:
        return JsonResponse({'error': f'Authentication error: {str(e)}'}, status=500)
    
    # Get query parameters
    search_plate = request.GET.get('search_plate', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    lot_name = request.GET.get('lot_name', '').strip()
    status_filter = request.GET.get('status', '').strip()
    page = int(request.GET.get('page', 1))
    page_size = min(int(request.GET.get('page_size', 10)), 100)
    
    try:
        # Build base query for entries
        entries_query = supabase.table('entries_exits').select(
            'id, time, vehicle_id, action, lot_id'
        ).eq('action', 'entry').order('time', desc=True)
        
        # Apply date filters
        if date_from:
            entries_query = entries_query.gte('time', f'{date_from}T00:00:00')
        if date_to:
            entries_query = entries_query.lte('time', f'{date_to}T23:59:59')
        
        # Get all entry records
        entries_response = entries_query.execute()
        entry_records = entries_response.data or []
        
        if not entry_records:
            return JsonResponse({
                'results': [],
                'count': 0,
                'page': page,
                'page_size': page_size,
                'total_pages': 0
            })
        
        # Get vehicle IDs and lot IDs for filtering
        vehicle_ids = [e['vehicle_id'] for e in entry_records if e.get('vehicle_id')]
        lot_ids = [e['lot_id'] for e in entry_records if e.get('lot_id')]
        
        # Fetch vehicles with plate filter
        vehicles_query = supabase.table('vehicle').select('id, plate')
        if vehicle_ids:
            vehicles_query = vehicles_query.in_('id', vehicle_ids)
        if search_plate:
            # Use ILIKE for case-insensitive partial match
            vehicles_query = vehicles_query.ilike('plate', f'%{search_plate}%')
        
        vehicles_response = vehicles_query.execute()
        vehicles_map = {v['id']: v.get('plate', '') for v in (vehicles_response.data or [])}
        
        # Filter by lot name if provided
        lots_query = supabase.table('parking_lot').select('id, name')
        if lot_ids:
            lots_query = lots_query.in_('id', lot_ids)
        if lot_name:
            lots_query = lots_query.eq('name', lot_name)
        
        lots_response = lots_query.execute()
        lots_map = {l['id']: l.get('name', '') for l in (lots_response.data or [])}
        valid_lot_ids = set(lots_map.keys())
        
        # Build sessions by matching entries with exits
        sessions = []
        
        for entry in entry_records:
            vehicle_id = entry.get('vehicle_id')
            lot_id = entry.get('lot_id')
            entry_time = entry.get('time')
            
            # Skip if vehicle or lot doesn't match filters
            if vehicle_id not in vehicles_map:
                continue
            if lot_id not in valid_lot_ids:
                continue
            
            plate_number = vehicles_map[vehicle_id]
            lot_name_value = lots_map.get(lot_id, '')
            
            # Find corresponding exit record
            exit_time = None
            try:
                exit_query = supabase.table('entries_exits').select('time').eq(
                    'vehicle_id', vehicle_id
                ).eq('action', 'exit').gte('time', entry_time).order('time', desc=True).limit(1)
                
                exit_response = exit_query.execute()
                if exit_response.data:
                    exit_time = exit_response.data[0].get('time')
            except Exception:
                pass
            
            # Determine status - "Incomplete" for sessions without exit, "Completed" for sessions with exit
            session_status = 'Incomplete' if exit_time is None else 'Completed'
            
            # Apply status filter (handle both old "Active" and new "Incomplete" for backward compatibility)
            if status_filter:
                if status_filter == 'Active':
                    # Map old "Active" filter to "Incomplete"
                    if session_status != 'Incomplete':
                        continue
                elif session_status != status_filter:
                    continue
            
            # Calculate duration
            duration = calculate_duration(entry_time, exit_time)
            
            sessions.append({
                'session_id': entry.get('id'),
                'plate_number': plate_number,
                'lot_name': lot_name_value,
                'entry_time': entry_time,
                'exit_time': exit_time,
                'duration': duration,
                'status': session_status
            })
        
        # Sort sessions by entry_time (most recent first)
        sessions.sort(key=lambda x: x['entry_time'] or '', reverse=True)
        
        # Pagination
        total_count = len(sessions)
        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 0
        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        paginated_sessions = sessions[start_index:end_index]
        
        return JsonResponse({
            'results': paginated_sessions,
            'count': total_count,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages
        })
        
    except Exception as e:
        return JsonResponse({'error': f'Database error: {str(e)}'}, status=500)


class ProfileForUsersView(View):
    """User profile view for regular users (non-admin)"""
    def get(self, request):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return redirect('login')

        try:
            user_id = request.session.get('user_id')
            user_response = supabase.table('users').select(
                'first_name, last_name, email, student_employee_id, role'
            ).eq('id', user_id).execute()

            if not user_response.data:
                messages.error(request, 'User not found.')
                return redirect('home')

            user_data = user_response.data[0]
            # Normalize role: convert to lowercase, handle NULL/empty, default to 'user'
            raw_role = user_data.get('role') or 'user'
            role_name = str(raw_role).strip().lower() if raw_role else 'user'
            if role_name not in ['admin', 'user']:
                role_name = 'user'

            # Prevent admin from entering user profile
            if role_name == 'admin':
                return redirect('dashboard')

        except Exception as e:
            messages.error(request, f'Error loading profile: {str(e)}')
            return redirect('home')

        context = {
            'role': role_name,
            'full_name': f"{user_data['first_name']} {user_data['last_name']}",
            'first_name': user_data['first_name'],
            'last_name': user_data['last_name'],
            'email': user_data['email'],
            'username': user_data['student_employee_id'],
        }
        return render(request, 'profile_for_users.html', context)

    def post(self, request):
        # Handle profile update only (password change moved to separate view)
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return redirect('login')

        try:
            user_id = request.session.get('user_id')
            full_name = request.POST.get('full_name', '').strip()
            
            if full_name:
                parts = full_name.split(' ', 1)
                first_name = parts[0] if parts else ''
                last_name = parts[1] if len(parts) > 1 else ''
                
                supabase.table('users').update({
                    'first_name': first_name,
                    'last_name': last_name,
                }).eq('id', user_id).execute()
                
                messages.success(request, 'Profile updated successfully.')
            
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
        
        return redirect('profile_for_users')


class ChangePasswordView(View):
    """View for users to change their own password"""
    def get(self, request):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return redirect('login')

        try:
            user_id = request.session.get('user_id')
            user_response = supabase.table('users').select(
                'first_name, last_name, email, student_employee_id, role'
            ).eq('id', user_id).execute()

            if not user_response.data:
                messages.error(request, 'User not found.')
                return redirect('home')

            user_data = user_response.data[0]
            raw_role = user_data.get('role') or 'user'
            role_name = str(raw_role).strip().lower() if raw_role else 'user'
            if role_name not in ['admin', 'user']:
                role_name = 'user'

        except Exception as e:
            messages.error(request, f'Error loading profile: {str(e)}')
            return redirect('home')

        form = ChangePasswordForm()
        context = {
            'form': form,
            'role': role_name,
            'full_name': f"{user_data['first_name']} {user_data['last_name']}",
            'first_name': user_data['first_name'],
            'last_name': user_data['last_name'],
            'email': user_data['email'],
            'username': user_data['student_employee_id'],
        }
        return render(request, 'change_password.html', context)

    def post(self, request):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return redirect('login')

        form = ChangePasswordForm(request.POST)
        
        try:
            user_id = request.session.get('user_id')
            user_response = supabase.table('users').select(
                'first_name, last_name, email, student_employee_id, role'
            ).eq('id', user_id).execute()

            if not user_response.data:
                messages.error(request, 'User not found.')
                return redirect('home')

            user_data = user_response.data[0]
            raw_role = user_data.get('role') or 'user'
            role_name = str(raw_role).strip().lower() if raw_role else 'user'
            if role_name not in ['admin', 'user']:
                role_name = 'user'

            if form.is_valid():
                current_password = form.cleaned_data['current_password']
                new_password = form.cleaned_data['new_password']
                email = user_data['email']
                
                # Verify current password and update using Supabase
                try:
                    from utils.supabase_client import get_client
                    from supabase import create_client
                    import os
                    
                    # Get Supabase URL and anon key for user operations
                    supabase_url = os.environ.get("SUPABASE_URL")
                    supabase_anon_key = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_KEY")
                    
                    if not supabase_url or not supabase_anon_key:
                        messages.error(request, 'Server configuration error. Please contact administrator.')
                        return redirect('profile_for_users')
                    
                    # Create a client for password verification
                    temp_client = create_client(supabase_url, supabase_anon_key)
                    
                    # Verify current password by signing in
                    auth_resp = temp_client.auth.sign_in_with_password({
                        "email": email, 
                        "password": current_password
                    })
                    
                    if not auth_resp.session:
                        messages.error(request, 'Current password is incorrect.')
                        context = {
                            'form': form,
                            'role': role_name,
                            'full_name': f"{user_data['first_name']} {user_data['last_name']}",
                            'first_name': user_data['first_name'],
                            'last_name': user_data['last_name'],
                            'email': user_data['email'],
                            'username': user_data['student_employee_id'],
                        }
                        return render(request, 'change_password.html', context)
                    
                    # Set the session on the client
                    temp_client.auth.set_session(
                        access_token=auth_resp.session.access_token,
                        refresh_token=auth_resp.session.refresh_token
                    )
                    
                    # Update password using the authenticated session
                    update_resp = temp_client.auth.update_user({
                        "password": new_password
                    })
                    
                    if update_resp.user:
                        messages.success(request, 'Password updated successfully. Please log in again with your new password.')
                        # Clear session and redirect to login
                        request.session.flush()
                        return redirect('login')
                    else:
                        messages.error(request, 'Failed to update password. Please try again.')
                        
                except Exception as e:
                    error_msg = str(e)
                    if 'Invalid login credentials' in error_msg or 'Email not confirmed' in error_msg or 'Invalid' in error_msg:
                        messages.error(request, 'Current password is incorrect.')
                    else:
                        messages.error(request, f'Failed to update password: {error_msg}')
                    
                    context = {
                        'form': form,
                        'role': role_name,
                        'full_name': f"{user_data['first_name']} {user_data['last_name']}",
                        'first_name': user_data['first_name'],
                        'last_name': user_data['last_name'],
                        'email': user_data['email'],
                        'username': user_data['student_employee_id'],
                    }
                    return render(request, 'change_password.html', context)
            else:
                # Form has errors, re-render with errors
                context = {
                    'form': form,
                    'role': role_name,
                    'full_name': f"{user_data['first_name']} {user_data['last_name']}",
                    'first_name': user_data['first_name'],
                    'last_name': user_data['last_name'],
                    'email': user_data['email'],
                    'username': user_data['student_employee_id'],
                }
                return render(request, 'change_password.html', context)
                
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
            return redirect('profile_for_users')


class AdminResetPasswordView(View):
    """Admin view to reset any user's password"""
    def get(self, request, user_id):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return redirect('login')

        try:
            # Verify current user is admin
            current_user_id = request.session.get('user_id')
            current_user_response = supabase.table('users').select('first_name, last_name, email, student_employee_id, role').eq('id', current_user_id).execute()
            
            if not current_user_response.data:
                messages.error(request, 'User not found.')
                return redirect('manage_users')
            
            current_user = current_user_response.data[0]
            raw_current_role = current_user.get('role', 'user')
            current_role = str(raw_current_role).strip().lower() if raw_current_role else 'user'
            if current_role != 'admin':
                messages.error(request, 'Access denied. Admins only.')
                return redirect('user_dashboard')
            
            # Get target user
            target_user_response = supabase.table('users').select(
                'id, first_name, last_name, student_employee_id, email'
            ).eq('id', user_id).execute()
            
            if not target_user_response.data:
                messages.error(request, 'Target user not found.')
                return redirect('manage_users')
            
            target_user = target_user_response.data[0]
            form = AdminPasswordResetForm()
            
            context = {
                'form': form,
                'target_user': target_user,
                'role': current_role,
                'full_name': f"{current_user['first_name']} {current_user['last_name']}",
                'first_name': current_user['first_name'],
                'last_name': current_user['last_name'],
                'email': current_user['email'],
                'username': current_user['student_employee_id'],
            }
            return render(request, 'admin_reset_password.html', context)
            
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
            return redirect('manage_users')

    def post(self, request, user_id):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return redirect('login')

        try:
            # Verify current user is admin
            current_user_id = request.session.get('user_id')
            current_user_response = supabase.table('users').select('first_name, last_name, email, student_employee_id, role').eq('id', current_user_id).execute()
            
            if not current_user_response.data:
                messages.error(request, 'User not found.')
                return redirect('manage_users')
            
            current_user = current_user_response.data[0]
            raw_current_role = current_user.get('role', 'user')
            current_role = str(raw_current_role).strip().lower() if raw_current_role else 'user'
            if current_role != 'admin':
                messages.error(request, 'Access denied. Admins only.')
                return redirect('user_dashboard')
            
            # Get target user
            target_user_response = supabase.table('users').select(
                'id, first_name, last_name, student_employee_id, email'
            ).eq('id', user_id).execute()
            
            if not target_user_response.data:
                messages.error(request, 'Target user not found.')
                return redirect('manage_users')
            
            target_user = target_user_response.data[0]
            form = AdminPasswordResetForm(request.POST)
            
            if form.is_valid():
                new_password = form.cleaned_data['new_password']
                
                # Update password using Supabase admin API
                # This requires service role key to work
                try:
                    from supabase import create_client
                    import os
                    
                    # Get Supabase URL and SERVICE ROLE KEY (required for admin operations)
                    supabase_url = os.environ.get("SUPABASE_URL")
                    supabase_service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
                    
                    if not supabase_url:
                        messages.error(request, 'Server configuration error: SUPABASE_URL not set.')
                        context = {
                            'form': form,
                            'target_user': target_user,
                            'role': current_role,
                            'full_name': f"{current_user['first_name']} {current_user['last_name']}",
                            'first_name': current_user['first_name'],
                            'last_name': current_user['last_name'],
                            'email': current_user['email'],
                            'username': current_user['student_employee_id'],
                        }
                        return render(request, 'admin_reset_password.html', context)
                    
                    if not supabase_service_key:
                        messages.error(request, 'Admin password reset requires SUPABASE_SERVICE_ROLE_KEY to be set in environment variables. Anon key cannot perform admin operations.')
                        context = {
                            'form': form,
                            'target_user': target_user,
                            'role': current_role,
                            'full_name': f"{current_user['first_name']} {current_user['last_name']}",
                            'first_name': current_user['first_name'],
                            'last_name': current_user['last_name'],
                            'email': current_user['email'],
                            'username': current_user['student_employee_id'],
                        }
                        return render(request, 'admin_reset_password.html', context)
                    
                    # Create admin client with service role key
                    admin_client = create_client(supabase_url, supabase_service_key)
                    
                    # Use admin API to update user password
                    try:
                        update_resp = admin_client.auth.admin.update_user_by_id(
                            user_id,
                            {"password": new_password}
                        )
                        
                        if update_resp.user:
                            messages.success(request, f'Password reset successfully for {target_user.get("first_name", "")} {target_user.get("last_name", "")}.')
                            return redirect('manage_users')
                        else:
                            messages.error(request, 'Password reset failed. User not found or update failed.')
                    except AttributeError as attr_err:
                        # Admin API not available
                        messages.error(request, f'Admin API not available: {str(attr_err)}. Please check your Supabase Python client version.')
                    except Exception as admin_error:
                        error_msg = str(admin_error)
                        if 'User not allowed' in error_msg or 'permission' in error_msg.lower() or 'not authorized' in error_msg.lower():
                            messages.error(request, 'Permission denied. The service role key may be incorrect or the user may not exist in Supabase Auth.')
                        else:
                            messages.error(request, f'Failed to reset password: {error_msg}')
                            
                except Exception as e:
                    error_msg = str(e)
                    messages.error(request, f'Error resetting password: {error_msg}')
            
            # Form has errors, re-render
            context = {
                'form': form,
                'target_user': target_user,
                'role': current_role,
                'full_name': f"{current_user['first_name']} {current_user['last_name']}",
                'first_name': current_user['first_name'],
                'last_name': current_user['last_name'],
                'email': current_user['email'],
                'username': current_user['student_employee_id'],
            }
            return render(request, 'admin_reset_password.html', context)
            
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
            return redirect('manage_users')


@require_POST
def reset_user_password(request):
    """Legacy admin-only endpoint to reset a user's password (kept for backward compatibility)"""
    if 'access_token' not in request.session:
        messages.error(request, 'Please log in first.')
        return redirect('login')

    try:
        # Verify current user is admin
        current_user_id = request.session.get('user_id')
        current_user_response = supabase.table('users').select('role').eq('id', current_user_id).execute()
        
        if not current_user_response.data:
            messages.error(request, 'User not found.')
            return redirect('manage_users')
        
        raw_current_role = current_user_response.data[0].get('role', 'user')
        current_role = str(raw_current_role).strip().lower() if raw_current_role else 'user'
        if current_role != 'admin':
            messages.error(request, 'Access denied. Admins only.')
            return redirect('user_dashboard')
        
        # Get form data
        user_id = request.POST.get('user_id')
        new_password = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()
        
        if not user_id or not new_password or not confirm_password:
            messages.error(request, 'All fields are required.')
            return redirect('manage_users')
        
        if new_password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return redirect('manage_users')
        
        # Update password using Supabase admin API
        try:
            supabase.auth.admin.update_user_by_id(
                user_id,
                {"password": new_password}
            )
            messages.success(request, 'Password reset successfully.')
        except AttributeError:
            # Fallback if admin API not available
            messages.error(request, 'Password reset is not available. Please contact system administrator.')
        except Exception as e:
            messages.error(request, f'Failed to reset password: {str(e)}')
        
    except Exception as e:
        messages.error(request, f'Error: {str(e)}')
    
    return redirect('manage_users')


@require_POST
def handle_check_in(request, slot_id):
    """
    API Endpoint: Vehicle Check-In
    Updates the slot's status to 'occupied', stores license plate, and sets check_in_time.
    """
    if 'access_token' not in request.session:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        # Get license plate from request
        if request.content_type and 'application/json' in request.content_type:
            import json
            data = json.loads(request.body)
            license_plate = data.get('license_plate', '').strip()
        else:
            license_plate = request.POST.get('license_plate', '').strip()
        
        if not license_plate:
            return JsonResponse({'error': 'License plate is required'}, status=400)
        # Normalize formatting for consistency
        license_plate = license_plate.strip().upper()
        
        # Get current slot status and lot_id in one query
        slot_resp = supabase.table('parking_slot').select('id, status, lot_id').eq('id', slot_id).execute()
        
        if not slot_resp.data or len(slot_resp.data) == 0:
            return JsonResponse({'error': 'Slot not found'}, status=404)
        
        current_slot = slot_resp.data[0]
        current_status = (current_slot.get('status') or 'available').lower()
        lot_id = current_slot.get('lot_id')
        
        # Validation: Check if slot is already occupied
        if current_status == 'occupied':
            return JsonResponse({'error': 'Slot is already occupied'}, status=400)
        
        # Validate lot_id exists
        if not lot_id:
            return JsonResponse({'error': 'Slot does not have an associated parking lot'}, status=400)
        
        if not license_plate:
            return JsonResponse({'error': 'No license plate recorded for this slot. Please enter the plate number before checking out.'}, status=400)
        
        # Get lot code from parking_lot table for zone field
        lot_code = None
        try:
            lot_resp = supabase.table('parking_lot').select('code').eq('id', lot_id).execute()
            if lot_resp.data and len(lot_resp.data) > 0:
                lot_code = lot_resp.data[0].get('code')
                print(f"Retrieved lot code: {lot_code} for lot_id: {lot_id}")
        except Exception as e:
            print(f"Warning: Failed to retrieve lot code: {str(e)}")
            # Continue without zone if we can't get the code
        
        # Update slot with check-in information
        from datetime import datetime
        check_in_time = datetime.now(dt_timezone.utc).isoformat()
        
        # First update status (this column definitely exists)
        update_data = {
            'status': 'occupied',
        }
        supabase.table('parking_slot').update(update_data).eq('id', slot_id).execute()
        
        # Try to update license_plate and check_in_time if columns exist
        try:
            update_data_extended = {
                'license_plate': license_plate,
                'check_in_time': check_in_time
            }
            supabase.table('parking_slot').update(update_data_extended).eq('id', slot_id).execute()
        except Exception:
            # Columns don't exist yet - that's okay, status was updated
            pass
        
        # Create or get vehicle record - always fetch by plate first, then insert if needed
        vehicle_id = None
        vehicle_error = None
        
        try:
            # ALWAYS try to find existing vehicle by plate first (case-insensitive search)
            # Try exact match first
            vehicle_resp = supabase.table('vehicle').select('id, plate').eq('plate', license_plate).execute()
            
            # If not found, try case-insensitive search using ilike
            if not vehicle_resp.data or len(vehicle_resp.data) == 0:
                vehicle_resp = supabase.table('vehicle').select('id, plate').ilike('plate', license_plate).execute()
            
            if vehicle_resp.data and len(vehicle_resp.data) > 0:
                vehicle_id = vehicle_resp.data[0]['id']
                actual_plate = vehicle_resp.data[0].get('plate', license_plate)
                print(f"Found existing vehicle with id: {vehicle_id} for plate: {actual_plate} (searched for: {license_plate})")
            else:
                # Vehicle doesn't exist, try to create it with normalized plate
                print(f"Vehicle with plate '{license_plate}' not found, creating new vehicle...")
                try:
                    vehicle_insert = supabase.table('vehicle').insert({'plate': license_plate}).execute()
                    if vehicle_insert.data and len(vehicle_insert.data) > 0:
                        vehicle_id = vehicle_insert.data[0]['id']
                        print(f"Created new vehicle with id: {vehicle_id} for plate: {license_plate}")
                    else:
                        # Insert succeeded but no data returned, fetch it
                        vehicle_resp_after_insert = supabase.table('vehicle').select('id').eq('plate', license_plate).execute()
                        if vehicle_resp_after_insert.data and len(vehicle_resp_after_insert.data) > 0:
                            vehicle_id = vehicle_resp_after_insert.data[0]['id']
                            print(f"Retrieved vehicle id: {vehicle_id} after insert")
                        else:
                            vehicle_error = "Vehicle insert succeeded but vehicle not found after insert"
                            print(f"Error: {vehicle_error}")
                except Exception as insert_error:
                    # If insert fails for ANY reason (duplicate key, constraint violation, etc.), fetch by plate
                    error_str = str(insert_error)
                    error_dict = {}
                    error_code = ''
                    error_message = error_str
                    
                    # Parse error - could be dict or string
                    if hasattr(insert_error, 'args') and insert_error.args:
                        if isinstance(insert_error.args[0], dict):
                            error_dict = insert_error.args[0]
                            error_code = error_dict.get('code', '')
                            error_message = error_dict.get('message', error_str)
                        elif isinstance(insert_error.args[0], str):
                            error_message = insert_error.args[0]
                    
                    print(f"Vehicle insert failed (code: {error_code}, message: {error_message}), fetching existing vehicle by plate...")
                    
                    # ALWAYS try to fetch by plate after insert error - vehicle might already exist
                    # Try multiple search methods to be sure
                    vehicle_found = False
                    for search_plate in [license_plate, license_plate.strip()]:
                        try:
                            vehicle_resp_retry = supabase.table('vehicle').select('id, plate').eq('plate', search_plate).execute()
                            if not vehicle_resp_retry.data or len(vehicle_resp_retry.data) == 0:
                                vehicle_resp_retry = supabase.table('vehicle').select('id, plate').ilike('plate', search_plate).execute()
                            
                            if vehicle_resp_retry.data and len(vehicle_resp_retry.data) > 0:
                                vehicle_id = vehicle_resp_retry.data[0]['id']
                                actual_plate = vehicle_resp_retry.data[0].get('plate', search_plate)
                                print(f"Successfully retrieved existing vehicle with id: {vehicle_id} for plate: {actual_plate} (searched: {search_plate})")
                                vehicle_found = True
                                break
                        except Exception as fetch_error:
                            print(f"Fetch attempt failed for '{search_plate}': {str(fetch_error)}")
                            continue
                    
                    if not vehicle_found:
                        # Vehicle truly doesn't exist and insert failed
                        vehicle_error = f"Failed to create vehicle and vehicle not found after multiple search attempts. Error: {error_message}"
                        print(f"Error: {vehicle_error}")
        except Exception as e:
            vehicle_error = str(e)
            print(f"Error creating/finding vehicle: {vehicle_error}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
        
        # Create entry record in entries_exits (parking history)
        history_error = None
        entry_created = False
        if vehicle_id and lot_id:
            try:
                # Ensure lot_id and vehicle_id are the correct type (int/str as needed by Supabase)
                entry_data = {
                    'time': check_in_time,
                    'vehicle_id': vehicle_id,
                    'action': 'entry',
                    'lot_id': lot_id
                }
                # Include zone (lot code) if we retrieved it
                if lot_code:
                    entry_data['zone'] = lot_code
                
                entry_result = supabase.table('entries_exits').insert(entry_data).execute()
                
                # Verify the entry was created
                if entry_result.data and len(entry_result.data) > 0:
                    entry_created = True
                    print(f"Successfully created parking history entry: {entry_result.data[0]}")
                else:
                    history_error = "Entry record created but no data returned"
                    print(f"Warning: {history_error}")
            except Exception as e:
                history_error = str(e)
                error_str = str(e)
                error_dict = {}
                error_code = ''
                
                # Parse error - check if it's a duplicate key error on the id column
                if hasattr(e, 'args') and e.args:
                    if isinstance(e.args[0], dict):
                        error_dict = e.args[0]
                        error_code = error_dict.get('code', '')
                        error_message = error_dict.get('message', error_str)
                    else:
                        error_message = error_str
                else:
                    error_message = error_str
                
                # Check if it's a sequence/duplicate key issue on the id column
                is_sequence_error = (
                    error_code == '23505' and 
                    ('entries_exits_pkey' in error_message or 'id' in error_message.lower())
                )
                
                if is_sequence_error:
                    print(f"Sequence error detected on entries_exits table. Error: {error_message}")
                    print("NOTE: You need to run the SQL script 'fix_entries_exits_sequence.sql' in Supabase to fix this.")
                    history_error = f"Database sequence issue: {error_message}. Please run fix_entries_exits_sequence.sql in Supabase SQL Editor."
                else:
                    import traceback
                    print(f"Error creating parking history entry: {history_error}")
                    print(f"Traceback: {traceback.format_exc()}")
                # Still continue - slot update was successful
        else:
            missing = []
            if not vehicle_id:
                missing.append('vehicle_id')
            if not lot_id:
                missing.append('lot_id')
            history_error = f"Missing required data: {', '.join(missing)}"
            print(f"Warning: Cannot create parking history entry - {history_error}")
            print(f"Debug - vehicle_id: {vehicle_id}, lot_id: {lot_id}")
        
        # Return success response (slot update succeeded even if history creation had issues)
        response_data = {
            'success': True,
            'message': 'Vehicle checked in successfully',
            'slot_id': slot_id,
            'license_plate': license_plate,
            'check_in_time': check_in_time,
            'history_created': entry_created,
            'vehicle_id': vehicle_id,
            'lot_id': lot_id
        }
        
        # Include warnings if history creation had issues
        if history_error:
            response_data['warning'] = f"Parking history may not have been updated: {history_error}"
        if vehicle_error:
            response_data['vehicle_warning'] = f"Vehicle record issue: {vehicle_error}"
        
        return JsonResponse(response_data)
        
    except Exception as e:
        return JsonResponse({'error': f'Check-in failed: {str(e)}'}, status=500)


@require_POST
def handle_check_out(request, slot_id):
    """
    API Endpoint: Vehicle Check-Out
    Updates the slot's status to 'available' and clears license_plate and check_in_time.
    """
    if 'access_token' not in request.session:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        provided_plate = ''
        try:
            if request.content_type and 'application/json' in request.content_type:
                import json
                body = json.loads(request.body)
                provided_plate = (body.get('license_plate') or '').strip().upper()
            else:
                provided_plate = (request.POST.get('license_plate') or '').strip().upper()
        except Exception:
            provided_plate = ''
        
        # Get current slot information
        slot_resp = supabase.table('parking_slot').select('id, status, license_plate, slot_number, lot_id').eq('id', slot_id).execute()
        
        if not slot_resp.data or len(slot_resp.data) == 0:
            return JsonResponse({'error': 'Slot not found'}, status=404)
        
        current_slot = slot_resp.data[0]
        current_status = (current_slot.get('status') or 'available').lower()
        license_plate = (provided_plate or current_slot.get('license_plate') or '').strip().upper()
        slot_number = current_slot.get('slot_number', '')
        lot_id = current_slot.get('lot_id')
        
        # Validation: Check if slot is actually occupied
        if current_status != 'occupied':
            return JsonResponse({'error': 'Slot is not currently occupied'}, status=400)
        
        # Validate lot_id exists
        if not lot_id:
            return JsonResponse({'error': 'Slot does not have an associated parking lot'}, status=400)
        
        # Get lot code from parking_lot table for zone field
        lot_code = None
        try:
            lot_resp = supabase.table('parking_lot').select('code').eq('id', lot_id).execute()
            if lot_resp.data and len(lot_resp.data) > 0:
                lot_code = lot_resp.data[0].get('code')
                print(f"Retrieved lot code: {lot_code} for lot_id: {lot_id}")
        except Exception as e:
            print(f"Warning: Failed to retrieve lot code: {str(e)}")
            # Continue without zone if we can't get the code
        
        # Get vehicle_id for exit record
        vehicle_id = None
        vehicle_error = None
        if license_plate:
            try:
                vehicle_resp = supabase.table('vehicle').select('id').eq('plate', license_plate).execute()
                if vehicle_resp.data and len(vehicle_resp.data) > 0:
                    vehicle_id = vehicle_resp.data[0]['id']
                    print(f"Found vehicle with id: {vehicle_id} for plate: {license_plate}")
                else:
                    # Vehicle doesn't exist - this shouldn't happen on check-out, but handle it gracefully
                    vehicle_error = f"Vehicle with plate {license_plate} not found in database"
                    print(f"Warning: {vehicle_error}")
            except Exception as e:
                vehicle_error = str(e)
                print(f"Error finding vehicle: {vehicle_error}")
                import traceback
                print(f"Traceback: {traceback.format_exc()}")
        
        # Update slot - clear check-out information
        from datetime import datetime
        check_out_time = datetime.now(dt_timezone.utc).isoformat()
        
        # First update status (this column definitely exists)
        update_data = {
            'status': 'available',
        }
        supabase.table('parking_slot').update(update_data).eq('id', slot_id).execute()
        
        # Try to clear license_plate and check_in_time if columns exist
        try:
            update_data_extended = {
                'license_plate': None,
                'check_in_time': None
            }
            supabase.table('parking_slot').update(update_data_extended).eq('id', slot_id).execute()
        except Exception:
            # Columns don't exist yet - that's okay, status was updated
            pass
        
        # Create exit record in entries_exits (parking history)
        history_error = None
        exit_created = False
        if vehicle_id and lot_id:
            try:
                # Ensure lot_id and vehicle_id are the correct type (int/str as needed by Supabase)
                exit_data = {
                    'time': check_out_time,
                    'vehicle_id': vehicle_id,
                    'action': 'exit',
                    'lot_id': lot_id
                }
                # Include zone (lot code) if we retrieved it
                if lot_code:
                    exit_data['zone'] = lot_code
                
                exit_result = supabase.table('entries_exits').insert(exit_data).execute()
                
                # Verify the exit was created
                if exit_result.data and len(exit_result.data) > 0:
                    exit_created = True
                    print(f"Successfully created parking history exit: {exit_result.data[0]}")
                else:
                    history_error = "Exit record created but no data returned"
                    print(f"Warning: {history_error}")
            except Exception as e:
                history_error = str(e)
                error_str = str(e)
                error_dict = {}
                error_code = ''
                
                # Parse error - check if it's a duplicate key error on the id column
                if hasattr(e, 'args') and e.args:
                    if isinstance(e.args[0], dict):
                        error_dict = e.args[0]
                        error_code = error_dict.get('code', '')
                        error_message = error_dict.get('message', error_str)
                    else:
                        error_message = error_str
                else:
                    error_message = error_str
                
                # Check if it's a sequence/duplicate key issue on the id column
                is_sequence_error = (
                    error_code == '23505' and 
                    ('entries_exits_pkey' in error_message or 'id' in error_message.lower())
                )
                
                if is_sequence_error:
                    print(f"Sequence error detected on entries_exits table. Error: {error_message}")
                    print("NOTE: You need to run the SQL script 'fix_entries_exits_sequence.sql' in Supabase to fix this.")
                    history_error = f"Database sequence issue: {error_message}. Please run fix_entries_exits_sequence.sql in Supabase SQL Editor."
                else:
                    import traceback
                    print(f"Error creating parking history exit: {history_error}")
                    print(f"Traceback: {traceback.format_exc()}")
                # Still continue - slot update was successful
        else:
            missing = []
            if not vehicle_id:
                missing.append('vehicle_id')
            if not lot_id:
                missing.append('lot_id')
            history_error = f"Missing required data: {', '.join(missing)}"
            print(f"Warning: Cannot create parking history exit - {history_error}")
            print(f"Debug - vehicle_id: {vehicle_id}, lot_id: {lot_id}")
        
        # Return success response (slot update succeeded even if history creation had issues)
        response_data = {
            'success': True,
            'message': 'Vehicle checked out successfully',
            'slot_id': slot_id,
            'slot_number': slot_number,
            'license_plate': license_plate,
            'history_created': exit_created,
            'vehicle_id': vehicle_id,
            'lot_id': lot_id
        }
        
        # Include warnings if history creation had issues
        if history_error:
            response_data['warning'] = f"Parking history may not have been updated: {history_error}"
        if vehicle_error:
            response_data['vehicle_warning'] = f"Vehicle record issue: {vehicle_error}"
        
        return JsonResponse(response_data)
        
    except Exception as e:
        return JsonResponse({'error': f'Check-out failed: {str(e)}'}, status=500)


def get_slot_details(request, slot_id):
    """
    API Endpoint: Get slot details including license plate and check-in time
    """
    if 'access_token' not in request.session:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        # Select base columns - include license_plate/check_in_time when available
        try:
            slot_resp = supabase.table('parking_slot').select(
                'id, lot_id, slot_number, status, license_plate, check_in_time'
            ).eq('id', slot_id).execute()
        except Exception:
            slot_resp = supabase.table('parking_slot').select('id, lot_id, slot_number, status').eq('id', slot_id).execute()
        
        if not slot_resp.data:
            return JsonResponse({'error': 'Slot not found'}, status=404)
        
        slot = slot_resp.data[0]
        # Add default values for columns that might not exist
        return JsonResponse({
            'success': True,
            'slot': {
                'id': slot.get('id'),
                'slot_number': slot.get('slot_number'),
                'status': slot.get('status'),
                'license_plate': slot.get('license_plate', None),
                'check_in_time': slot.get('check_in_time', None),
            }
        })
        
    except Exception as e:
        return JsonResponse({'error': f'Failed to get slot details: {str(e)}'}, status=500)


class AdvancedReportsView(View):
    """Advanced Reports page for admin - shows analytics, charts, and export options"""
    
    def get(self, request):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return redirect('login')

        try:
            user_id = request.session.get('user_id')
            user_response = supabase.table('users').select(
                'first_name, last_name, email, student_employee_id, role'
            ).eq('id', user_id).execute()

            if not user_response.data:
                messages.error(request, 'User not found.')
                return redirect('home')

            user_data = user_response.data[0]
            raw_role = user_data.get('role') or 'user'
            role_name = str(raw_role).strip().lower() if raw_role else 'user'
            if role_name not in ['admin', 'user']:
                role_name = 'user'

            # Only allow admins
            if role_name != 'admin':
                messages.error(request, 'Access denied. Admins only.')
                return redirect('user_dashboard')

        except Exception as e:
            messages.error(request, f'Error loading user: {str(e)}')
            return redirect('home')

        # Get filter parameters
        date_range = request.GET.get('date_range', '30')
        selected_lot = request.GET.get('lot_id', '')
        vehicle_search = request.GET.get('vehicle', '')
        selected_month = request.GET.get('month', '')

        # Calculate date range
        now = timezone.now()
        try:
            days_back = int(date_range)
        except ValueError:
            days_back = 30
        
        start_date = now - timedelta(days=days_back)

        # Fetch parking lots for filter dropdown
        try:
            lots_resp = supabase.table('parking_lot').select('id, name, code').order('code').execute()
            parking_lots = lots_resp.data or []
        except Exception:
            parking_lots = []

        # Fetch parking sessions data
        try:
            entries_query = supabase.table('entries_exits').select(
                'id, time, vehicle_id, action, lot_id'
            ).eq('action', 'entry').gte('time', start_date.isoformat()).order('time', desc=True)
            
            if selected_lot:
                entries_query = entries_query.eq('lot_id', int(selected_lot))
            
            entries_response = entries_query.execute()
            entry_records = entries_response.data or []
        except Exception:
            entry_records = []

        # Fetch vehicle data
        vehicle_ids = list(set([e['vehicle_id'] for e in entry_records if e.get('vehicle_id')]))
        vehicles_map = {}
        if vehicle_ids:
            try:
                vehicles_query = supabase.table('vehicle').select('id, plate').in_('id', vehicle_ids)
                if vehicle_search:
                    vehicles_query = vehicles_query.ilike('plate', f'%{vehicle_search}%')
                vehicles_response = vehicles_query.execute()
                vehicles_map = {v['id']: v.get('plate', '') for v in (vehicles_response.data or [])}
            except Exception:
                vehicles_map = {}

        # Fetch lots mapping
        lot_ids = list(set([e['lot_id'] for e in entry_records if e.get('lot_id')]))
        lots_map = {}
        if lot_ids:
            try:
                lots_data = supabase.table('parking_lot').select('id, name').in_('id', lot_ids).execute()
                lots_map = {l['id']: l.get('name', '') for l in (lots_data.data or [])}
            except Exception:
                lots_map = {}

        # Build sessions with exit data
        parking_logs = []
        total_duration_minutes = 0
        completed_count = 0

        for entry in entry_records:
            vehicle_id = entry.get('vehicle_id')
            lot_id = entry.get('lot_id')
            entry_time = entry.get('time')

            if vehicle_search and vehicle_id not in vehicles_map:
                continue

            plate_number = vehicles_map.get(vehicle_id, 'Unknown')
            lot_name_value = lots_map.get(lot_id, 'Unknown')

            # Find exit
            exit_time = None
            try:
                exit_resp = supabase.table('entries_exits').select('time').eq(
                    'vehicle_id', vehicle_id
                ).eq('action', 'exit').gte('time', entry_time).order('time').limit(1).execute()
                if exit_resp.data:
                    exit_time = exit_resp.data[0].get('time')
            except Exception:
                pass

            status = 'Completed' if exit_time else 'Active'
            status_class = 'completed' if exit_time else 'active'
            duration = calculate_duration(entry_time, exit_time)

            # Track stats
            if exit_time:
                completed_count += 1
                try:
                    entry_dt = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
                    exit_dt = datetime.fromisoformat(exit_time.replace('Z', '+00:00'))
                    total_duration_minutes += (exit_dt - entry_dt).total_seconds() / 60
                except Exception:
                    pass

            parking_logs.append({
                'id': entry.get('id'),
                'vehicle_plate': plate_number,
                'lot_name': lot_name_value,
                'entry_time': entry_time,
                'exit_time': exit_time,
                'duration': duration,
                'status': status,
                'status_class': status_class,
            })

        # Calculate statistics
        total_sessions = len(parking_logs)
        avg_duration_minutes = total_duration_minutes / completed_count if completed_count > 0 else 0
        avg_duration_hours = avg_duration_minutes / 60
        if avg_duration_hours >= 1:
            avg_duration = f"{int(avg_duration_hours)}h {int(avg_duration_minutes % 60)}m"
        else:
            avg_duration = f"{int(avg_duration_minutes)}m"

        # Calculate monthly usage data for chart
        monthly_data = defaultdict(int)
        for log in parking_logs:
            try:
                entry_dt = datetime.fromisoformat(log['entry_time'].replace('Z', '+00:00'))
                month_key = entry_dt.strftime('%b %Y')
                monthly_data[month_key] += 1
            except Exception:
                pass

        # Sort by date and prepare for chart
        sorted_months = sorted(monthly_data.items(), 
                               key=lambda x: datetime.strptime(x[0], '%b %Y'))
        monthly_labels = [m[0] for m in sorted_months[-12:]]  # Last 12 months
        monthly_usage = [m[1] for m in sorted_months[-12:]]

        # Daily usage for the selected period (for more granular chart)
        daily_data = defaultdict(int)
        for log in parking_logs:
            try:
                entry_dt = datetime.fromisoformat(log['entry_time'].replace('Z', '+00:00'))
                day_key = entry_dt.strftime('%b %d')
                daily_data[day_key] += 1
            except Exception:
                pass

        # Peak hours analysis
        hourly_data = defaultdict(int)
        for log in parking_logs:
            try:
                entry_dt = datetime.fromisoformat(log['entry_time'].replace('Z', '+00:00'))
                hour = entry_dt.hour
                hourly_data[hour] += 1
            except Exception:
                pass

        peak_hours = sorted(hourly_data.items(), key=lambda x: x[1], reverse=True)[:5]
        peak_hour_labels = [f"{h[0]:02d}:00" for h in peak_hours]
        peak_hour_values = [h[1] for h in peak_hours]

        # Lot usage breakdown
        lot_usage = defaultdict(int)
        for log in parking_logs:
            lot_usage[log['lot_name']] += 1
        
        lot_labels = list(lot_usage.keys())
        lot_values = list(lot_usage.values())

        import json

        context = {
            'role': role_name,
            'full_name': f"{user_data['first_name']} {user_data['last_name']}",
            'email': user_data['email'],
            'username': user_data['student_employee_id'],
            # Stats
            'total_sessions': total_sessions,
            'avg_duration': avg_duration,
            'completed_sessions': completed_count,
            'active_sessions': total_sessions - completed_count,
            # Filters
            'parking_lots': parking_lots,
            'date_range': date_range,
            'selected_lot': selected_lot,
            'vehicle_search': vehicle_search,
            'selected_month': selected_month,
            # Data
            'parking_logs': parking_logs[:100],  # Limit for display
            # Chart data (JSON encoded)
            'monthly_labels': json.dumps(monthly_labels if monthly_labels else ['No Data']),
            'monthly_usage': json.dumps(monthly_usage if monthly_usage else [0]),
            'daily_labels': json.dumps(list(daily_data.keys())[-30:]),
            'daily_usage': json.dumps(list(daily_data.values())[-30:]),
            'peak_hour_labels': json.dumps(peak_hour_labels if peak_hour_labels else ['No Data']),
            'peak_hour_values': json.dumps(peak_hour_values if peak_hour_values else [0]),
            'lot_labels': json.dumps(lot_labels if lot_labels else ['No Data']),
            'lot_values': json.dumps(lot_values if lot_values else [0]),
        }

        return render(request, 'advanced_reports.html', context)


def export_parking_csv(request):
    """
    API Endpoint: GET /api/admin/reports/export-csv/
    
    Exports filtered parking logs to CSV file.
    Admin-only endpoint.
    """
    import csv
    from django.http import HttpResponse
    
    # Authentication check
    if 'access_token' not in request.session:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        # Verify user is admin
        user_id = request.session.get('user_id')
        user_response = supabase.table('users').select('role').eq('id', user_id).execute()
        
        if not user_response.data:
            return JsonResponse({'error': 'User not found'}, status=404)
        
        raw_role = user_response.data[0].get('role') or 'user'
        role_name = str(raw_role).strip().lower() if raw_role else 'user'
        
        if role_name != 'admin':
            return JsonResponse({'error': 'Admin privileges required'}, status=403)
    except Exception as e:
        return JsonResponse({'error': f'Authentication error: {str(e)}'}, status=500)
    
    # Get filter parameters
    date_range = request.GET.get('date_range', '30')
    selected_lot = request.GET.get('lot_id', '')
    vehicle_search = request.GET.get('vehicle', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    status_filter = request.GET.get('status', '')

    # Calculate date range
    now = timezone.now()
    if date_from:
        start_date = datetime.fromisoformat(date_from)
    else:
        try:
            days_back = int(date_range)
        except ValueError:
            days_back = 30
        start_date = now - timedelta(days=days_back)

    if date_to:
        end_date = datetime.fromisoformat(date_to) + timedelta(days=1)
    else:
        end_date = now + timedelta(days=1)

    try:
        # Fetch entries
        entries_query = supabase.table('entries_exits').select(
            'id, time, vehicle_id, action, lot_id'
        ).eq('action', 'entry').gte('time', start_date.isoformat()).lte('time', end_date.isoformat()).order('time', desc=True)
        
        if selected_lot:
            entries_query = entries_query.eq('lot_id', int(selected_lot))
        
        entries_response = entries_query.execute()
        entry_records = entries_response.data or []

        # Fetch vehicles
        vehicle_ids = list(set([e['vehicle_id'] for e in entry_records if e.get('vehicle_id')]))
        vehicles_map = {}
        if vehicle_ids:
            vehicles_query = supabase.table('vehicle').select('id, plate').in_('id', vehicle_ids)
            if vehicle_search:
                vehicles_query = vehicles_query.ilike('plate', f'%{vehicle_search}%')
            vehicles_response = vehicles_query.execute()
            vehicles_map = {v['id']: v.get('plate', '') for v in (vehicles_response.data or [])}

        # Fetch lots
        lot_ids = list(set([e['lot_id'] for e in entry_records if e.get('lot_id')]))
        lots_map = {}
        if lot_ids:
            lots_data = supabase.table('parking_lot').select('id, name').in_('id', lot_ids).execute()
            lots_map = {l['id']: l.get('name', '') for l in (lots_data.data or [])}

        # Build CSV data
        csv_data = []
        for entry in entry_records:
            vehicle_id = entry.get('vehicle_id')
            lot_id = entry.get('lot_id')
            entry_time = entry.get('time')

            if vehicle_search and vehicle_id not in vehicles_map:
                continue

            plate_number = vehicles_map.get(vehicle_id, 'Unknown')
            lot_name_value = lots_map.get(lot_id, 'Unknown')

            # Find exit
            exit_time = None
            try:
                exit_resp = supabase.table('entries_exits').select('time').eq(
                    'vehicle_id', vehicle_id
                ).eq('action', 'exit').gte('time', entry_time).order('time').limit(1).execute()
                if exit_resp.data:
                    exit_time = exit_resp.data[0].get('time')
            except Exception:
                pass

            status = 'Completed' if exit_time else 'Active'
            
            # Apply status filter
            if status_filter and status != status_filter:
                continue

            duration = calculate_duration(entry_time, exit_time)

            # Format datetime for CSV
            try:
                entry_dt = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
                entry_formatted = entry_dt.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                entry_formatted = entry_time

            if exit_time:
                try:
                    exit_dt = datetime.fromisoformat(exit_time.replace('Z', '+00:00'))
                    exit_formatted = exit_dt.strftime('%Y-%m-%d %H:%M:%S')
                except Exception:
                    exit_formatted = exit_time
            else:
                exit_formatted = ''

            csv_data.append({
                'Session ID': entry.get('id'),
                'Vehicle Plate': plate_number,
                'Parking Lot': lot_name_value,
                'Entry Time': entry_formatted,
                'Exit Time': exit_formatted,
                'Duration': duration,
                'Status': status,
            })

        # Create CSV response
        response = HttpResponse(content_type='text/csv')
        filename = f"parking_logs_{now.strftime('%Y%m%d_%H%M%S')}.csv"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        if csv_data:
            writer = csv.DictWriter(response, fieldnames=csv_data[0].keys())
            writer.writeheader()
            writer.writerows(csv_data)
        else:
            writer = csv.writer(response)
            writer.writerow(['No data found for the selected filters'])

        return response

    except Exception as e:
        return JsonResponse({'error': f'Export failed: {str(e)}'}, status=500)


def monthly_report_api(request):
    """
    API Endpoint: GET /api/admin/reports/monthly/
    
    Returns monthly usage statistics for the reports dashboard.
    Admin-only endpoint.
    """
    # Authentication check
    if 'access_token' not in request.session:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        # Verify user is admin
        user_id = request.session.get('user_id')
        user_response = supabase.table('users').select('role').eq('id', user_id).execute()
        
        if not user_response.data:
            return JsonResponse({'error': 'User not found'}, status=404)
        
        raw_role = user_response.data[0].get('role') or 'user'
        role_name = str(raw_role).strip().lower() if raw_role else 'user'
        
        if role_name != 'admin':
            return JsonResponse({'error': 'Admin privileges required'}, status=403)
    except Exception as e:
        return JsonResponse({'error': f'Authentication error: {str(e)}'}, status=500)

    # Get parameters
    year = request.GET.get('year', str(timezone.now().year))
    month = request.GET.get('month', '')
    lot_id = request.GET.get('lot_id', '')

    try:
        year_int = int(year)
    except ValueError:
        year_int = timezone.now().year

    try:
        # Build date range for the year
        start_date = datetime(year_int, 1, 1)
        end_date = datetime(year_int, 12, 31, 23, 59, 59)

        if month:
            try:
                month_int = int(month)
                start_date = datetime(year_int, month_int, 1)
                if month_int == 12:
                    end_date = datetime(year_int + 1, 1, 1) - timedelta(seconds=1)
                else:
                    end_date = datetime(year_int, month_int + 1, 1) - timedelta(seconds=1)
            except ValueError:
                pass

        # Fetch entries for the period
        entries_query = supabase.table('entries_exits').select(
            'id, time, vehicle_id, action, lot_id'
        ).eq('action', 'entry').gte('time', start_date.isoformat()).lte('time', end_date.isoformat())
        
        if lot_id:
            entries_query = entries_query.eq('lot_id', int(lot_id))
        
        entries_response = entries_query.execute()
        entry_records = entries_response.data or []

        # Calculate monthly breakdown
        monthly_stats = defaultdict(lambda: {
            'entries': 0,
            'exits': 0,
            'total_duration_minutes': 0,
            'completed_sessions': 0
        })

        vehicle_ids = list(set([e['vehicle_id'] for e in entry_records if e.get('vehicle_id')]))

        for entry in entry_records:
            try:
                entry_dt = datetime.fromisoformat(entry['time'].replace('Z', '+00:00'))
                month_key = entry_dt.strftime('%Y-%m')
                monthly_stats[month_key]['entries'] += 1

                # Find exit for duration calculation
                vehicle_id = entry.get('vehicle_id')
                entry_time = entry.get('time')
                
                exit_resp = supabase.table('entries_exits').select('time').eq(
                    'vehicle_id', vehicle_id
                ).eq('action', 'exit').gte('time', entry_time).order('time').limit(1).execute()
                
                if exit_resp.data:
                    exit_time = exit_resp.data[0].get('time')
                    monthly_stats[month_key]['exits'] += 1
                    monthly_stats[month_key]['completed_sessions'] += 1
                    
                    try:
                        exit_dt = datetime.fromisoformat(exit_time.replace('Z', '+00:00'))
                        duration_minutes = (exit_dt - entry_dt).total_seconds() / 60
                        monthly_stats[month_key]['total_duration_minutes'] += duration_minutes
                    except Exception:
                        pass
            except Exception:
                continue

        # Format response
        result = []
        for month_key in sorted(monthly_stats.keys()):
            stats = monthly_stats[month_key]
            avg_duration = stats['total_duration_minutes'] / stats['completed_sessions'] if stats['completed_sessions'] > 0 else 0
            
            result.append({
                'month': month_key,
                'month_label': datetime.strptime(month_key, '%Y-%m').strftime('%B %Y'),
                'total_entries': stats['entries'],
                'total_exits': stats['exits'],
                'completed_sessions': stats['completed_sessions'],
                'active_sessions': stats['entries'] - stats['completed_sessions'],
                'avg_duration_minutes': round(avg_duration, 1),
                'avg_duration_formatted': f"{int(avg_duration // 60)}h {int(avg_duration % 60)}m" if avg_duration >= 60 else f"{int(avg_duration)}m"
            })

        # Calculate totals
        total_entries = sum(m['total_entries'] for m in result)
        total_exits = sum(m['total_exits'] for m in result)
        total_completed = sum(m['completed_sessions'] for m in result)

        return JsonResponse({
            'success': True,
            'year': year_int,
            'month': month if month else 'all',
            'monthly_data': result,
            'summary': {
                'total_entries': total_entries,
                'total_exits': total_exits,
                'total_completed': total_completed,
                'total_active': total_entries - total_completed
            }
        })

    except Exception as e:
        return JsonResponse({'error': f'Failed to fetch monthly report: {str(e)}'}, status=500)