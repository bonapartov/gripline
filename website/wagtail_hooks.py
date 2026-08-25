from wagtail_modeladmin.options import (ModelAdmin, ModelAdminGroup, modeladmin_register)
from .models import Driver, Team, Track, Chassis, TyreBrand, TyreType, Tyre, Engine, TeamStaff, TeamStaffMembership, AnalyticsSettings, EventIndexPage, StagePage, TelegramSettings, MaxSettings, VkSettings, SocialTag, ArticlePage
from wagtail import hooks
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.urls import path, reverse
from .import_utils import import_results, import_preview, import_confirm, import_add_driver
from wagtail.admin.menu import MenuItem, Menu, SubmenuMenuItem
from wagtail.admin.action_menu import ActionMenuItem, PublishMenuItem
from django.contrib import messages
from django.utils import timezone
from .admin_views import analytics_dashboard, analytics_status
from .telegram_admin_views import telegram_status, telegram_send
from .telegram import send_to_telegram
from .max_admin_views import max_status, max_send
from .max import send_to_max
from .vk_admin_views import vk_status, vk_send
from .vk import send_to_vk
import wagtail.admin.rich_text.editors.draftail.features as draftail_features
from draftjs_exporter.dom import DOM
from wagtail.admin.rich_text.converters.html_to_contentstate import InlineEntityElementHandler
from wagtail.rich_text import LinkHandler
from django.utils.html import escape
from django.templatetags.static import static

class DriverAdmin(ModelAdmin):
    model = Driver
    menu_label = 'Пилоты'
    menu_icon = 'user'

    def full_name_display(self, obj):
        return f"{obj.first_name} {obj.last_name}"

    full_name_display.short_description = 'ФИО'
    list_display = ('full_name_display', 'city')
    list_filter = ('city',)
    search_fields = ('first_name', 'last_name', 'city')

class TeamAdmin(ModelAdmin):
    model = Team
    menu_label = 'Команды'
    menu_icon = 'group'
    list_display = ('name',)
    search_fields = ('name',)

class TrackAdmin(ModelAdmin):
    model = Track
    menu_label = 'Трассы'
    menu_icon = 'site'
    list_display = ('name', 'city')
    search_fields = ('name', 'city')

class ChassisAdmin(ModelAdmin):
    model = Chassis
    menu_label = 'Шасси'
    menu_icon = 'cog'
    list_display = ('name', 'country')
    search_fields = ('name', 'country')

class TyreBrandAdmin(ModelAdmin):
    model = TyreBrand
    menu_label = 'Производители шин'
    menu_icon = 'fa-brands'
    list_display = ('name', 'country')
    search_fields = ('name', 'country')

class TyreTypeAdmin(ModelAdmin):
    model = TyreType
    menu_label = 'Типы шин'
    menu_icon = 'fa-type'
    list_display = ('name',)
    search_fields = ('name',)

class TyreAdmin(ModelAdmin):
    model = Tyre
    menu_label = 'Шины'
    menu_icon = 'fa-tyre'
    list_display = ('__str__', 'brand', 'type')
    list_filter = ('brand', 'type')
    search_fields = ('brand__name',)

class EngineAdmin(ModelAdmin):
    model = Engine
    menu_label = 'Двигатели'
    menu_icon = 'fa-engine'
    list_display = ('name', 'country')
    search_fields = ('name', 'country')

class TeamStaffAdmin(ModelAdmin):
    model = TeamStaff
    menu_label = 'Сотрудники команд'
    menu_icon = 'user'
    list_display = ('last_name', 'first_name', 'position', 'phone')
    list_filter = ('position',)
    search_fields = ('last_name', 'first_name', 'position')

class TeamStaffMembershipAdmin(ModelAdmin):
    model = TeamStaffMembership
    menu_label = 'Участия сотрудников'
    menu_icon = 'group'
    list_display = ('staff', 'team', 'is_active')
    list_filter = ('is_active', 'team')
    search_fields = ('staff__last_name', 'staff__first_name', 'team__name')

# Группы меню
class PilotsGroup(ModelAdminGroup):
    menu_label = 'Пилоты'
    menu_icon = 'user'
    items = (DriverAdmin,)

class TeamsGroup(ModelAdminGroup):
    menu_label = 'Команды'
    menu_icon = 'group'
    items = (TeamAdmin, TeamStaffAdmin, TeamStaffMembershipAdmin)

class EquipmentGroup(ModelAdminGroup):
    menu_label = 'Техника'
    menu_icon = 'cog'
    items = (ChassisAdmin, EngineAdmin)

class TyresGroup(ModelAdminGroup):
    menu_label = 'Шины'
    menu_icon = 'fa-tyre'
    items = (TyreBrandAdmin, TyreTypeAdmin, TyreAdmin)

class TracksGroup(ModelAdminGroup):
    menu_label = 'Трассы'
    menu_icon = 'site'
    items = (TrackAdmin,)

class AnalyticsSettingsAdmin(ModelAdmin):
    model = AnalyticsSettings
    menu_label = 'Параметры рейтинга'
    menu_icon = 'cog'
    list_display = (
        'lambda_active',
        'lambda_inactive',
        'inactive_threshold_days',
        'bt_alpha',
        'pagerank_damping',
        'updated_at',
    )

class AnalyticsGroup(ModelAdminGroup):
    menu_label = 'Аналитика'
    menu_icon = 'fa-bar-chart'
    items = (AnalyticsSettingsAdmin,)

class TelegramSettingsAdmin(ModelAdmin):
    model = TelegramSettings
    menu_label = 'Настройки'
    menu_icon = 'fa-paper-plane'
    list_display = ('channel_id', 'link_text')

class TelegramGroup(ModelAdminGroup):
    menu_label = 'Telegram'
    menu_icon = 'fa-paper-plane'
    items = (TelegramSettingsAdmin,)
    # Своего пункта в меню не создаёт — вложен в «Соцсети» через
    # register_social_networks_menu ниже (URL/права всё равно регистрируются
    # через register_with_wagtail(), просто без автоматического menu item).
    add_to_admin_menu = False

class MaxSettingsAdmin(ModelAdmin):
    model = MaxSettings
    menu_label = 'Настройки'
    menu_icon = 'fa-comment'
    list_display = ('chat_id', 'link_text')

class MaxGroup(ModelAdminGroup):
    menu_label = 'MAX'
    menu_icon = 'fa-comment'
    items = (MaxSettingsAdmin,)
    add_to_admin_menu = False

class VkSettingsAdmin(ModelAdmin):
    model = VkSettings
    menu_label = 'Настройки'
    menu_icon = 'fa-globe'
    list_display = ('group_id', 'link_text')

class VkGroup(ModelAdminGroup):
    menu_label = 'VK'
    menu_icon = 'fa-globe'
    items = (VkSettingsAdmin,)
    add_to_admin_menu = False

class SocialTagAdmin(ModelAdmin):
    model = SocialTag
    menu_label = 'Теги'
    menu_icon = 'fa-tags'
    list_display = ('tag', 'emoji', 'parent_page')
    list_filter = ('parent_page',)

class SocialTagGroup(ModelAdminGroup):
    # Теги общие для всех соцсетей — top-level пункт в "Соцсети", не вложен
    # ни в Telegram, ни в MAX (иначе редактор не поймёт, что тег общий).
    menu_label = 'Теги'
    menu_icon = 'fa-tags'
    items = (SocialTagAdmin,)
    add_to_admin_menu = False

# Регистрируем группы
modeladmin_register(PilotsGroup)
modeladmin_register(TeamsGroup)
modeladmin_register(EquipmentGroup)
modeladmin_register(TyresGroup)
modeladmin_register(TracksGroup)
modeladmin_register(AnalyticsGroup)

telegram_group = TelegramGroup()
telegram_group.register_with_wagtail()

max_group = MaxGroup()
max_group.register_with_wagtail()

vk_group = VkGroup()
vk_group.register_with_wagtail()

social_tag_group = SocialTagGroup()
social_tag_group.register_with_wagtail()

def _menu_icon_kwargs(menu_icon):
    """Повторяет логику иконок wagtail_modeladmin.GroupMenuItem: старые
    fa-* иконки идут через CSS-класс, а не через современный icon_name."""
    if menu_icon[:3] == 'fa-':
        return {'classname': 'icon icon-%s' % menu_icon}
    return {'icon_name': menu_icon}

@hooks.register('register_admin_menu_item')
def register_social_networks_menu():
    """«Соцсети» в боковом меню: Telegram, MAX, VK — каждый со своими
    "Настройками", и общий top-level пункт "Теги" (один набор тегов на все
    соцсети). Добавление новой соцсети — новая ModelAdminGroup с
    add_to_admin_menu=False + новый SubmenuMenuItem рядом с telegram_item/
    max_item/vk_item ниже."""
    telegram_item = SubmenuMenuItem(
        'Telegram', Menu(items=telegram_group.get_submenu_items()), name='telegram', order=1,
        **_menu_icon_kwargs('fa-paper-plane'),
    )
    max_item = SubmenuMenuItem(
        'MAX', Menu(items=max_group.get_submenu_items()), name='max', order=2,
        **_menu_icon_kwargs('fa-comment'),
    )
    vk_item = SubmenuMenuItem(
        'VK', Menu(items=vk_group.get_submenu_items()), name='vk', order=3,
        **_menu_icon_kwargs('fa-globe'),
    )
    tags_item = SubmenuMenuItem(
        'Теги', Menu(items=social_tag_group.get_submenu_items()), name='social-tags', order=4,
        **_menu_icon_kwargs('fa-tags'),
    )
    social_menu = Menu(items=[telegram_item, max_item, vk_item, tags_item])
    return SubmenuMenuItem(
        'Соцсети', social_menu, name='soc-networks', order=999,
        **_menu_icon_kwargs('fa-share-alt'),
    )

# === КНОПКИ ПУБЛИКАЦИИ СТАТЬИ: "НА САЙТЕ" / "ВЕЗДЕ" (+ TELEGRAM) ===

PUBLISH_EVERYWHERE_VALUE = 'action-publish-everywhere'

def _is_article_page_context(context):
    """True если экшен-меню сейчас относится к ArticlePage — и на создании
    (view == 'create'), и на редактировании существующей страницы.

    На создании Wagtail не кладёт 'page' в context вообще (PageActionMenu
    в create.py вызывается без page=...) — там есть только parent_page,
    поэтому isinstance(context.get('page'), ArticlePage) всегда False на
    этом экране. Модель, которую создают, там же в URL create-вью
    (/admin/pages/add/<app>/<model>/<parent_id>/) — берём её из
    request.resolver_match.kwargs, как это делает сам Wagtail для
    определения self.page_class в CreateView.
    """
    if context.get('view') == 'create':
        request = context.get('request')
        match = getattr(request, 'resolver_match', None)
        if not match:
            return False
        return (
            match.kwargs.get('content_type_app_name') == 'website'
            and match.kwargs.get('content_type_model_name') == 'articlepage'
        )
    return isinstance(context.get('page'), ArticlePage)

class PublishOnSiteMenuItem(PublishMenuItem):
    """Копия стандартного PublishMenuItem с другим лейблом. Не переиспользуем
    сам PublishMenuItem — он singleton на все типы страниц (кэшируется в
    wagtail.admin.action_menu.BASE_PAGE_ACTION_MENU_ITEMS), менять .label
    на нём напрямую поменяло бы подпись кнопки везде в админке, не только
    у статей."""
    label = 'Опубликовать на сайте'

class PublishEverywhereMenuItem(ActionMenuItem):
    """Публикует страницу как обычно (action-publish, тот же реальный publish),
    но с отдельным value — по нему send_announcements_on_publish_everywhere
    ниже понимает, что после публикации нужно ещё отправить анонсы в
    Telegram и MAX."""
    label = 'Опубликовать везде'
    name = 'action-publish'
    template_name = 'wagtailadmin/pages/action_menu/publish_everywhere.html'
    icon_name = 'upload'

    def is_shown(self, context):
        if not _is_article_page_context(context):
            return False
        if context['view'] == 'create':
            # На создании ещё нет context['page'] (см. _is_article_page_context) —
            # права проверяются так же, как у стандартного PublishMenuItem: через
            # родительскую страницу.
            return (
                context['parent_page']
                .permissions_for_user(context['request'].user)
                .can_publish_subpage()
            )
        perms_tester = self.get_user_page_permissions_tester(context)
        return not context['locked_for_user'] and perms_tester.can_publish()

    def get_context_data(self, parent_context):
        context = super().get_context_data(parent_context)
        page = context.get('page')
        context['is_scheduled'] = bool(page and page.go_live_at and page.go_live_at > timezone.now())
        return context

@hooks.register('construct_page_action_menu')
def customize_article_publish_menu(menu_items, request, context):
    """Только для ArticlePage: переименовывает «Опубликовать» в «Опубликовать
    на сайте» и добавляет рядом «Опубликовать везде». Работает и на создании
    новой страницы, и на редактировании — см. _is_article_page_context."""
    if not _is_article_page_context(context):
        return
    for i, item in enumerate(menu_items):
        if type(item) is PublishMenuItem:
            menu_items[i] = PublishOnSiteMenuItem(order=item.order)
            menu_items.insert(i + 1, PublishEverywhereMenuItem(order=item.order))
            break

@hooks.register('after_publish_page')
def send_announcements_on_publish_everywhere(request, page):
    """«Опубликовать везде» — публикует страницу как обычно и дополнительно
    отправляет анонс в Telegram, MAX и VK. Каналы независимы: падение одного
    не блокирует попытку другого (свой try/except на каждый), у каждого
    своя отметка *_posted_at, чтобы не задублировать пост при повторной
    публикации статьи."""
    if request.POST.get('action-publish') != PUBLISH_EVERYWHERE_VALUE:
        return
    if not isinstance(page, ArticlePage):
        return
    if not page.social_teaser:
        messages.warning(request, 'Страница опубликована, но не отправлена в соцсети — не заполнен тизер.')
        return

    if page.telegram_posted_at:
        messages.info(request, 'В Telegram уже отправлялось ранее — для повторной отправки используйте кнопку «Отправить в Telegram».')
    else:
        try:
            send_to_telegram(page, request.user)
        except Exception:
            messages.error(request, 'Публикация: отправка в Telegram не удалась — проверьте логи.')
        else:
            messages.success(request, 'Отправлено в Telegram-канал.')

    if page.max_posted_at:
        messages.info(request, 'В MAX уже отправлялось ранее — для повторной отправки используйте кнопку «Отправить в MAX».')
    else:
        try:
            send_to_max(page, request.user)
        except Exception:
            messages.error(request, 'Публикация: отправка в MAX не удалась — проверьте логи.')
        else:
            messages.success(request, 'Отправлено в MAX-канал.')

    if page.vk_posted_at:
        messages.info(request, 'В VK уже отправлялось ранее — для повторной отправки используйте кнопку «Отправить в VK».')
    else:
        try:
            send_to_vk(page, request.user)
        except Exception:
            messages.error(request, 'Публикация: отправка в VK не удалась — проверьте логи.')
        else:
            messages.success(request, 'Опубликовано в сообществе VK.')

@hooks.register('register_admin_urls')
def register_import_urls():
    return [
        path('event/<int:page_id>/import/', import_results, name='event_import'),
        path('import/preview/', import_preview, name='event_import_preview'),
        path('import/confirm/', import_confirm, name='event_import_confirm'),
        path('import/add-driver/', import_add_driver, name='event_import_add_driver'),
        path('analytics/', analytics_dashboard, name='analytics_dashboard'),
        path('analytics/status/', analytics_status, name='analytics_status'),
        path('article/<int:page_id>/telegram-status/', telegram_status, name='article_telegram_status'),
        path('article/<int:page_id>/telegram-send/', telegram_send, name='article_telegram_send'),
        path('article/<int:page_id>/max-status/', max_status, name='article_max_status'),
        path('article/<int:page_id>/max-send/', max_send, name='article_max_send'),
        path('article/<int:page_id>/vk-status/', vk_status, name='article_vk_status'),
        path('article/<int:page_id>/vk-send/', vk_send, name='article_vk_send'),
    ]

@hooks.register('register_admin_menu_item')
def register_analytics_menu():
    return MenuItem(
        '📊 Аналитика',
        reverse('analytics_dashboard'),
        icon_name='fa-bar-chart',
        order=10000
    )

@hooks.register('insert_global_admin_css')
def global_admin_css():
    return mark_safe("""
        <style>
            .import-button { margin-left: 10px; }
            .listing .admin-badge {
                display: inline-block;
                padding: 2px 6px;
                border-radius: 4px;
                margin-left: 8px;
                font-size: 11px;
                font-weight: bold;
                vertical-align: middle;
                text-transform: uppercase;
                line-height: 1.2;
                background: #ffc107;
                color: #000;
                border: 1px solid #e0a800;
            }
            .listing .title {
                display: table-cell !important;
                align-items: normal;
                flex-wrap: nowrap;
            }
            body:not(.wagtail-admin) .title {
                display: inline;
            }

            /* === ТЁМНАЯ ТЕМА ДЛЯ СТРАНИЦЫ АНАЛИТИКИ === */
            .analytics-container {
                background-color: #1e1e2f;
                color: #fff;
                padding: 30px;
                border-radius: 8px;
            }
            .analytics-container h1,
            .analytics-container h2,
            .analytics-container h3,
            .analytics-container p {
                color: #fff !important;
            }
            .analytics-container .stat-card {
                background: #2a2a3a;
                color: #fff;
                border: 1px solid #3a3a4a;
                border-radius: 8px;
                padding: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.3);
            }
            .analytics-container .stat-value {
                font-size: 2.5rem;
                font-weight: bold;
                color: #ffc107;
            }
            .analytics-container .stat-label {
                font-size: 1rem;
                color: #adb5bd;
                text-transform: uppercase;
            }
            .analytics-container .log-box {
                background: #0a0a14;
                color: #00ff00;
                font-family: monospace;
                padding: 15px;
                border-radius: 4px;
                border: 1px solid #3a3a4a;
                max-height: 400px;
                overflow-y: auto;
                white-space: pre-wrap;
            }
            .analytics-container .button-run {
                background: #28a745;
                color: white;
                border: none;
                padding: 15px 30px;
                font-size: 1.2rem;
                border-radius: 4px;
                cursor: pointer;
                transition: background 0.3s;
            }
            .analytics-container .button-run:hover {
                background: #218838;
            }
            .analytics-container .button-run:disabled {
                background: #6c757d;
                cursor: not-allowed;
            }
            .analytics-container .model-list li {
                background: #2a2a3a;
                color: #fff;
                padding: 10px;
                margin: 5px 0;
                border-radius: 4px;
                list-style: none;
            }
            .analytics-container .model-list li:before {
                content: "✓";
                color: #28a745;
                font-weight: bold;
                margin-right: 10px;
            }

            /* Стили для поиска пилотов в админке */
            .driver-search-input {
                background-color: #2a2a3a !important;
                color: #ffffff !important;
                border: 1px solid #3a3a4a !important;
            }

            .driver-search-input:focus {
                outline: none;
                border-color: #ffc107 !important;
                box-shadow: 0 0 3px rgba(255, 193, 7, 0.3) !important;
            }

            .driver-search-input::placeholder {
                color: #adb5bd !important;
                opacity: 0.7;
            }

            .field-row { align-items: flex-end; }
        </style>
    """)

@hooks.register('insert_global_admin_js')
def insert_admin_js():
    return mark_safe("""
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // === ИМПОРТ РЕЗУЛЬТАТОВ И БЕЙДЖИ ===
            setTimeout(function() {
                if (window.location.pathname.includes('/edit/')) {
                    const pageId = window.location.pathname.split('/')[3];
                    if (pageId && !isNaN(pageId)) {
                        // Кнопка только на страницах типа Event Page (именно на них
                        // работает import_results — см. import_utils.py) — проверяем
                        // тип через встроенный Wagtail admin API перед вставкой.
                        // Кнопка кладётся в футер, рядом с группой кнопок
                        // "Сохранить черновик / Опубликовать" — не в шапку.
                        fetch('/admin/api/main/pages/' + pageId + '/')
                            .then(function(r) { return r.json(); })
                            .then(function(data) {
                                if (!data.meta || data.meta.type !== 'website.EventPage') return;
                                const actionsNav = document.querySelector('nav.footer__container');
                                if (!actionsNav) return;
                                const button = document.createElement('a');
                                button.href = '/admin/event/' + pageId + '/import/';
                                button.className = 'button bicolor icon icon-download import-button';
                                button.innerHTML = 'Импорт результатов';
                                actionsNav.appendChild(button);
                            })
                            .catch(function() {});
                    }
                }
                if (window.location.pathname.includes('/admin/pages/')) {
                    const rows = document.querySelectorAll('tbody tr');
                    rows.forEach(row => {
                        const titleCell = row.querySelector('.title');
                        if (titleCell && !titleCell.querySelector('.admin-badge')) {
                            const link = titleCell.querySelector('a');
                            if (link) {
                                const href = link.getAttribute('href');
                                const match = href.match(/\\/admin\\/pages\\/(\\d+)/);
                                if (match) {
                                    const pageId = match[1];
                                    const badge = document.createElement('span');
                                    badge.className = 'admin-badge';
                                    badge.textContent = '...';
                                    titleCell.appendChild(badge);
                                    fetch('/admin/api/main/pages/' + pageId + '/')
                                        .then(r => r.json())
                                        .then(data => {
                                            if (data.admin_title) {
                                                badge.textContent = data.admin_title;
                                            } else if (data.admin_display_title) {
                                                badge.textContent = data.admin_display_title;
                                            } else {
                                                badge.style.display = 'none';
                                            }
                                        })
                                        .catch(() => {
                                            badge.style.display = 'none';
                                        });
                                }
                            }
                        }
                    });
                }
            }, 500);

            // === КНОПКИ "ОТПРАВИТЬ В TELEGRAM" / "ОТПРАВИТЬ В MAX" (страницы статей) ===
            setTimeout(function() {
                const header = document.querySelector('header');
                if (!header || !window.location.pathname.includes('/edit/')) return;
                const pageId = window.location.pathname.split('/')[3];
                if (!pageId || isNaN(pageId)) return;

                function getCookie(name) {
                    const parts = ('; ' + document.cookie).split('; ' + name + '=');
                    return parts.length === 2 ? parts.pop().split(';').shift() : '';
                }

                const actions = header.querySelector('.actions') || header;
                const teaserField = document.getElementById('id_social_teaser');
                const extraTagsField = document.getElementById('id_social_extra_tags');

                // Строка "уже применены автоматически" общая для обоих каналов
                // (теги — общая сущность), рендерим один раз, из того ответа,
                // который придёт первым.
                let autoTagsRendered = false;
                function renderAutoTagsLine(data) {
                    if (autoTagsRendered || !extraTagsField || !Array.isArray(data.auto_tags)) return;
                    autoTagsRendered = true;
                    const autoTagsLine = document.createElement('div');
                    autoTagsLine.className = 'social-auto-tags';
                    autoTagsLine.style.cssText = 'font-size:12px; margin-bottom:6px; opacity:0.75;';
                    autoTagsLine.textContent = data.auto_tags.length
                        ? 'Уже применены автоматически: ' + data.auto_tags.map(function(t) {
                            return (t.emoji ? t.emoji + ' ' : '') + t.tag;
                        }).join(' ')
                        : 'Для этого раздела автоматических тегов не задано.';
                    extraTagsField.insertAdjacentElement('beforebegin', autoTagsLine);
                }

                function extraTagsLen() {
                    // overhead_len уже включает автоматические теги раздела —
                    // вручную выбранные на статье теги в мультиселекте туда не
                    // входят (выбор меняется без перезагрузки страницы), поэтому
                    // считаем их длину прямо здесь, по текущим selectedOptions.
                    if (!extraTagsField) return 0;
                    let total = 0;
                    for (const opt of extraTagsField.selectedOptions) {
                        total += opt.textContent.trim().length + 1; // +1 — разделяющий пробел
                    }
                    return total;
                }

                // Два независимых счётчика (у каждого канала свой лимит), оба
                // слушают общее поле тизера и общий мультиселект тегов.
                function setupCounter(label, data) {
                    if (!teaserField || typeof data.overhead_len !== 'number') return;
                    const counter = document.createElement('div');
                    counter.className = 'social-teaser-counter';
                    counter.style.cssText = 'font-size:12px; margin-top:4px; text-align:right;';

                    function updateCounter() {
                        const total = data.overhead_len + teaserField.value.length + extraTagsLen();
                        const over = total > data.teaser_limit;
                        counter.textContent = label + ': ' + total + ' / ' + data.teaser_limit +
                            (data.has_image ? ' (с учётом заголовка, фото, тегов и ссылки)' : ' (с учётом заголовка, тегов и ссылки)') +
                            (over && data.has_image ? ' — фото не поместится, уйдёт только текст' : '');
                        counter.style.color = over ? '#dc3545' : '';
                        counter.style.fontWeight = over ? 'bold' : 'normal';
                    }

                    teaserField.addEventListener('input', updateCounter);
                    extraTagsField && extraTagsField.addEventListener('change', updateCounter);
                    updateCounter();
                    teaserField.insertAdjacentElement('afterend', counter);
                }

                // Кнопки создаются сразу в фиксированном порядке (Telegram → MAX),
                // до резолва fetch — иначе порядок кнопок скакал бы в зависимости
                // от того, какой запрос ответит раньше.
                function createChannelButton(config) {
                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'button bicolor icon icon-mail ' + config.cssClass;
                    btn.disabled = true;
                    btn.textContent = 'Загрузка...';
                    actions.appendChild(btn);

                    let data = null;

                    function render() {
                        if (!data) return;
                        if (!data.teaser_filled) {
                            btn.disabled = true;
                            btn.title = 'Заполните тизер для соцсетей';
                        } else if (!data.live) {
                            btn.disabled = true;
                            btn.title = 'Страница ещё не опубликована';
                        } else if (!data.can_publish) {
                            btn.disabled = true;
                            btn.title = 'Нет прав на публикацию этой страницы';
                        } else {
                            btn.disabled = false;
                            btn.title = data.posted_at
                                ? 'Уже отправлялось ' + new Date(data.posted_at).toLocaleString('ru-RU')
                                : '';
                        }
                        btn.textContent = data.posted_at ? config.repeatLabel : config.sendLabel;
                    }

                    btn.addEventListener('click', function() {
                        if (!data) return;
                        if (data.posted_at && !confirm(
                            'Эта статья уже была отправлена в ' + config.channelName + ' ' +
                            new Date(data.posted_at).toLocaleString('ru-RU') +
                            '. Отправить повторно? Это создаст дубль поста в канале.'
                        )) {
                            return;
                        }
                        btn.disabled = true;
                        btn.textContent = 'Отправка...';
                        fetch(config.sendUrl, {
                            method: 'POST',
                            headers: { 'X-CSRFToken': getCookie('csrftoken') },
                        })
                            .then(r => r.json())
                            .then(result => {
                                alert(result.message);
                                if (result.success) {
                                    data.posted_at = new Date().toISOString();
                                }
                                render();
                            })
                            .catch(function() {
                                alert('Ошибка отправки — проверьте соединение');
                                render();
                            });
                    });

                    fetch(config.statusUrl)
                        .then(r => r.json())
                        .then(function(resolvedData) {
                            if (!resolvedData.applicable) {
                                btn.remove();
                                return;
                            }
                            data = resolvedData;
                            renderAutoTagsLine(data);
                            setupCounter(config.channelName, data);
                            render();
                        })
                        .catch(function() {
                            btn.remove();
                        });
                }

                createChannelButton({
                    channelName: 'Telegram',
                    sendLabel: 'Отправить в Telegram',
                    repeatLabel: 'Повторно отправить в Telegram',
                    statusUrl: '/admin/article/' + pageId + '/telegram-status/',
                    sendUrl: '/admin/article/' + pageId + '/telegram-send/',
                    cssClass: 'telegram-send-button',
                });
                createChannelButton({
                    channelName: 'MAX',
                    sendLabel: 'Отправить в MAX',
                    repeatLabel: 'Повторно отправить в MAX',
                    statusUrl: '/admin/article/' + pageId + '/max-status/',
                    sendUrl: '/admin/article/' + pageId + '/max-send/',
                    cssClass: 'max-send-button',
                });
                createChannelButton({
                    channelName: 'VK',
                    sendLabel: 'Отправить в VK',
                    repeatLabel: 'Повторно отправить в VK',
                    statusUrl: '/admin/article/' + pageId + '/vk-status/',
                    sendUrl: '/admin/article/' + pageId + '/vk-send/',
                    cssClass: 'vk-send-button',
                });
            }, 500);

            // === ПОИСК ПИЛОТОВ ===
            setTimeout(function() {
                // Функция для добавления поиска к select полям
                function enhanceSelectWithSearch(selectElement) {
                    if (!selectElement) return;

                    // Проверяем, не добавлен ли уже поиск
                    if (selectElement.closest('.field') && selectElement.closest('.field').querySelector('.driver-search-input')) {
                        return;
                    }

                    // Создаем контейнер
                    const container = document.createElement('div');
                    container.className = 'driver-search-container';
                    container.style.marginBottom = '8px';
                    container.style.marginTop = '4px';

                    // Создаем поле поиска
                    const searchInput = document.createElement('input');
                    searchInput.type = 'text';
                    searchInput.placeholder = '🔍 Поиск пилота по имени или городу...';
                    searchInput.className = 'driver-search-input';
                    searchInput.style.cssText = `
                        width: 100%;
                        padding: 8px 12px;
                        border: 1px solid #3a3a4a;
                        border-radius: 4px;
                        font-size: 13px;
                        box-sizing: border-box;
                        background-color: #2a2a3a !important;
                        color: #ffffff !important;
                    `;

                    // Вставляем перед select
                    const field = selectElement.closest('.field');
                    if (field) {
                        field.insertBefore(container, selectElement);
                        container.appendChild(searchInput);
                    } else {
                        selectElement.parentNode.insertBefore(container, selectElement);
                        container.appendChild(searchInput);
                    }

                    // Сохраняем все опции
                    const options = Array.from(selectElement.options);

                    searchInput.addEventListener('keyup', function() {
                        const searchText = this.value.toLowerCase().trim();

                        options.forEach(option => {
                            if (option.value === '') return; // пропускаем пустой

                            const text = option.text.toLowerCase();
                            if (searchText === '' || text.includes(searchText)) {
                                option.style.display = '';
                            } else {
                                option.style.display = 'none';
                            }
                        });
                    });
                }

                // Ищем все select поля на странице
                document.querySelectorAll('select[name$="-driver"]').forEach(select => {
                    if (!select.hasAttribute('data-search-enhanced')) {
                        select.setAttribute('data-search-enhanced', 'true');
                        enhanceSelectWithSearch(select);
                    }
                });

                // Отслеживаем появление новых форм (для inlines)
                const observer = new MutationObserver(function(mutations) {
                    mutations.forEach(function(mutation) {
                        if (mutation.addedNodes.length) {
                            setTimeout(function() {
                                document.querySelectorAll('select[name$="-driver"]:not([data-search-enhanced])').forEach(select => {
                                    select.setAttribute('data-search-enhanced', 'true');
                                    enhanceSelectWithSearch(select);
                                });
                            }, 200);
                        }
                    });
                });

                observer.observe(document.body, { childList: true, subtree: true });
            }, 500);
        });
    </script>
    """)


@hooks.register('construct_explorer_page_queryset')
def order_event_pages_by_admin_title(parent_page, pages, request):
    """
    В списках Wagtail-админки под StagePage/EventIndexPage (дочерние — всегда
    EventPage) сортируем по умолчанию по алфавиту "Название для админки"
    (EventPage.admin_title), а не по стандартному заголовку страницы.
    Явно выбранную пользователем сортировку (клик по колонке) не трогаем.
    """
    if request.GET.get('ordering'):
        return pages

    if isinstance(parent_page, (StagePage, EventIndexPage)):
        return pages.order_by('coderedpage__eventpage__admin_title')

    return pages


# ==================== АВТОССЫЛКИ НА ПИЛОТОВ И КОМАНД В СТАТЬЯХ ====================
#
# Live-автокомплит в теле статьи (ArticlePage.body): в блоке "text" (Draftail)
# редактор печатает "/пилот" или "/команда" — открывается встроенная в
# Wagtail 7.3 командная палитра (Notion-style, живёт в самом draftail.js),
# внутри неё — наш поиск по фамилии/названию, выбор вставляет ссылку.
#
# Ссылка хранится не как готовый href, а как <a linktype="driver" id="42">
# / <a linktype="team" id="7"> — тот же паттерн, что использует сам Wagtail
# для ссылок на страницы (PageLinkHandler, wagtail/rich_text/pages.py):
# реальный URL подставляется при РЕНДЕРЕ через DriverLinkHandler/
# TeamLinkHandler.expand_db_attributes(), поэтому смена slug у пилота/команды
# не превращает уже опубликованные упоминания в мёртвые ссылки.
#
# Фича НЕ добавлена в features.default_features — доступна только там, где
# явно перечислена: ArticlePage.body, блок "text" (см. website/models.py,
# _article_body_streamblocks()).


class DriverLinkHandler(LinkHandler):
    """<a linktype="driver" id="42"> -> реальный URL при рендере."""
    identifier = "driver"

    @staticmethod
    def get_model():
        return Driver

    @classmethod
    def expand_db_attributes(cls, attrs):
        try:
            driver = Driver.objects.get(id=attrs["id"])
        except (Driver.DoesNotExist, KeyError, ValueError):
            return "<a>"
        return '<a href="%s" target="_blank" rel="noopener">' % escape(driver.get_absolute_url())

    @classmethod
    def extract_references(cls, attrs):
        yield Driver, attrs["id"], "", ""


class TeamLinkHandler(LinkHandler):
    """<a linktype="team" id="7"> -> реальный URL при рендере."""
    identifier = "team"

    @staticmethod
    def get_model():
        return Team

    @classmethod
    def expand_db_attributes(cls, attrs):
        try:
            team = Team.objects.get(id=attrs["id"])
        except (Team.DoesNotExist, KeyError, ValueError):
            return "<a>"
        return '<a href="%s" target="_blank" rel="noopener">' % escape(team.get_absolute_url())

    @classmethod
    def extract_references(cls, attrs):
        yield Team, attrs["id"], "", ""


class PilotMentionElementHandler(InlineEntityElementHandler):
    """Обратная загрузка <a linktype="driver"> в Draftail-сущность PILOT_MENTION
    при повторном открытии статьи в редакторе."""
    mutability = "MUTABLE"

    def get_attribute_data(self, attrs):
        driver_id = attrs.get("id")
        driver = Driver.objects.filter(id=driver_id).first() if driver_id else None
        return {"id": driver_id, "fullName": driver.full_name if driver else None}


class TeamMentionElementHandler(InlineEntityElementHandler):
    """Обратная загрузка <a linktype="team"> в Draftail-сущность TEAM_MENTION
    при повторном открытии статьи в редакторе."""
    mutability = "MUTABLE"

    def get_attribute_data(self, attrs):
        team_id = attrs.get("id")
        team = Team.objects.filter(id=team_id).first() if team_id else None
        return {"id": team_id, "name": team.name if team else None}


def pilot_mention_entity(props):
    return DOM.create_element("a", {"linktype": "driver", "id": props["id"]}, props["children"])


def team_mention_entity(props):
    return DOM.create_element("a", {"linktype": "team", "id": props["id"]}, props["children"])


@hooks.register("register_rich_text_features")
def register_pilot_mention_feature(features):
    features.register_link_type(DriverLinkHandler)
    features.register_editor_plugin(
        "draftail", "pilot_mention",
        draftail_features.EntityFeature(
            {
                "type": "PILOT_MENTION",
                "icon": "user",
                "description": "Упомянуть пилота",
                "attributes": ["id", "fullName"],
            },
            js=["website/js/driver-search.js", "website/js/pilot-mention.js"],
            css={"all": ["website/css/mention.css"]},
        ),
    )
    features.register_converter_rule("contentstate", "pilot_mention", {
        "from_database_format": {
            'a[linktype="driver"]': PilotMentionElementHandler("PILOT_MENTION"),
        },
        "to_database_format": {
            "entity_decorators": {"PILOT_MENTION": pilot_mention_entity},
        },
    })
    # Сознательно НЕ в features.default_features — строго opt-in.


@hooks.register("register_rich_text_features")
def register_team_mention_feature(features):
    features.register_link_type(TeamLinkHandler)
    features.register_editor_plugin(
        "draftail", "team_mention",
        draftail_features.EntityFeature(
            {
                "type": "TEAM_MENTION",
                "icon": "group",
                "description": "Упомянуть команду",
                "attributes": ["id", "name"],
            },
            js=["website/js/team-search.js", "website/js/team-mention.js"],
            css={"all": ["website/css/mention.css"]},
        ),
    )
    features.register_converter_rule("contentstate", "team_mention", {
        "from_database_format": {
            'a[linktype="team"]': TeamMentionElementHandler("TEAM_MENTION"),
        },
        "to_database_format": {
            "entity_decorators": {"TEAM_MENTION": team_mention_entity},
        },
    })
    # Сознательно НЕ в features.default_features — строго opt-in.


@hooks.register("insert_editor_js")
def mention_markdown_js():
    """Автокомплит пилотов/команд для markdown-блока ArticlePage.body
    (EasyMDE, не Draftail — своя реализация, см. website/static/website/js/
    mention-markdown.js). Хук срабатывает на каждой странице редактирования
    (как кнопка "Отправить в Telegram" выше), но безвреден там, где
    .codemirror-инстанса нет — просто ничего не находит."""
    return format_html(
        '<script src="{}"></script><script src="{}"></script><script src="{}"></script>'
        '<link rel="stylesheet" href="{}">',
        static("website/js/driver-search.js"),
        static("website/js/team-search.js"),
        static("website/js/mention-markdown.js"),
        static("website/css/mention.css"),
    )
