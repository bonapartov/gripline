from django.urls import path
from . import views

app_name = 'demo'

urlpatterns = [
    path('login/<str:slot_type>/', views.demo_login, name='demo_login'),
]
