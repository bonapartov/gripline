"""Страницы Wagtail: статьи, события, чемпионаты, архивы."""

from django.contrib.auth.models import User
from coderedcms.forms import CoderedFormField
from coderedcms.models import (
    CoderedArticleIndexPage, CoderedArticlePage, CoderedEmail,
    CoderedEventIndexPage, CoderedEventOccurrence, CoderedEventPage,
    CoderedFormPage, CoderedLocationIndexPage, CoderedLocationPage,
    CoderedWebPage)
from modelcluster.fields import ParentalKey, ParentalManyToManyField
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from modelcluster.models import ClusterableModel
from wagtail.api import APIField
from wagtail.snippets.models import register_snippet
from wagtail.admin.panels import FieldPanel, FieldRowPanel, HelpPanel, InlinePanel, MultiFieldPanel, ObjectList, Panel, TabbedInterface
from wagtail.admin.forms.pages import WagtailAdminPageForm
from wagtail.models import DraftStateMixin, RevisionMixin, PreviewableMixin, Orderable
from django.urls import reverse
from django.utils.text import slugify
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned, ValidationError
from unidecode import unidecode
import datetime
from wagtail.models import Page
from django.db.models import Count, Q
from django import forms
from datetime import timedelta
from zoneinfo import ZoneInfo
from django.http import HttpResponse
from wagtail.fields import StreamField
from coderedcms.blocks import CONTENT_STREAMBLOCKS
from coderedcms.blocks.html_blocks import RichTextBlock as CrxRichTextBlock
from wagtailmarkdown.blocks import MarkdownBlock
from django.utils.html import format_html, format_html_join
from wagtailseo.models import SeoType

from .people import Driver
from .site_settings import SocialTag


# ---------- СТРАНИЦЫ (PAGES) ----------

class TransliteratedSlugMixin:
    """Транслитерирует slug в ASCII, пока страница ещё не опубликована.

    Wagtail по умолчанию (WAGTAIL_ALLOW_UNICODE_SLUGS) разрешает кириллицу в
    slug и автозаполняет его из заголовка как есть — из-за этого URL
    превращается в percent-encoded кашу при копировании ссылки или в
    анонсах в соцсети (Telegram/MAX/VK). Остальные модели проекта (Driver,
    Team, RaceClass, Brand) уже транслитерируют через unidecode — приводим
    страницы к тому же виду.

    Обязательно ПЕРВЫЙ в списке родителей, перед CoderedXxxPage/Page:
    Page.save() сам вызывает set_url_path() (считает url_path по текущему
    slug) до super().save() — если транслитерировать slug сигналом
    pre_save (который сработает уже внутри super().save()), url_path
    останется старым, кириллическим, несмотря на то что сам slug в базе
    станет ASCII. Меняя slug здесь, до вызова super().save(), успеваем до
    того, как Page.save() посчитает url_path.

    Проверка `self.pk is None` (только первый save) не годится: экран
    «Новая страница» в Wagtail 7.3 создаёт запись в БД сразу по мере ввода
    заголовка (autosave/hydrate-flow) — на этом этапе title ещё неполный.
    Полный заголовок и итоговый slug приходят позже, уже через EditView, у
    страницы к этому моменту уже есть pk — старая проверка такие сохранения
    пропускала, и кириллический slug из клиентского JS уходил в базу как
    есть. Используем `not self.first_published_at` — срабатывает на любом
    save черновика (сколько бы их ни было), но не трогает уже
    опубликованные страницы, чтобы не ломать расшаренные внешние ссылки.
    """
    def save(self, *args, **kwargs):
        if not self.first_published_at and self.slug:
            try:
                self.slug.encode('ascii')
            except UnicodeEncodeError:
                transliterated = slugify(unidecode(self.slug))
                if transliterated:
                    self.slug = transliterated
        super().save(*args, **kwargs)


class ArticlePageForm(WagtailAdminPageForm):
    """Мультиселект social_extra_tags должен показывать только теги,
    которые ещё не применяются автоматически (без раздела или с разделом,
    совпадающим с фактическим родителем статьи) — иначе редактор может
    выбрать тег, который и так уже будет опубликован."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields.get('social_extra_tags')
        if field is None:
            return

        parent = self.parent_page or (self.instance.get_parent() if self.instance.pk else None)
        auto_tags_filter = models.Q(parent_page__isnull=True)
        if parent is not None:
            auto_tags_filter |= models.Q(parent_page_id=parent.id)
        auto_tag_ids = SocialTag.objects.filter(auto_tags_filter).values_list('pk', flat=True)
        field.queryset = SocialTag.objects.exclude(pk__in=auto_tag_ids)


def _article_body_streamblocks():
    """CONTENT_STREAMBLOCKS с локальной копией блока "text": добавляет
    pilot_mention/team_mention (см. website/wagtail_hooks.py) только для
    ArticlePage.body — CONTENT_STREAMBLOCKS общий объект для всех типов
    страниц проекта, менять его напрямую включило бы автокомплит пилотов/
    команд в rich text везде, а не только в статьях.

    Список стандартных фич захардкожен, а не взят через
    wagtail.rich_text.features.get_default_features() — тот вызов на этапе
    импорта website/models.py триггерит сканирование wagtail_hooks.py по
    всем приложениям, а organizers/wagtail_hooks.py -> organizers/models.py
    импортирует обратно website.models, который в этот момент ещё сам не
    доимпортировался (circular import). Значения сверены вручную через
    `wagtail.rich_text.features.get_default_features()` в shell — при
    обновлении Wagtail/coderedcms проверить, что список не разошёлся.
    """
    features = [
        "embed", "hr", "link", "bold", "italic", "h2", "h3", "h4",
        "ol", "ul", "document-link", "image",
    ] + ["pilot_mention", "team_mention"]
    result = []
    for name, block in CONTENT_STREAMBLOCKS:
        if name == "text":
            result.append(("text", CrxRichTextBlock(icon="cr-font", features=features)))
        else:
            result.append((name, block))
    return result


class ArticlePage(TransliteratedSlugMixin, CoderedArticlePage):
    class Meta:
        verbose_name = "Article"
        ordering = ["-first_published_at"]
    parent_page_types = ["website.ArticleIndexPage", "website.TechArticleIndexPage"]
    template = "coderedcms/pages/article_page.html"

    # Включает генерацию Article-разметки в wagtailseo (seo_struct_article_dict),
    # см. seo_og_type в SeoMixin.
    seo_content_type = SeoType.ARTICLE

    # Соответствие термина классификатора "Уровень" значению TechArticle.proficiencyLevel.
    SEO_PROFICIENCY_LEVEL_MAP = {
        "Базовый": "Beginner",
        "Средний": "Intermediate",
        "Продвинутый": "Advanced",
    }

    @property
    def seo_struct_article_dict(self) -> dict:
        """
        Достраивает Article-разметку от wagtailseo: TechArticle для Матчасти,
        NewsArticle для Новостей (различаем по родительской странице — модель
        ArticlePage общая для обоих разделов), редакционный автор по умолчанию,
        proficiencyLevel/about для Матчасти из классификаторов "Уровень"/"Категории".
        """
        sd_dict = super().seo_struct_article_dict

        parent = self.get_parent().specific
        is_tech = isinstance(parent, TechArticleIndexPage)
        sd_dict["@type"] = "TechArticle" if is_tech else "NewsArticle"

        # seo_author (из CoderedArticlePage) в отсутствие явного автора падает
        # обратно на author/owner страницы — оба технические поля Wagtail
        # (кто опубликовал), не редакционная подпись: на проде author_id
        # заполнен только у 14/104 статей и везде указывает на служебный
        # аккаунт админа, не на настоящего автора. Единственный надёжный
        # сигнал "у статьи есть именной автор" — явно заполненный author_display.
        if not self.author_display:
            site = self.get_site()
            sd_dict["author"] = {
                "@type": "Organization",
                "name": "Gripline",
                "url": site.root_url if site else "",
            }

        if is_tech:
            level_term = self.classifier_terms.filter(
                classifier__name="Уровень"
            ).first()
            if level_term:
                proficiency = self.SEO_PROFICIENCY_LEVEL_MAP.get(level_term.name)
                if proficiency:
                    sd_dict["proficiencyLevel"] = proficiency

            categories = list(
                self.classifier_terms.filter(
                    classifier__name="Категории"
                ).values_list("name", flat=True)
            )
            if categories:
                sd_dict["about"] = categories

        return sd_dict

    body = StreamField(
        _article_body_streamblocks() + [("markdown", MarkdownBlock(icon="code"))],
        null=True,
        blank=True,
        use_json_field=True,
    )

    social_teaser = models.TextField(
        max_length=900,
        blank=True,
        verbose_name="Тизер для соцсетей",
        help_text=(
            "Короткий тизер для анонса в соцсетях (Telegram, MAX и др.), 3–5 "
            "предложений. Лимит ~900 символов — оставляет запас под ссылку, "
            "теги и подпись к фото (самый тесный из лимитов площадок — "
            "подпись к фото в Telegram, 1024 символа)."
        ),
    )
    social_extra_tags = ParentalManyToManyField(
        'website.SocialTag',
        blank=True,
        verbose_name="Доп. теги для соцсетей",
        help_text="Добавляются к автоматическим тегам раздела для этого конкретного поста — во всех соцсетях сразу.",
    )
    telegram_posted_at = models.DateTimeField(null=True, blank=True, editable=False)
    telegram_posted_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        editable=False, related_name='+',
    )
    max_posted_at = models.DateTimeField(null=True, blank=True, editable=False)
    max_posted_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        editable=False, related_name='+',
    )
    vk_posted_at = models.DateTimeField(null=True, blank=True, editable=False)
    vk_posted_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        editable=False, related_name='+',
    )

    content_panels = CoderedArticlePage.content_panels + [
        FieldPanel('social_teaser'),
        FieldPanel('social_extra_tags'),
    ]

    base_form_class = ArticlePageForm

class ArticleIndexPage(TransliteratedSlugMixin, CoderedArticleIndexPage):
    class Meta:
        verbose_name = "Article Landing Page"
    index_query_pagemodel = "website.ArticlePage"
    subpage_types = ["website.ArticlePage"]
    template = "coderedcms/pages/article_index_page.html"

    def get_context(self, request):
        context = super().get_context(request)

        # Получаем статьи только из этого раздела (исключаем матчасть и другие индексы)
        articles = ArticlePage.objects.child_of(self).live().order_by('-date_display')

        # Получаем данные классификаторов
        classifiers_data = self.get_classifiers_data()

        # Получаем все активные фильтры из GET-параметров
        active_filters = {}

        for classifier, terms in classifiers_data.items():
            classifier_slug = classifier.slug
            filter_value = request.GET.get(classifier_slug)
            if filter_value:
                active_filters[classifier_slug] = filter_value
                articles = articles.filter(
                    classifier_terms__slug=filter_value,
                    classifier_terms__classifier__slug=classifier_slug
                )

        context['articles'] = articles
        context['classifiers_data'] = classifiers_data
        context['active_filters'] = active_filters

        return context

    def get_classifiers_data(self):
        """Возвращает словарь классификаторов и их терминов, используемых в статьях"""
        from coderedcms.models import ClassifierTerm

        # Получаем термины только из дочерних статей этого раздела
        child_ids = ArticlePage.objects.child_of(self).live().values_list('id', flat=True)
        used_terms = ClassifierTerm.objects.filter(
            coderedpage__id__in=child_ids,
        ).distinct().select_related('classifier')

        # Группируем по классификаторам
        classifiers_dict = {}
        for term in used_terms:
            classifier = term.classifier
            if classifier not in classifiers_dict:
                classifiers_dict[classifier] = []
            if term not in classifiers_dict[classifier]:
                classifiers_dict[classifier].append(term)

        return classifiers_dict

class TechArticleIndexPage(TransliteratedSlugMixin, CoderedArticleIndexPage):
    class Meta:
        verbose_name = "Матчасть (индекс)"
    subpage_types = ["website.ArticlePage"]
    template = "coderedcms/pages/tech_article_index_page.html"

    def get_index_children(self):
        return ArticlePage.objects.child_of(self).live().order_by('-first_published_at')

    def get_context(self, request):
        context = super().get_context(request)
        articles = ArticlePage.objects.child_of(self).live().order_by('-first_published_at')
        classifiers_data = self._get_section_classifiers()
        active_filters = {}
        for classifier, terms in classifiers_data.items():
            classifier_slug = classifier.slug
            filter_value = request.GET.get(classifier_slug)
            if filter_value:
                active_filters[classifier_slug] = filter_value
                articles = articles.filter(
                    classifier_terms__slug=filter_value,
                    classifier_terms__classifier__slug=classifier_slug
                )
        context['articles'] = articles
        context['classifiers_data'] = classifiers_data
        context['active_filters'] = active_filters
        return context

    def _get_section_classifiers(self):
        from coderedcms.models import ClassifierTerm
        section_ids = ArticlePage.objects.child_of(self).live().values_list('id', flat=True)
        used_terms = ClassifierTerm.objects.filter(
            coderedpage__id__in=section_ids,
            coderedpage__live=True,
        ).distinct().select_related('classifier')
        classifiers_dict = {}
        for term in used_terms:
            classifier = term.classifier
            if classifier not in classifiers_dict:
                classifiers_dict[classifier] = []
            if term not in classifiers_dict[classifier]:
                classifiers_dict[classifier].append(term)
        return classifiers_dict


class EventPage(TransliteratedSlugMixin, CoderedEventPage):
    class Meta:
        verbose_name = "Event Page"
    parent_page_types = ["website.EventIndexPage", "website.ChampionshipPage", "website.StagePage"]
    template = "coderedcms/pages/event_page.html"

    # Новое поле для названия в админке
    admin_title = models.CharField(
        "Название для админки",
        max_length=255,
        blank=True,
        help_text="Название для отображения в списках админки (например, '1 этап Micro')"
    )

    # Связь с трассой
    track = models.ForeignKey(
        'website.Track',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='events',
        verbose_name="Трасса"
    )

    # Переопределяем content_panels
    content_panels = [
        # Сначала основные поля заголовка
        CoderedEventPage.content_panels[0],  # Это поле "Заголовок страницы видимый всем"
        FieldPanel('admin_title'),  # Теперь сразу под заголовком
    ] + CoderedEventPage.content_panels[1:] + [
        FieldPanel('track'),
        InlinePanel('race_class_groups', label="🏁 Результаты по классам"),
    ]

    def __str__(self):
        """Используем admin_title в админке, если он есть"""
        return self.admin_title or self.title

    @property
    def seo_description(self) -> str:
        # Пустое «Описание для поиска» — из данных этапа, а не текст меню в сниппете
        from website.seo_meta import event_page_description
        return super().seo_description or event_page_description(self)

    def get_championship(self):
        """Ближайший ChampionshipPage: родитель напрямую либо родитель StagePage-родителя."""
        from .pages_extra import StagePage
        parent = self.get_parent().specific
        if isinstance(parent, ChampionshipPage):
            return parent
        if isinstance(parent, StagePage):
            return parent.get_parent().specific
        return None

    @property
    def race_results(self):
        """Все RaceResult этой страницы across все классы (race_class_groups) —
        используется в мини-таблице протокола (website/includes/event_results_mini_table.html)."""
        from website.services.race_results import with_classification_order
        from .racing import RaceResult
        return with_classification_order(RaceResult.objects.filter(group__page=self)).select_related(
            'driver', 'team', 'group__race_class'
        ).order_by('group__race_class__sort_order', 'group__race_class__name', '_unclassified', 'position')

    api_fields = [
        APIField('admin_title'),
    ]

class ColorSwatchWidget(forms.Widget):
    """Пикер цвета палитрой готовых образцов — по аналогии с выбором цвета в ЛК организатора."""

    PALETTE = [
        '#e63946', '#ea580c', '#d97706',
        '#16a34a', '#0891b2', '#2563eb',
        '#4f46e5', '#7c3aed', '#db2777',
        '#65a30d', '#0e7490', '#b91c1c',
        '#ffc107', '#0dcaf0',
    ]

    def render(self, name, value, attrs=None, renderer=None):
        value = value or ''
        widget_id = (attrs or {}).get('id') or f'id_{name}'
        unset_selected = '' if value else ' selected'
        swatches = format_html_join(
            '',
            '<span class="gl-color-swatch{}" style="background:{};" data-color="{}" title="{}"></span>',
            ((' selected' if c == value else '', c, c, c) for c in self.PALETTE),
        )
        return format_html(
            '''<input type="hidden" name="{name}" id="{id}" value="{value}">
<div class="gl-color-swatches" data-target="{id}">
    <span class="gl-color-swatch gl-color-unset{unset_selected}" data-color="" title="Не задан — унаследуется от родителя">&times;</span>
    {swatches}
</div>
<style>
    .gl-color-swatches {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; }}
    .gl-color-swatch {{ width: 32px; height: 32px; border-radius: 6px; cursor: pointer; border: 3px solid transparent; transition: transform .15s, border-color .15s; }}
    .gl-color-swatch:hover {{ transform: scale(1.12); }}
    .gl-color-swatch.selected {{ border-color: #333; transform: scale(1.12); }}
    .gl-color-unset {{ background: repeating-linear-gradient(45deg, #888, #888 4px, #ccc 4px, #ccc 8px); display: flex; align-items: center; justify-content: center; font-weight: bold; color: #222; }}
</style>
<script>
    (function() {{
        document.querySelectorAll('.gl-color-swatches[data-target="{id}"] .gl-color-swatch').forEach(function(el) {{
            el.addEventListener('click', function() {{
                var box = this.parentElement;
                var target = document.getElementById(box.dataset.target);
                target.value = this.dataset.color;
                box.querySelectorAll('.gl-color-swatch').forEach(function(s) {{ s.classList.remove('selected'); }});
                this.classList.add('selected');
            }});
        }});
    }})();
</script>''',
            name=name, id=widget_id, value=value, swatches=swatches, unset_selected=unset_selected,
        )


class ChampionshipPage(TransliteratedSlugMixin, CoderedWebPage):
    class Meta:
        verbose_name = "Чемпионат (Хаб)"

    parent_page_types = ["website.SeasonArchivePage", "website.WebPage"]
    subpage_types = ["website.EventPage", "website.StagePage"]
    template = "coderedcms/pages/championship_page.html"

    # Поле для отметки завершённости чемпионата
    is_completed = models.BooleanField(
        "Чемпионат завершён",
        default=False,
        help_text="Отметьте, если все этапы проведены"
    )

    # Цвет чемпионата в общем календаре. Наследуется всеми этапами, у которых цвет не задан явно,
    # но не отменяет индивидуальный цвет, выбранный на конкретном этапе (StagePage.calendar_color).
    calendar_color = models.CharField(
        "Цвет в календаре",
        max_length=7,
        blank=True,
        default="",
        help_text="Цвет по умолчанию для всех этапов чемпионата, у которых цвет не задан индивидуально"
    )

    # Убираем competition_types как ManyToMany поле
    # Будем использовать отдельную модель через InlinePanel

    # Кэш турнирных таблиц (get_champions_by_class) — не редактируется в
    # админке, обновляется командой update_championship_standings.
    # Структура: {"<year>"|"__all__": {"<class_id>": {"name": ..., "champions": [{"position", "driver_id", "points", "starts"}, ...]}}}
    standings_cache = models.JSONField(
        "Кэш турнирных таблиц",
        default=dict,
        blank=True,
        editable=False,
    )

    # Основные поля
    content_panels = CoderedWebPage.content_panels + [
        FieldPanel('is_completed'),
        FieldPanel('calendar_color', widget=ColorSwatchWidget),
        InlinePanel('championship_competition_types', label="Типы соревнований"),
    ]

    promote_panels = CoderedWebPage.promote_panels  # Без изменений

    @property
    def seo_description(self) -> str:
        from website.seo_meta import championship_page_description
        return super().seo_description or championship_page_description(self)

    def get_years(self):
        """
        Возвращает список годов, в которые проводились этапы чемпионата
        Учитывает годовые кубки (например, этапы в декабре и январе)
        """
        # /api/v2/pulse/ зовёт метод десятки раз на один чемпионат — считаем
        # один раз на объект. Раньше обход дерева шёл запросами на каждый
        # этап и событие: ~65% времени ответа Пульса.
        if getattr(self, '_years_cache', None) is None:
            self._years_cache = self._compute_years()
        return list(self._years_cache)

    def _compute_years(self):
        from .pages_extra import StagePage
        children = list(self.get_children().live().values_list('id', 'path'))
        years = {
            d.year for d in StagePage.objects.filter(id__in=[c[0] for c in children])
            .exclude(start_date__isnull=True).values_list('start_date', flat=True)
        }
        # Даты дочерних EventPage этапов — на случай, если отличаются от даты этапа
        live_child_paths = {c[1] for c in children}
        event_ids = [
            pid for pid, path in Page.objects.live()
            .filter(path__startswith=self.path, depth=self.depth + 2)
            .values_list('id', 'path')
            if path[:-Page.steplen] in live_child_paths
        ]
        years.update(
            s.year for s in EventOccurrence.objects.filter(event_id__in=event_ids)
            .exclude(start__isnull=True).values_list('start', flat=True)
        )
        return sorted(years)

    def get_champions_by_class(self, year=None):
        """
        Возвращает топ-3 пилотов для каждого класса.

        Читает из `standings_cache` (обновляется командой
        `update_championship_standings`, запускается вручную после ввода
        новых результатов — тот же паттерн, что `update_ratings` для
        rating_by_class на Driver). Раньше пересчитывалось вживую при
        каждом вызове — на странице пилота (Career highlights: «Титул»)
        это означало полный пересчёт турнирной таблицы при каждом
        открытии профиля, ~2с на реальных данных. Если кэша ещё нет
        (например, до первого запуска команды) — считает вживую как
        fallback, ничего не ломается.
        """
        cache_key = str(year) if year else '__all__'
        cached = (self.standings_cache or {}).get(cache_key)
        if cached is not None:
            return self._hydrate_champions_cache(cached)
        return self._compute_champions_by_class(year)

    def _hydrate_champions_cache(self, cached):
        """Разворачивает JSON-кэш (driver_id) обратно в объекты Driver — один bulk-запрос."""
        from .people import Driver

        driver_ids = {
            c['driver_id']
            for data in cached.values()
            for c in data['champions']
        }
        drivers = {d.id: d for d in Driver.objects.filter(id__in=driver_ids)}

        result = {}
        for class_id_str, data in cached.items():
            champions = [
                {
                    'position': c['position'],
                    'driver': drivers[c['driver_id']],
                    'points': c['points'],
                    'starts': c['starts'],
                }
                for c in data['champions'] if c['driver_id'] in drivers
            ]
            result[int(class_id_str)] = {'name': data['name'], 'champions': champions}
        return result

    def _compute_champions_by_class(self, year=None):
        """
        Тяжёлая версия — считает турнирную таблицу вживую из RaceResult.
        Не вызывать напрямую на каждый рендер страницы — см. get_champions_by_class()
        и команду update_championship_standings.

        Если year указан и чемпионат не завершён (is_completed=False) — только этапы за этот год
        Если чемпионат завершён (is_completed=True) — все этапы
        """
        from django.db.models import Sum, Q
        from django.utils import timezone
        from .racing import RaceResult
        from .pages_extra import StagePage

        # Получаем все StagePage (этапы) этого чемпионата
        stages = self.get_children().live().specific()

        # Собираем все EventPage из всех StagePage
        all_events = []
        for stage in stages:
            for event in stage.get_children().live().specific():
                if isinstance(event, EventPage):
                    all_events.append(event)

        # Фильтруем события по году, если нужно
        if year and not self.is_completed:
            filtered_events = []
            for event in all_events:
                if hasattr(event, 'occurrences'):
                    for occurrence in event.occurrences.all():
                        if occurrence.start and occurrence.start.year == year:
                            filtered_events.append(event)
                            break
            events = filtered_events
        else:
            events = all_events

        if not events:
            return {}

        # Получаем все результаты для отфильтрованных событий
        results = RaceResult.objects.filter(
            group__page__in=events
        ).select_related('driver', 'group__race_class')

        # Группируем по классам
        class_results = {}

        for result in results:
            class_id = result.group.race_class_id
            if class_id not in class_results:
                class_results[class_id] = {
                    'name': result.group.race_class.name,
                    'scores': {}
                }

            driver_id = result.driver_id
            if driver_id not in class_results[class_id]['scores']:
                class_results[class_id]['scores'][driver_id] = {
                    'driver': result.driver,
                    'total_points': 0,
                    'starts': 0
                }

            # Суммируем очки с учётом штрафов
            points_with_penalty = result.points - (result.penalty or 0)
            class_results[class_id]['scores'][driver_id]['total_points'] += points_with_penalty
            class_results[class_id]['scores'][driver_id]['starts'] += 1

        # Сортируем и берем топ-3 для каждого класса
        result_data = {}

        for class_id, data in class_results.items():
            # Сортируем пилотов по очкам
            sorted_drivers = sorted(
                data['scores'].values(),
                key=lambda x: -x['total_points']
            )[:3]  # Берем топ-3

            champions = []
            for position, driver_data in enumerate(sorted_drivers, 1):
                champions.append({
                    'position': position,
                    'driver': driver_data['driver'],
                    'points': driver_data['total_points'],
                    'starts': driver_data['starts']
                })

            result_data[class_id] = {
                'name': data['name'],
                'champions': champions
            }

        return result_data

    def get_champion(self):
        """Возвращает чемпиона (первое место в главном классе)"""
        return self.champion_driver

    def get_context(self, request):
      context = super().get_context(request)
      from .racing import RaceClass, RaceClassResultGroup, RaceResult

      # Получаем ВСЕ дочерние StagePage (этапы) этого чемпионата
      all_stages = self.get_children().live().specific()

      # Собираем все EventPage из всех StagePage
      all_events = []
      for stage in all_stages:
          for event in stage.get_child_classes():
              if event not in all_events:
                  all_events.append(event)

      # Нормализуем входящее название класса
      raw_class_name = request.GET.get('race_class', '')
      from urllib.parse import unquote
      selected_class_name = unquote(raw_class_name.replace('+', ' '))

      # Получаем ВСЕ доступные классы для этого чемпионата
      available_class_ids = RaceResult.objects.filter(
          group__page__in=all_events
      ).values_list('group__race_class_id', flat=True).distinct()

      available_classes = RaceClass.objects.filter(id__in=available_class_ids).order_by('sort_order', 'name')

      # Получаем список названий для проверки
      available_class_names = [c.name for c in available_classes]

      # Если класс не выбран или не найден — берём первый из списка
      if not selected_class_name or selected_class_name not in available_class_names:
          selected_class_name = available_class_names[0] if available_class_names else None

      # Получаем ID групп результатов ТОЛЬКО для выбранного класса
      class_group_ids = RaceClassResultGroup.objects.filter(
          page__in=all_events,
          race_class__name=selected_class_name
      ).values_list('id', flat=True)

      # Функция для получения даты события
      def get_event_date(event):
          if event.occurrences.exists():
              return event.occurrences.first().start
          return event.first_published_at

      # Фильтруем события по выбранному классу
      events = []
      for event in all_events:
          if RaceResult.objects.filter(
              group__page=event,
              group__race_class__name=selected_class_name
          ).exists():
              events.append(event)

      # СОРТИРУЕМ СОБЫТИЯ ПО ДАТЕ (от раннего к позднему)
      events.sort(key=get_event_date)

      # Собираем статистику ТОЛЬКО для этого чемпионата и класса
      standings = {}
      for res in RaceResult.objects.filter(group_id__in=class_group_ids).select_related('driver', 'group__race_class', 'team'):
          driver_id = res.driver.id
          if driver_id not in standings:
              standings[driver_id] = {
                  'driver': res.driver,
                  'team': res.team,
                  'race_number': res.race_number,
                  'chassis': res.chassis_new,
                  'scores': {},
                  'total': 0,
                  'penalty_total': 0,
                  'tie_breaker_total': 0,
              }
          standings[driver_id]['scores'][res.group.page_id] = res.points
          standings[driver_id]['total'] += res.points - res.penalty
          standings[driver_id]['penalty_total'] += res.penalty
          standings[driver_id]['tie_breaker_total'] += res.tie_breaker
          if res.race_number:
              standings[driver_id]['race_number'] = res.race_number
          if res.chassis_new:
              standings[driver_id]['chassis_new'] = res.chassis_new

      # Сортировка
      sorted_standings = sorted(
          standings.values(),
          key=lambda x: (-x['total'], -x['tie_breaker_total'])
      )

      context['events'] = events
      context['standings'] = sorted_standings
      context['available_classes'] = available_classes
      context['selected_class'] = selected_class_name

      return context

# Добавьте эту модель ПОСЛЕ ChampionshipPage
class ChampionshipCompetitionType(models.Model):
    page = ParentalKey('ChampionshipPage', related_name='championship_competition_types')
    competition_type = models.ForeignKey('CompetitionType', on_delete=models.CASCADE)

    panels = [
        FieldPanel('competition_type'),
    ]

    class Meta:
        unique_together = ('page', 'competition_type')
        verbose_name = "Тип соревнования"
        verbose_name_plural = "Типы соревнований"

    def __str__(self):
        return self.competition_type.name

class EventIndexPage(TransliteratedSlugMixin, CoderedEventIndexPage):
    class Meta:
        verbose_name = "Events Landing Page"
    index_query_pagemodel = "website.EventPage"
    subpage_types = ["website.EventPage"]
    template = "coderedcms/pages/event_index_page.html"

class EventOccurrence(CoderedEventOccurrence):
    event = ParentalKey(EventPage, related_name="occurrences")

class SeasonArchivePage(TransliteratedSlugMixin, CoderedWebPage):
    class Meta:
        verbose_name = "Главная страница результатов"
    subpage_types = ["website.ChampionshipPage"]
    template = "coderedcms/pages/season_archive_page.html"


    def get_context(self, request):
        context = super().get_context(request)
        championships = self.get_children().live().specific()
        selected_slug = request.GET.get('champ')
        active_champ = championships.filter(slug=selected_slug).first() or championships.first()

        context['championships'] = championships
        context['active_champ'] = active_champ

        if active_champ:
            context.update(active_champ.get_context(request))
            context['events_list'] = active_champ.get_children().live().specific()
        return context
