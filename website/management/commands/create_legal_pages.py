"""
Создаёт/обновляет правовые страницы сайта:

    /legal/                Правовая информация (оглавление)
    /legal/privacy/        Политика в отношении обработки персональных данных
    /legal/terms/          Пользовательское соглашение

Тексты лежат в website/legal_pages/*.html с плейсхолдерами {{OPERATOR}}, {{TG}},
{{DATE}} — ФИО оператора и Telegram подставляются при запуске, в репозитории их нет
(это персональные данные оператора, хранить в git их незачем).

Запуск:
    python manage.py create_legal_pages --operator "Фамилия Имя Отчество" --tg "@username"
    ... --publish      # опубликовать (без флага страницы создаются/обновляются как ЧЕРНОВИКИ)

Идемпотентна: повторный запуск обновляет текст существующих страниц (новая ревизия) и
дату «последнего обновления», дубликатов не создаёт. Форма обращения
(/legal/data-request/) — не Wagtail-страница, а обычный Django-view (website/legal_views.py).

Почему команда, а не data-migration: операции с деревом Wagtail-страниц через
frozen-модели миграций (treebeard path/depth/numchild) — известный источник
проблем с целостностью дерева, Wagtail сам так делать не рекомендует.

Также ставит постоянный редирект /privacy-policy/ → /legal/privacy/ (старый адрес
политики; на нём остались ссылки у внешних источников и в старых письмах).
"""
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from wagtail.contrib.redirects.models import Redirect
from wagtail.models import Site

from website.models import WebPage

LEGAL_DIR = Path(__file__).resolve().parents[2] / "legal_pages"

PAGES = [
    ("Политика в отношении обработки персональных данных", "privacy", "privacy.html"),
    ("Пользовательское соглашение", "terms", "terms.html"),
]

# Только токены --gl-*, без hex (DESIGN_SYSTEM.md).
STYLE = """<style>
  .gl-legal { max-width: 860px; margin: 2rem auto; padding: 0 1rem; }
  .gl-legal h1 { margin-bottom: 0.5rem; }
  .gl-legal h2 { margin-top: 2.5rem; margin-bottom: 1rem; }
  .gl-legal p, .gl-legal li { color: var(--gl-fg-3); line-height: 1.6; }
  .gl-legal ul { padding-left: 1.25rem; }
  .gl-legal a { color: var(--gl-brand-cyan); }
</style>"""


def wrap(title, inner):
    return f'{STYLE}\n<div class="gl-legal">\n<h1>{title}</h1>\n{inner}\n</div>'


class Command(BaseCommand):
    help = "Создаёт/обновляет /legal/, /legal/privacy/, /legal/terms/ (идемпотентно)"

    def add_arguments(self, p):
        p.add_argument("--operator", required=True, help="ФИО оператора персональных данных")
        p.add_argument("--tg", required=True, help="Telegram оператора, например @username")
        p.add_argument("--publish", action="store_true", help="опубликовать (по умолчанию — черновик)")

    def _upsert(self, parent, title, slug, html, publish):
        existing = parent.get_children().filter(slug=slug).first()
        body = [("html", html)]
        if existing:
            page = existing.specific
            page.title = title
            page.body = body
        else:
            page = WebPage(title=title, slug=slug, body=body, live=publish)
            parent.add_child(instance=page)
        revision = page.save_revision()
        if publish:
            revision.publish()
        return page

    def handle(self, *args, **o):
        replacements = {
            "{{OPERATOR}}": o["operator"],
            "{{TG}}": o["tg"],
            "{{DATE}}": date.today().strftime("%d.%m.%Y"),
        }
        publish = o["publish"]
        root = Site.objects.get(is_default_site=True).root_page

        docs = []
        for title, slug, fname in PAGES:
            html = (LEGAL_DIR / fname).read_text(encoding="utf-8")
            for k, v in replacements.items():
                html = html.replace(k, v)
            if "{{" in html:
                raise CommandError(f"В {fname} остались незаменённые плейсхолдеры")
            docs.append((title, slug, html))

        index_html = "<ul>\n" + "\n".join(
            f'<li><a href="/legal/{slug}/">{title}</a></li>' for title, slug, _ in docs
        ) + '\n<li><a href="/legal/data-request/">Обращение по персональным данным</a></li>\n</ul>'

        parent = self._upsert(root, "Правовая информация", "legal", wrap("Правовая информация", index_html), publish)
        self.stdout.write(self.style.SUCCESS(f"legal: готово ({'опубликована' if publish else 'черновик'})"))

        for title, slug, html in docs:
            self._upsert(parent, title, slug, wrap(title, html), publish)
            self.stdout.write(self.style.SUCCESS(f"legal/{slug}: готово ({'опубликована' if publish else 'черновик'})"))

        Redirect.objects.update_or_create(
            old_path=Redirect.normalise_path("/privacy-policy/"),
            site=None,
            defaults={"is_permanent": True, "redirect_link": "/legal/privacy/", "redirect_page": None},
        )
        self.stdout.write(self.style.SUCCESS("redirect /privacy-policy/ → /legal/privacy/: готово"))
