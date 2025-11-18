from django.shortcuts import render, redirect
from django.contrib import messages
from django.views import View
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.urls import reverse
from .forms import RegisterForm, LoginForm
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
        slots_resp = supabase.table('parking_slot').select('id, lot_id, slot_number, status').execute()
        slots = slots_resp.data or []
    except Exception:
        slots = []

    return lots, slots


def build_lot_display(lots, slots, selected_lot_id=None):
    slots_by_lot = defaultdict(list)
    for slot in slots:
        lot_id = slot.get('lot_id')
        if lot_id is None:
            continue
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

        try:
            user_resp = supabase.table('users')\
                .select('email, role_id')\
                .eq('student_employee_id', id_input)\
                .execute()
        except Exception as e:
            messages.error(request, f'Error connecting to database: {str(e)}')
            tmpl = f'signin_{portal}.html' if portal in ['admin', 'student'] else 'signin.html'
            return render(request, tmpl, {'form': form})

        if not user_resp.data:
            messages.error(request, 'ID not found.')
            tmpl = f'signin_{portal}.html' if portal in ['admin', 'student'] else 'signin.html'
            return render(request, tmpl, {'form': form})

        email   = user_resp.data[0]['email']
        role_id = user_resp.data[0]['role_id']

        try:
            auth_resp = supabase.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
        except Exception as e:
            messages.error(request, f'Authentication error: {str(e)}')
            tmpl = f'signin_{portal}.html' if portal in ['admin', 'student'] else 'signin.html'
            return render(request, tmpl, {'form': form})

        if not auth_resp.session:
            error_msg = 'Invalid credentials.'
            if hasattr(auth_resp, 'error') and auth_resp.error:
                error_msg = auth_resp.error.message or error_msg
            messages.error(request, error_msg)
            tmpl = f'signin_{portal}.html' if portal in ['admin', 'student'] else 'signin.html'
            return render(request, tmpl, {'form': form})


        request.session['access_token'] = auth_resp.session.access_token
        request.session['user_id']      = auth_resp.user.id


        try:
            role_resp = supabase.table('roles')\
                .select('role_name')\
                .eq('role_id', role_id)\
                .execute()
        except Exception as e:
            messages.error(request, f'Error fetching role: {str(e)}')
            tmpl = f'signin_{portal}.html' if portal in ['admin', 'student'] else 'signin.html'
            return render(request, tmpl, {'form': form})

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

        # Store role in session for later use
        request.session['role_name'] = role_name

        messages.success(request, 'Login successful!')
        
        # Redirect based on role
        if role_name == 'admin':
            return redirect('dashboard')
        else:
            # Students and other roles go to parking spaces
            return redirect('user_dashboard')

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

        try:
            user_id = request.session.get('user_id')
            user_response = supabase.table('users').select('first_name, last_name, email, student_employee_id, role_id').eq('id', user_id).execute()

            if not user_response.data:
                messages.error(request, 'User not found.')
                return redirect('home')

            user_data = user_response.data[0]
            role_response = supabase.table('roles').select('role_name').eq('role_id', user_data['role_id']).execute()
            role_name = role_response.data[0]['role_name'] if role_response.data else 'student'
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
            return redirect('home')

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
            if action.startswith('enter'):
                total_entries += 1
            elif action.startswith('exit'):
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
            return redirect('signin', portal='student')

        try:
            user_id = request.session.get('user_id')
            user_response = supabase.table('users').select(
                'first_name, last_name, email, student_employee_id, role_id'
            ).eq('id', user_id).execute()

            if not user_response.data:
                messages.error(request, 'User not found.')
                return redirect('home')

            user_data = user_response.data[0]

            # Fetch role
            role_response = supabase.table('roles').select('role_name').eq(
                'role_id', user_data['role_id']
            ).execute()

            role_name = role_response.data[0]['role_name'] if role_response.data else 'student'

            # Prevent admin from entering student dashboard
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
            return redirect('signin', portal='student')

        try:
            user_id = request.session.get('user_id')
            user_response = supabase.table('users').select(
                'first_name, last_name, email, student_employee_id, role_id'
            ).eq('id', user_id).execute()

            if not user_response.data:
                messages.error(request, 'User not found.')
                return redirect('home')

            user_data = user_response.data[0]
            role_response = supabase.table('roles').select('role_name').eq(
                'role_id', user_data['role_id']
            ).execute()
            role_name = role_response.data[0]['role_name'] if role_response.data else 'student'
        except ValueError:
            messages.error(request, 'Server configuration error. Please contact administrator.')
            return redirect('home')
        except Exception as e:
            messages.error(request, f'Database error: {str(e)}')
            return redirect('home')

    # Only allow admins to manage parking slots
        if role_name != 'admin':
            messages.error(request, 'Access denied. Admins only.')
            return redirect('home')

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


class StudentParkingSpacesView(View):
    def get(self, request):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return redirect('signin', portal='student')

        try:
            user_id = request.session.get('user_id')
            user_response = supabase.table('users').select(
                'first_name, last_name, email, student_employee_id, role_id'
            ).eq('id', user_id).execute()

            if not user_response.data:
                messages.error(request, 'User not found.')
                return redirect('home')

            user_data = user_response.data[0]
            role_response = supabase.table('roles').select('role_name').eq(
                'role_id', user_data['role_id']
            ).execute()
            role_name = role_response.data[0]['role_name'] if role_response.data else 'student'
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
            return redirect('signin', portal='student')

        try:
            user_id = request.session.get('user_id')
            user_response = supabase.table('users').select('first_name, last_name, email, student_employee_id, role_id').eq('id', user_id).execute()

            if not user_response.data:
                messages.error(request, 'User not found.')
                return redirect('home')

            user_data = user_response.data[0]
            role_response = supabase.table('roles').select('role_name').eq('role_id', user_data['role_id']).execute()
            role_name = role_response.data[0]['role_name'] if role_response.data else 'student'
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
            return redirect('home')

        try:
            users_response = supabase.table('users').select(
                'id, first_name, last_name, student_employee_id, status, created_at, roles(role_name)'
            ).order('created_at', desc=True).execute()
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
            role_data = item.get('roles') or {}
            role_label = (role_data.get('role_name') or '—').title()
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
        }
        return render(request, 'manage_users.html', context)


class EditUserView(View):
    """Edit another user's full name, username, and role (admin only)."""

    def _require_admin(self, request):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return None, None, redirect('signin', portal='student')

        try:
            current_user_id = request.session.get('user_id')
            user_response = supabase.table('users').select(
                'first_name, last_name, email, student_employee_id, role_id'
            ).eq('id', current_user_id).execute()

            if not user_response.data:
                messages.error(request, 'User not found.')
                return None, None, redirect('home')

            current_user = user_response.data[0]
            role_response = supabase.table('roles').select('role_name').eq(
                'role_id', current_user['role_id']
            ).execute()
            role_name = role_response.data[0]['role_name'] if role_response.data else 'student'
        except ValueError:
            messages.error(request, 'Server configuration error. Please contact administrator.')
            return None, None, redirect('home')
        except Exception as e:
            messages.error(request, f'Database error: {str(e)}')
            return None, None, redirect('home')

        if role_name != 'admin':
            messages.error(request, 'Access denied. Admins only.')
            return None, None, redirect('home')

        return current_user, role_name, None

    def _load_target_user_and_roles(self, user_id):
        # Load target user
        user_resp = supabase.table('users').select(
            'id, first_name, last_name, student_employee_id, role_id, status'
        ).eq('id', user_id).execute()

        if not user_resp.data:
            return None, None

        target = user_resp.data[0]

        # Load all possible roles
        roles_resp = supabase.table('roles').select('role_id, role_name').order(
            'role_name'
        ).execute()
        roles = roles_resp.data or []

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
        role_id_raw = request.POST.get('role_id')

        if not first_name or not last_name or not username or not role_id_raw:
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

        try:
            try:
                role_id = int(role_id_raw)
            except (TypeError, ValueError):
                role_id = role_id_raw

            supabase.table('users').update({
                'first_name': first_name,
                'last_name': last_name,
                'student_employee_id': username,
                'role_id': role_id,
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
        return redirect('signin', portal='student')

    try:
        current_user_id = request.session.get('user_id')
        user_response = supabase.table('users').select(
            'role_id'
        ).eq('id', current_user_id).execute()

        if not user_response.data:
            messages.error(request, 'User not found.')
            return redirect('home')

        current_user = user_response.data[0]
        role_response = supabase.table('roles').select('role_name').eq(
            'role_id', current_user['role_id']
        ).execute()
        role_name = role_response.data[0]['role_name'] if role_response.data else 'student'
    except Exception as e:
        messages.error(request, f'Database error: {str(e)}')
        return redirect('home')

    if role_name != 'admin':
        messages.error(request, 'Access denied. Admins only.')
        return redirect('home')

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
        try:
            roles_resp = supabase.table('roles').select('role_id, role_name').order(
                'role_name'
            ).execute()
            return roles_resp.data or []
        except Exception:
            return []

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
            'form_role_id': form_values.get('role_id', ''),
        }
        return render(request, 'add_user.html', context)

    def _require_admin(self, request):
        if 'access_token' not in request.session:
            messages.error(request, 'Please log in first.')
            return None, None, redirect('signin', portal='student')

        try:
            current_user_id = request.session.get('user_id')
            user_response = supabase.table('users').select(
                'first_name, last_name, email, student_employee_id, role_id'
            ).eq('id', current_user_id).execute()

            if not user_response.data:
                messages.error(request, 'User not found.')
                return None, None, redirect('home')

            current_user = user_response.data[0]
            role_response = supabase.table('roles').select('role_name').eq(
                'role_id', current_user['role_id']
            ).execute()
            role_name = role_response.data[0]['role_name'] if role_response.data else 'student'
        except ValueError:
            messages.error(request, 'Server configuration error. Please contact administrator.')
            return None, None, redirect('home')
        except Exception as e:
            messages.error(request, f'Database error: {str(e)}')
            return None, None, redirect('home')

        if role_name != 'admin':
            messages.error(request, 'Access denied. Admins only.')
            return None, None, redirect('home')

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
        role_id_raw = request.POST.get('role_id')
        form_values = {
            'first_name': first_name,
            'last_name': last_name,
            'username': username,
            'email': email,
            'role_id': role_id_raw or '',
        }

        if not first_name or not last_name or not username or not email or not role_id_raw:
            messages.error(request, 'All fields are required.')
            return self._render_form(request, current_user, role_name, roles, form_values)

        try:
            try:
                role_id = int(role_id_raw)
            except (TypeError, ValueError):
                role_id = role_id_raw

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

            # Insert into users profile table
            supabase.table('users').insert({
                'id': auth_user.id,
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'student_employee_id': username,
                'role_id': role_id,
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


@require_POST
def update_parking_slot_status(request, slot_id):
    if 'access_token' not in request.session:
        messages.error(request, 'Please log in first.')
        return redirect('signin', portal='student')

    try:
        current_user_id = request.session.get('user_id')
        user_response = supabase.table('users').select('role_id').eq('id', current_user_id).execute()
        if not user_response.data:
            messages.error(request, 'User not found.')
            return redirect('home')

        role_id = user_response.data[0]['role_id']
        role_resp = supabase.table('roles').select('role_name').eq('role_id', role_id).execute()
        role_name = role_resp.data[0]['role_name'] if role_resp.data else 'student'
    except Exception as e:
        messages.error(request, f'Database error: {str(e)}')
        return redirect('home')

    if role_name != 'admin':
        messages.error(request, 'Access denied. Admins only.')
        return redirect('home')

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
