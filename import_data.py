import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gripline.settings.dev')
django.setup()

from wagtail.models import Page
from website.models import Driver, Track
from django.utils.text import slugify

def run_import():
    d_parent = Page.objects.get(slug='drivers')
    t_parent = Page.objects.get(slug='tracks')

    with open('website_data.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    print("Начинаем жесткую запись в базу...")

    for item in data:
        fields = item.get('fields', {})
        slug = fields.get('slug') or slugify(fields.get('title', 'page'))
        
        if item['model'] == 'website.driver':
            if not Driver.objects.filter(slug=slug).exists():
                # Создаем объект вручную
                obj = Driver()
                obj.title = fields.get('title') or f"{fields.get('first_name', '')} {fields.get('last_name', '')}".strip()
                obj.slug = slug
                obj.first_name = fields.get('first_name', '')
                obj.last_name = fields.get('last_name', '')
                obj.live = True
                obj.depth = d_parent.depth + 1
                # Генерируем временный путь, который fix_tree потом заменит
                obj.path = d_parent.path + "9999" 
                obj.save() # Обычный сейв без add_child
                print(f"📦 Сброшен в базу: {obj.title}")

        elif item['model'] == 'website.track':
            if not Track.objects.filter(slug=slug).exists():
                obj = Track()
                obj.title = fields.get('title') or fields.get('name') or slug
                obj.slug = slug
                obj.address = fields.get('address', '')
                obj.live = True
                obj.depth = t_parent.depth + 1
                obj.path = t_parent.path + "9999"
                obj.save()
                print(f"📦 Сброшена трасса: {obj.title}")

    print("\n🛠 КРИТИЧЕСКИЙ МОМЕНТ: Принудительное восстановление дерева...")
    Page.fix_tree()
    print("🚀 Всё! Теперь иди в админку и проверяй.")

if __name__ == "__main__":
    run_import()
