from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path
from .views import (
    HomeView, RegisterView, LoginView, logout_view,
    SignInView, DashboardView, ParkingSpacesView, ManageUsersView, UserDashboardView,
    EditUserView, deactivate_user, activate_user, AddUserView, update_parking_slot_status,
    UserParkingSpacesView, UnifiedLoginView, update_user_role, AdminParkingHistoryView,
    parking_history_api, ProfileForUsersView, reset_user_password,
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
    path('profile/change-password/', ProfileForUsersView.as_view(), name='change_password'),  # Alias for password change form
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
    path("manage-users/reset-password/", reset_user_password, name="reset_user_password"),
    # Admin parking history (admin only)
    path("admin/parking-history/", AdminParkingHistoryView.as_view(), name="admin_parking_history"),
    # Admin API endpoints
    path("api/admin/parking/history/", parking_history_api, name="parking_history_api"),
    path("api/admin/users/<str:user_id>/role/", update_user_role, name="update_user_role"),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])