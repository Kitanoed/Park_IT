# Park_IT/Park_IT/urls.py
from django.contrib import admin
from django.urls import path
from .views import HomeView, RegisterView, LoginView, logout_view, SignInView, DashboardView, ParkingSpacesView, \
    ManageUsersView
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', HomeView.as_view(), name='home'),
    path('register/', RegisterView.as_view(), name='register'),
    path('signin/', SignInView.as_view(), name='signIn'),
    path('signin/<str:portal>/', LoginView.as_view(), name='signin'),
    path('logout/', logout_view, name='logout'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('parking-spaces/', ParkingSpacesView.as_view(), name='parking_spaces'),
    path("manage-users/", ManageUsersView.as_view(), name="manage_users"),
]
