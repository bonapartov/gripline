from django.urls import path
from . import balance_views

app_name = "balance"

urlpatterns = [
    path("", balance_views.balance_home, name="home"),
    path("manifest.json", balance_views.balance_manifest, name="manifest"),
    path("sw.js", balance_views.balance_service_worker, name="service_worker"),
]
