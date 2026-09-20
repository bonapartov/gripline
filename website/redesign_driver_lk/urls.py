from django.urls import path

from .views import driver_detail_v2_view

urlpatterns = [
    path("<slug:slug>/", driver_detail_v2_view, name="details_v2"),
]
