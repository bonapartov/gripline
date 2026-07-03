from django.contrib import admin
from django.urls import include, path, reverse_lazy
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from django.contrib.auth import views as auth_views
from website.models import Driver, Chassis, RaceResult, Track
from website.views import staff_detail_view, staff_api
from website.views import rating_stats_api
from demo.views import choose_role
from accounts.views import vk_id_redirect_landing

# Функция для API статистики
def stats_api(request):
    data = {
        'pilots': Driver.objects.filter(live=True).count(),
        'chassis': Chassis.objects.filter(live=True).count(),
        'races': RaceResult.objects.values('group__page').distinct().count(),
        'tracks': Track.objects.filter(live=True).count(),
    }
    return JsonResponse(data)
    
urlpatterns = [
    # Перехват redirectUrl VK ID SDK ДО social_django — обмен code на
    # access_token для «узнанной» VK-сессии довершается в браузере,
    # а не через классический server-side complete-view python-social-auth.
    path('auth/complete/vk-id/', vk_id_redirect_landing, name='vk_id_redirect_landing'),
    path('auth/', include('social_django.urls', namespace='social')),
    path('api/stats/', stats_api, name='stats_api'),
    path('api/rating-stats/', rating_stats_api, name='rating_stats_api'),
    path('organizers/', include('organizers.urls')),
    path('applications/', include('applications.urls')),
    path('demo/', include('demo.urls')),
    path('choose-role/', choose_role, name='choose_role'),
    path("django-admin/", admin.site.urls),

    # accounts URLS - САМЫЕ ПЕРВЫЕ, ДО ВСЕГО
    path('accounts/', include('accounts.urls')),

    # ВАЖНО: Используем СТРОКИ в include, чтобы избежать ранней загрузки
    path("admin/", include("coderedcms.admin_urls")),

    path('teams/', include('teams.urls')),

    # API пути
    path('api/staff/<int:staff_id>/', staff_api, name='staff_api'),

    # СТРАНИЦЫ СОТРУДНИКОВ - прямой путь
    path('staff/<slug:slug>/', staff_detail_view, name='staff_detail'),

    # Подключаем маршруты через строку
    path("", include("website.urls")),

    path("docs/", include("wagtail.documents.urls")),
    path("search/", include("coderedcms.search_urls")),
    path('accounts/password-reset/', auth_views.PasswordResetView.as_view(
        email_template_name='registration/password_reset_email.txt',
        html_email_template_name='registration/password_reset_email.html',
    ), name='password_reset'),
    path('accounts/password-reset/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('accounts/password-reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        post_reset_login=True,
        success_url=reverse_lazy('accounts:profile'),
    ), name='password_reset_confirm'),
    path('accounts/password-reset/complete/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
    path("", include("coderedcms.urls")),  # Wagtail в самом конце
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
