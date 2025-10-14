# Park_IT/Park_IT/urls.py
from django.contrib import admin
from django.urls import path
from .views import HomeView, RegisterView, LoginView, logout_view, SignInView, DashboardView
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', HomeView.as_view(), name='home'),
    path('register/', RegisterView.as_view(), name='register'),
    path('signin/', SignInView.as_view(), name='signIn'),  # Direct route for sign-in selection
    path('signin/<str:portal>/', LoginView.as_view(), name='signin'),  # Dynamic portal route
    path('logout/', logout_view, name='logout'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
]