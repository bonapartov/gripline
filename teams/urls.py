from django.urls import path
from . import views

app_name = 'teams'

urlpatterns = [
    path('register/', views.register, name='register'),
    path('select-team/', views.select_team, name='select_team'),
    path('login/', views.login_view, name='login'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('add-driver/', views.add_driver, name='add_driver'),
    path('remove-driver/<int:driver_id>/', views.remove_driver, name='remove_driver'),
    path('approve-request/<int:request_id>/', views.approve_request, name='approve_request'),
    path('reject-request/<int:request_id>/', views.reject_request, name='reject_request'),
    path('logout/', views.logout_view, name='logout'),
    path('add-staff/', views.add_staff, name='add_staff'),
    path('remove-staff/<int:staff_id>/', views.remove_staff, name='remove_staff'),
    path('edit-staff/<int:staff_id>/', views.edit_staff, name='edit_staff'),
]
