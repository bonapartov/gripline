from django.urls import path
from . import views

app_name = 'teams'

urlpatterns = [
    path('register/', views.register, name='register'),
    path('select-team/', views.select_team, name='select_team'),
    path('login/', views.login_view, name='login'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('add-driver/', views.add_driver, name='add_driver'),
    path('invite-driver/', views.invite_driver, name='invite_driver'),
    path('invitation/<int:inv_id>/accept/', views.accept_invitation, name='accept_invitation'),
    path('invitation/<int:inv_id>/decline/', views.decline_invitation, name='decline_invitation'),
    path('remove-driver/<int:driver_id>/', views.remove_driver, name='remove_driver'),
    path('approve-request/<int:request_id>/', views.approve_request, name='approve_request'),
    path('reject-request/<int:request_id>/', views.reject_request, name='reject_request'),
    path('logout/', views.logout_view, name='logout'),
    path('add-staff/', views.add_staff, name='add_staff'),
    path('remove-staff/<int:staff_id>/', views.remove_staff, name='remove_staff'),
    path('edit-staff/<int:staff_id>/', views.edit_staff, name='edit_staff'),
    
    path('join/<slug:team_slug>/', views.join_team, name='join_team'),

    # Регистрация пилота на этап от имени команды
    path('apply/<int:stage_id>/', views.team_apply, name='team_apply'),
    path('apply/<int:stage_id>/add-driver/', views.team_add_driver, name='team_add_driver'),
    path('apply/driver-search/', views.team_driver_search, name='team_driver_search'),

    # Email verification
    path('verify-email/<uidb64>/<token>/', views.team_verify_email, name='team_verify_email'),
    path('resend-verification/', views.team_resend_verification, name='team_resend_verification'),
    path('verification-sent/', views.team_verification_sent, name='team_verification_sent'),
]
