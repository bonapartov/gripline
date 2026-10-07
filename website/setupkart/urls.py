from django.urls import path

from . import api

urlpatterns = [
    path('catalog/', api.catalog, name='setupkart_api_catalog'),
    path('tracks/', api.tracks, name='setupkart_api_tracks'),
    path('suggestions/', api.suggestions, name='setupkart_api_suggestions'),
    path('feedback/', api.feedback, name='setupkart_api_feedback'),
]
