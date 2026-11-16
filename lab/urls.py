from django.urls import path

from . import views

app_name = 'lab'

urlpatterns = [
    path('search/', views.lab_search, name='search'),
]
