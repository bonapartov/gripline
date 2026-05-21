from django.urls import path
from . import views

app_name = 'applications'

urlpatterns = [
    path('apply/<int:stage_id>/', views.apply, name='apply'),
    path('apply/<int:stage_id>/numbers/', views.available_numbers_api, name='available_numbers'),
    path('<int:application_id>/', views.detail, name='detail'),
    path('<int:application_id>/cancel/', views.cancel, name='cancel'),
    path('<int:application_id>/submit/', views.submit_application, name='submit'),
    path('<int:application_id>/pay/', views.upload_payment, name='upload_payment'),
    path('document/<int:document_id>/upload/', views.upload_document, name='upload_document'),

    # Действия организатора
    path('<int:application_id>/action/', views.org_action, name='org_action'),
    path('<int:application_id>/verify-payment/', views.org_verify_payment, name='org_verify_payment'),
    path('document/<int:document_id>/verify/', views.org_verify_document, name='org_verify_document'),
]
