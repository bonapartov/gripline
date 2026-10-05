"""
Кладёт встроенный футер (website/templates/includes/footer_default.html) в сниппет CodeRed
«Footers» и подключает его к сайту — после этого весь футер правится в админке
(Сниппеты → Footers → блок «HTML»), без деплоя.

Запуск:
    python manage.py seed_footer            # создаёт сниппет «футер», если его нет или он пуст
    python manage.py seed_footer --force    # перезаписывает содержимое существующего сниппета

Ссылки, телефон и e-mail из Настроек организатора вставляются в HTML на момент запуска
(в сниппете шаблонные теги не работают) — дальше правятся прямо в блоке.
"""
from coderedcms.models import Footer, FooterOrderable, LayoutSettings
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from wagtail.models import Site

SNIPPET_NAME = 'футер'


class Command(BaseCommand):
    help = 'Кладёт встроенный футер в сниппет «Footers» и подключает его к сайту'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='перезаписать непустое содержимое')

    def handle(self, *args, **opts):
        html = render_to_string('includes/footer_default.html').strip()
        footer = Footer.objects.filter(name=SNIPPET_NAME).first() or Footer(name=SNIPPET_NAME)
        if footer.pk and footer.content and not opts['force']:
            self.stdout.write(self.style.WARNING(
                f'Сниппет «{SNIPPET_NAME}» уже содержит данные — ничего не меняю (--force перезапишет).'))
        else:
            footer.content = [('html', html)]
            footer.save()
            self.stdout.write(self.style.SUCCESS(f'Сниппет «{SNIPPET_NAME}» (id {footer.pk}) заполнен.'))

        site = Site.objects.get(is_default_site=True)
        layout = LayoutSettings.for_site(site)
        if not layout.site_footer.filter(footer=footer).exists():
            FooterOrderable.objects.create(footer=footer, footer_chooser=layout)
            self.stdout.write(self.style.SUCCESS('Футер подключён к сайту.'))
