from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("django-admin/", admin.site.urls),

    # ВАЖНО: Используем СТРОКИ в include, чтобы избежать ранней загрузки
    path("admin/", include("coderedcms.admin_urls")),

    # Подключаем ваши маршруты через строку
    path("", include("website.urls")),

    path("docs/", include("wagtail.documents.urls")),
    path("search/", include("coderedcms.search_urls")),
    path("", include("coderedcms.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
