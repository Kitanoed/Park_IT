from django import forms

class RegisterForm(forms.Form):
    first_name = forms.CharField(max_length=100, label='First Name', required=True)
    last_name = forms.CharField(max_length=100, label='Last Name', required=True)
    email = forms.EmailField(label='Email', required=True)
    student_id = forms.CharField(max_length=20, label='Student/Employee ID', required=True)
    role = forms.ChoiceField(choices=[('student', 'Student'), ('faculty', 'Faculty'), ('admin', 'Admin')], label='Role', required=True)
    password1 = forms.CharField(widget=forms.PasswordInput, label='Password', required=True)
    password2 = forms.CharField(widget=forms.PasswordInput, label='Confirm Password', required=True)

class LoginForm(forms.Form):
    id = forms.CharField(max_length=20, label='Enter ID', required=True)
    password = forms.CharField(widget=forms.PasswordInput, label='Enter Password', required=True)