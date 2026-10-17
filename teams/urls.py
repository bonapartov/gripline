from django.urls import path
from applications import team_wizard

from . import views

app_name = 'teams'

urlpatterns = [
    path('register/', views.register, name='register'),
    path('select-team/', views.select_team, name='select_team'),
    path('login/', views.login_view, name='login'),
    path('dashboard/', views.dashboard, name='dashboard'),
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

    # Заявка команды на этап: несколько пилотов, разные классы (applications/team_wizard.py)
    path('apply/<int:stage_id>/', team_wizard.start, name='team_apply'),
    path('apply/entry/<int:entry_id>/', team_wizard.roster, name='team_entry'),
    path('apply/entry/<int:entry_id>/add-pilot/', team_wizard.add_pilot, name='team_entry_add_pilot'),
    path('apply/entry/<int:entry_id>/pilots/', team_wizard.pilots, name='team_entry_pilots'),
    path('apply/entry/<int:entry_id>/pilots/<int:application_id>/', team_wizard.pilot, name='team_entry_pilot'),
    path('apply/entry/<int:entry_id>/review/', team_wizard.review, name='team_entry_review'),
    path('apply/driver-search/', views.team_driver_search, name='team_driver_search'),

    # Email verification
    path('verify-email/<uidb64>/<token>/', views.team_verify_email, name='team_verify_email'),
    path('resend-verification/', views.team_resend_verification, name='team_resend_verification'),
    path('verification-sent/', views.team_verification_sent, name='team_verification_sent'),
]
