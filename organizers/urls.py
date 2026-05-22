from django.urls import path
from . import views

app_name = 'organizers'

urlpatterns = [
    path("verify-email/<uidb64>/<token>/", views.organizer_verify_email, name="organizer_verify_email"),
    path("resend-verification/", views.organizer_resend_verification, name="organizer_resend_verification"),
    path("verification-sent/", views.organizer_verification_sent, name="organizer_verification_sent"),
    path("register/", views.organizer_register, name="register"),
    path("login/", views.organizer_login, name="login"),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('championship/create/', views.championship_create, name='championship_create'),
    path('championship/edit/<int:pk>/', views.championship_edit, name='championship_edit'),
    path('championship/delete/<int:pk>/', views.championship_delete, name='championship_delete'),
    path('stage/create/<int:championship_id>/', views.stage_create, name='stage_create'),
    path('stage/edit/<int:pk>/', views.stage_edit, name='stage_edit'),
    path('stage/delete/<int:pk>/', views.stage_delete, name='stage_delete'),
    path('stage/settings/<int:pk>/', views.stage_settings, name='stage_settings'),
    path('stage/<int:stage_id>/register/', views.stage_register, name='stage_register'),
    path('stage/<int:stage_id>/registrations/', views.stage_registrations, name='stage_registrations'),
    path('registration/<int:registration_id>/cancel/', views.registration_cancel, name='registration_cancel'),
    path('registration/<int:registration_id>/action/', views.registration_action, name='registration_action'),
    path('stage/<int:stage_id>/numbers/', views.stage_numbers, name='stage_numbers'),
    path('stage/<int:stage_id>/numbers/reassign/', views.reassign_number, name='reassign_number'),
]
