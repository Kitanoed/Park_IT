"""
Middleware for role-based access control (RBAC).
Protects /admin/* routes to ensure only users with "admin" role can access them.
"""
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import resolve
from utils import supabase


class RoleBasedAccessControlMiddleware:
    """
    Middleware that enforces role-based access control.
    All routes under /admin/* require the authenticated user to have role="admin".
    """
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip Django admin routes (moved to /django-admin/)
        if request.path.startswith('/django-admin/'):
            response = self.get_response(request)
            return response
        
        # Check if the request path starts with /admin/ (app admin routes)
        if request.path.startswith('/admin/'):
            # Check session-based authentication
            if 'access_token' not in request.session or 'user_id' not in request.session:
                messages.error(request, 'Please log in to access this page.')
                return redirect('login')
            
            # Verify user role
            try:
                user_id = request.session.get('user_id')
                user_response = supabase.table('users').select('role').eq('id', user_id).execute()
                
                if not user_response.data:
                    messages.error(request, 'User not found.')
                    request.session.flush()
                    return redirect('login')
                
                user_role = user_response.data[0].get('role', 'user')
                
                # Only allow "admin" role to access /admin/* routes
                if user_role != 'admin':
                    messages.error(request, 'Access denied. Admin privileges required.')
                    return redirect('user_dashboard')
                    
            except Exception as e:
                messages.error(request, f'Error verifying access: {str(e)}')
                return redirect('login')
        
        response = self.get_response(request)
        return response

