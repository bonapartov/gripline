# Создайте файл debug_pages.py в корне проекта
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')
django.setup()

from website.models import ArticlePage, ArticleIndexPage, WebPage
from wagtail.models import Page

# Найдем страницу с slug "картинг"
try:
    page = Page.objects.get(slug='картинг')
    print(f"Найдена страница: {page.title}")
    print(f"URL: {page.url}")
    print(f"Тип: {page.content_type}")

    # Получим конкретный экземпляр
    specific = page.specific
    print(f"Конкретная модель: {specific.__class__.__name__}")
    print(f"Шаблон: {getattr(specific, 'template', 'Не указан')}")
except Page.DoesNotExist:
    print("Страница с slug 'картинг' не найдена")
    print("Все страницы:")
    for p in Page.objects.filter(depth__gt=2):
        print(f"- {p.title}: {p.url} (slug: {p.slug})")
