from django import forms
from django.core.exceptions import ValidationError

class RegisterForm(forms.Form):
    first_name = forms.CharField(max_length=100, label='First Name', required=True)
    last_name = forms.CharField(max_length=100, label='Last Name', required=True)
    email = forms.EmailField(label='Email', required=True)
    student_id = forms.CharField(max_length=20, label='Student/Employee ID', required=True)
    # Role selection removed - all new users default to "user" role
    password1 = forms.CharField(widget=forms.PasswordInput, label='Password', required=True)
    password2 = forms.CharField(widget=forms.PasswordInput, label='Confirm Password', required=True)

class LoginForm(forms.Form):
    id = forms.CharField(max_length=20, label='Enter ID', required=True)
    password = forms.CharField(widget=forms.PasswordInput, label='Enter Password', required=True)


class ChangePasswordForm(forms.Form):
    """Form for users to change their own password"""
    current_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'field-input'}),
        label='Current Password',
        required=True
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'field-input'}),
        label='New Password',
        required=True,
        min_length=8,
        help_text='Password must be at least 8 characters long.'
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'field-input'}),
        label='Confirm New Password',
        required=True
    )

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')

        if new_password and confirm_password:
            if new_password != confirm_password:
                raise ValidationError('New passwords do not match.')
        
        return cleaned_data


class AdminPasswordResetForm(forms.Form):
    """Form for admins to reset any user's password - generates secure temporary password"""
    # No password fields needed - password is generated automatically
    # This form is just for CSRF protection and confirmation
    confirm_reset = forms.BooleanField(
        required=False,
        widget=forms.HiddenInput(attrs={'value': 'true'}),
        initial=True
    )
    
    def clean(self):
        # Always valid - we just need CSRF protection
        return self.cleaned_data