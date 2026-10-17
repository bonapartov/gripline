from django.urls import path

from . import api, auth

urlpatterns = [
    path('config/', api.config, name='setupkart_api_config'),
    path('catalog/', api.catalog, name='setupkart_api_catalog'),
    path('tracks/', api.tracks, name='setupkart_api_tracks'),
    path('suggestions/', api.suggestions, name='setupkart_api_suggestions'),
    path('feedback/', api.feedback, name='setupkart_api_feedback'),
    path('diagnostics/', api.diagnostics, name='setupkart_api_diagnostics'),
    path('trial/', api.trial, name='setupkart_api_trial'),
    path('auth/start/', auth.start, name='setupkart_auth_start'),
    path('auth/complete/', auth.complete, name='setupkart_auth_complete'),
    path('auth/exchange/', auth.exchange, name='setupkart_auth_exchange'),
    path('auth/me/', auth.me, name='setupkart_auth_me'),
    path('auth/logout/', auth.logout, name='setupkart_auth_logout'),
    path('auth/devices/<int:token_id>/revoke/', auth.revoke_device, name='setupkart_auth_revoke'),
]
