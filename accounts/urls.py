from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path("favorite-ads/", views.favorite_ads, name="favorite_ads"),
    path("my-responses/", views.my_responses, name="my_responses"),
    path("ad-responses/<int:ad_id>/", views.ad_responses, name="ad_responses"),
    path("response-action/<int:response_id>/<str:action>/", views.response_action, name="response_action"),
    path('register/', views.register, name='register'),
    path('select-driver/', views.select_driver, name='select_driver'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile, name='profile'),
    path('api/process-claim/', views.process_claim_api, name='process_claim_api'),
    path('documents/upload/', views.upload_pilot_document, name='upload_pilot_document'),
    path('documents/<int:doc_id>/delete/', views.delete_pilot_document, name='delete_pilot_document'),
    
    # Email verification
    path('verify-email/<uidb64>/<token>/', views.verify_email, name='verify_email'),
    path('resend-verification/', views.resend_verification, name='resend_verification'),
    path('verification-sent/', views.verification_sent, name='verification_sent'),

    # Public search API (used by choose-role page and onboarding)
    path('api/drivers-search/', views.yandex_search_drivers, name='drivers_search'),
    path('api/teams-search/', views.yandex_search_teams, name='teams_search'),

    # Yandex OAuth (legacy thin wrapper → social:begin; callback handled by social_django)
    path('yandex/login/', views.yandex_login, name='yandex_login'),
    path('yandex/onboarding/pilot/', views.yandex_pilot_onboarding, name='yandex_pilot_onboarding'),
    path('yandex/onboarding/team/', views.yandex_team_onboarding, name='yandex_team_onboarding'),
    path('yandex/onboarding/organizer/', views.yandex_organizer_onboarding, name='yandex_organizer_onboarding'),
    path('yandex/role-switch/', views.yandex_role_switch, name='yandex_role_switch'),
    path('yandex/search-drivers/', views.yandex_search_drivers, name='yandex_search_drivers'),
    path('yandex/search-teams/', views.yandex_search_teams, name='yandex_search_teams'),
]
