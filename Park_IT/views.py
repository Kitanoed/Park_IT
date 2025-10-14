from django.shortcuts import render
from django.http import HttpRequest, HttpResponse


def home(request: HttpRequest) -> HttpResponse:
    return render(request, 'home.html')

def sign_in(request: HttpRequest) -> HttpResponse:
    return render(request, 'signIn.html')

def register(request: HttpRequest) -> HttpResponse:
    return render(request, 'register.html')


def signin_student(request: HttpRequest) -> HttpResponse:
    return render(request, 'signin_student.html')


def signin_admin(request: HttpRequest) -> HttpResponse:
    return render(request, 'signin_admin.html')



