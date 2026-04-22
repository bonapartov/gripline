from wagtail_modeladmin.options import (ModelAdmin, ModelAdminGroup, modeladmin_register)
from .models import Driver, Team, Track, Chassis, TyreBrand, TyreType, Tyre, Engine, TeamStaff, TeamStaffMembership
from wagtail import hooks
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.urls import path, reverse
from .import_utils import import_results, import_preview, import_confirm
from wagtail.admin.menu import MenuItem
from .admin_views import analytics_dashboard

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

# Регистрируем группы
modeladmin_register(PilotsGroup)
modeladmin_register(TeamsGroup)
modeladmin_register(EquipmentGroup)
modeladmin_register(TyresGroup)
modeladmin_register(TracksGroup)

@hooks.register('register_admin_urls')
def register_import_urls():
    return [
        path('event/<int:page_id>/import/', import_results, name='event_import'),
        path('import/preview/', import_preview, name='event_import_preview'),
        path('import/confirm/', import_confirm, name='event_import_confirm'),
        path('analytics/', analytics_dashboard, name='analytics_dashboard'),
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
        </style>
    """)

@hooks.register('insert_global_admin_js')
def insert_admin_js():
    return mark_safe("""
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // === ИМПОРТ РЕЗУЛЬТАТОВ И БЕЙДЖИ ===
            setTimeout(function() {
                const header = document.querySelector('header');
                if (header && window.location.pathname.includes('/edit/')) {
                    const pageId = window.location.pathname.split('/')[3];
                    if (pageId && !isNaN(pageId)) {
                        const button = document.createElement('a');
                        button.href = '/admin/event/' + pageId + '/import/';
                        button.className = 'button bicolor icon icon-download import-button';
                        button.innerHTML = 'Импорт результатов';
                        const actions = header.querySelector('.actions');
                        if (actions) {
                            actions.appendChild(button);
                        } else {
                            header.appendChild(button);
                        }
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
