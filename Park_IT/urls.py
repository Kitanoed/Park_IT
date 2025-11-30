from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path
from .views import (
    HomeView, RegisterView, LoginView, logout_view,
    SignInView, DashboardView, ParkingSpacesView, ManageUsersView, UserDashboardView,
    EditUserView, deactivate_user, activate_user, AddUserView, update_parking_slot_status,
    StudentParkingSpacesView, UnifiedLoginView, update_user_role, AdminParkingHistoryView,
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
    # Parking spaces
    path('parking-spaces/', ParkingSpacesView.as_view(), name='parking_spaces'),
    path('student/parking-spaces/', StudentParkingSpacesView.as_view(), name='stud_parking_spaces'),
    path('parking-slots/<int:slot_id>/status/', update_parking_slot_status, name='update_slot_status'),
    # User management (admin only)
    path("manage-users/", ManageUsersView.as_view(), name="manage_users"),
    path("manage-users/add/", AddUserView.as_view(), name="add_user"),
    path("manage-users/<str:user_id>/edit/", EditUserView.as_view(), name="edit_user"),
    path("manage-users/<str:user_id>/deactivate/", deactivate_user, name="deactivate_user"),
    path("manage-users/<str:user_id>/activate/", activate_user, name="activate_user"),
    # Admin parking history (admin only)
    path("admin/parking-history/", AdminParkingHistoryView.as_view(), name="admin_parking_history"),
    # Admin API endpoint for role management
    path("api/admin/users/<str:user_id>/role/", update_user_role, name="update_user_role"),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])