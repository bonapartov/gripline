from django.urls import path
from . import views

app_name = 'applications'

urlpatterns = [
    path('apply/<int:stage_id>/', views.apply, name='apply'),
    path('<int:application_id>/', views.detail, name='detail'),
    path('<int:application_id>/cancel/', views.cancel, name='cancel'),
    path('<int:application_id>/pay/', views.upload_payment, name='upload_payment'),
    path('document/<int:document_id>/upload/', views.upload_document, name='upload_document'),
]
