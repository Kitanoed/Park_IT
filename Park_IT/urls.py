from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path
from .views import (
    HomeView, RegisterView, LoginView, logout_view,
    SignInView, DashboardView, ParkingSpacesView, ManageUsersView, UserDashboardView,
    EditUserView, deactivate_user, activate_user, AddUserView, update_parking_slot_status,
    UserParkingSpacesView, UnifiedLoginView, update_user_role, AdminParkingHistoryView,
    parking_history_api, ProfileForUsersView, reset_user_password, ChangePasswordView,
    AdminResetPasswordView, handle_check_in, handle_check_out, get_slot_details,
    AdvancedReportsView, export_parking_csv, monthly_report_api,
)

urlpatterns = [
    path('django-admin/', admin.site.urls),  # Django admin (moved to avoid conflict)
    path('', HomeView.as_view(), name='home'),
    path('register/', RegisterView.as_view(), name='register'),
    # Unified login routes
    path('login/', UnifiedLoginView.as_view(), name='login'),
    path('sign-in/', UnifiedLoginView.as_view(), name='sign-in'),  # Alias
    # Legacy routes (redirect to unified login)
    path('signin/', SignInView.as_view(), name='signIn'),
    path('signin/<str:portal>/', LoginView.as_view(), name='signin'),
    path('logout/', logout_view, name='logout'),
    # Admin dashboard (protected by middleware) - redirects /admin to dashboard
    path('admin/', DashboardView.as_view(), name='dashboard'),
    # User/Attendant dashboard
    path('users/attendant/', UserDashboardView.as_view(), name='user_dashboard'),
    path('user-dashboard/', UserDashboardView.as_view(), name='user_dashboard_legacy'),  # Legacy alias
    # User profile
    path('profile/', ProfileForUsersView.as_view(), name='profile_for_users'),
    path('profile/', ProfileForUsersView.as_view(), name='user_profile'),  # Alias for template compatibility
    path('profile/update/', ProfileForUsersView.as_view(), name='update_profile'),  # Alias for profile update form
    path('profile/change-password/', ChangePasswordView.as_view(), name='change_password'),
    # Parking spaces
    path('parking-spaces/', ParkingSpacesView.as_view(), name='parking_spaces'),
    path('user/parking-spaces/', UserParkingSpacesView.as_view(), name='user_parking_spaces'),
    path('student/parking-spaces/', UserParkingSpacesView.as_view(), name='stud_parking_spaces'),  # Legacy alias for backward compatibility
    path('parking-slots/<int:slot_id>/status/', update_parking_slot_status, name='update_slot_status'),
    # User management (admin only)
    path("manage-users/", ManageUsersView.as_view(), name="manage_users"),
    path("manage-users/add/", AddUserView.as_view(), name="add_user"),
    path("manage-users/<str:user_id>/edit/", EditUserView.as_view(), name="edit_user"),
    path("manage-users/<str:user_id>/deactivate/", deactivate_user, name="deactivate_user"),
    path("manage-users/<str:user_id>/activate/", activate_user, name="activate_user"),
    path("manage-users/<str:user_id>/reset-password/", AdminResetPasswordView.as_view(), name="admin_reset_password"),
    path("manage-users/reset-password/", reset_user_password, name="reset_user_password"),  # Legacy endpoint
    # Admin parking history (admin only)
    path("admin/parking-history/", AdminParkingHistoryView.as_view(), name="admin_parking_history"),
    # Advanced Reports (admin only)
    path("admin/reports/", AdvancedReportsView.as_view(), name="advanced_reports"),
    # Admin API endpoints
    path("api/admin/parking/history/", parking_history_api, name="parking_history_api"),
    path("api/admin/reports/export-csv/", export_parking_csv, name="export_parking_csv"),
    path("api/admin/reports/monthly/", monthly_report_api, name="monthly_report_api"),
    path("api/admin/users/<str:user_id>/role/", update_user_role, name="update_user_role"),
    # Parking slot check-in/check-out endpoints
    path("api/parking-slots/<int:slot_id>/check-in/", handle_check_in, name="check_in"),
    path("api/parking-slots/<int:slot_id>/check-out/", handle_check_out, name="check_out"),
    path("api/parking-slots/<int:slot_id>/details/", get_slot_details, name="slot_details"),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])