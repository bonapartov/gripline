from coderedcms import admin_urls as crx_admin_urls
from coderedcms import search_urls as crx_search_urls
from coderedcms import urls as crx_urls
from django.conf import settings
from django.contrib import admin
from django.urls import include
from django.urls import path
from wagtail.documents import urls as wagtaildocs_urls
from website.views import staff_detail_view, staff_api

urlpatterns = [
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
    path("", include("coderedcms.urls")),  # Wagtail в самом конце
]

# fmt: off
if settings.DEBUG:
    from django.conf.urls.static import static

    # Serve static and media files from development server
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)  # type: ignore
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)  # type: ignore
# fmt: on
