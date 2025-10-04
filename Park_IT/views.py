from django.shortcuts import render
from django.http import HttpRequest, HttpResponse


def home(request: HttpRequest) -> HttpResponse:
    return render(request, 'signIn.html')


def signin_student(request: HttpRequest) -> HttpResponse:
    return render(request, 'signin_student.html')


def signin_admin(request: HttpRequest) -> HttpResponse:
    return render(request, 'signin_admin.html')



