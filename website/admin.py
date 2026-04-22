from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from .models import RaceResult, Driver, Team, RaceClassResultGroup, DriverResource, Chassis
from django.urls import path
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.core.management import call_command
from django.shortcuts import render
from django.utils.html import format_html
import io
import sys
from datetime import datetime

# ============= АНАЛИТИЧЕСКАЯ ПАНЕЛЬ =============
@staff_member_required
def analytics_dashboard(request):
    context = {}

    # Статистика
    from .models import Driver, Chassis, RaceResult
    context['total_pilots'] = Driver.objects.count()
    context['total_chassis'] = Chassis.objects.count()
    context['total_races'] = RaceResult.objects.count()

    # Последнее обновление из БД
    from website.models import AnalyticsMetadata
    try:
        last_update_obj = AnalyticsMetadata.objects.get(key='last_updated')
        last_update = last_update_obj.value.strftime('%d.%m.%Y %H:%M')
    except AnalyticsMetadata.DoesNotExist:
        last_update = '—'

    context['last_update'] = last_update

    if request.method == 'POST':
        output = io.StringIO()
        error_output = io.StringIO()

        try:
            sys.stdout = output
            sys.stderr = error_output

            call_command('update_ratings', '--entity', 'all', '--model', 'all', '--alpha', '0.1')

            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__

            context['success'] = True
            context['output'] = output.getvalue()

            messages.success(request, "✅ Все рейтинги успешно обновлены!")

        except Exception as e:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__

            context['error'] = True
            context['error_message'] = str(e)
            context['error_output'] = error_output.getvalue()
            context['output'] = output.getvalue()

            messages.error(request, f"❌ Ошибка при обновлении: {str(e)}")

    return render(request, 'admin/analytics_dashboard.html', context)

# ============= УМНЫЕ ВИДЖЕТЫ ДЛЯ ИМПОРТА =============
class SmartDriverWidget(ForeignKeyWidget):
    def get_queryset(self, value, row, *args, **kwargs):
        first_name = str(row.get('first_name', '')).strip()
        last_name = str(row.get('last_name', '')).strip()
        city = str(row.get('city', '')).strip()

        if not first_name or not last_name:
            return self.model.objects.none()

        qs = self.model.objects.filter(
            first_name__iexact=first_name,
            last_name__iexact=last_name
        )

        if qs.count() > 1 and city:
            qs_city = qs.filter(city__iexact=city)
            if qs_city.count() == 1:
                return qs_city

        return qs

    def clean(self, value, row=None, **kwargs):
        first_name = str(row.get('first_name', '')).strip()
        last_name = str(row.get('last_name', '')).strip()
        city = str(row.get('city', '')).strip()

        obj = self.get_queryset(value, row)

        if obj.count() > 1:
            raise Exception(f"Конфликт: найдено несколько пилотов {first_name} {last_name}. Уточните город или исправьте вручную.")

        if obj.count() == 1:
            return obj.first()

        if not obj.exists() and first_name and last_name:
            new_driver = Driver.objects.create(
                first_name=first_name,
                last_name=last_name,
                city=city
            )
            print(f"--- Создан новый пилот: {new_driver} ---")
            return new_driver

        return None

class SmartTeamWidget(ForeignKeyWidget):
    def clean(self, value, row=None, **kwargs):
        name = str(row.get('team_name', '')).strip()
        if not name:
            return None

        try:
            team = Team.objects.get(name=name)
            return team
        except Team.DoesNotExist:
            raise Exception(f"Команда '{name}' не найдена в базе. Создание новых команд запрещено.")

class SmartChassisWidget(ForeignKeyWidget):
    def clean(self, value, row=None, **kwargs):
        name = str(row.get('chassis', '')).strip()
        if not name:
            return None

        try:
            chassis = Chassis.objects.get(name=name)
            return chassis
        except Chassis.DoesNotExist:
            raise Exception(f"Шасси '{name}' не найдено в базе. Создание новых шасси запрещено.")

# ============= РЕСУРС ДЛЯ ИМПОРТА =============
class RaceResultResource(resources.ModelResource):
    first_name = fields.Field(column_name='first_name', attribute='driver__first_name')
    city = fields.Field(column_name='city', attribute='driver__city')

    driver = fields.Field(
        column_name='last_name',
        attribute='driver',
        widget=SmartDriverWidget(Driver, 'last_name')
    )
    team = fields.Field(
        column_name='team_name',
        attribute='team',
        widget=SmartTeamWidget(Team, 'name')
    )
    group = fields.Field(
        column_name='group_id',
        attribute='group',
        widget=ForeignKeyWidget(RaceClassResultGroup, 'id')
    )
    chassis = fields.Field(
        column_name='chassis',
        attribute='chassis',
        widget=SmartChassisWidget(Chassis, 'name')
    )

    class Meta:
        model = RaceResult
        fields = ('id', 'group', 'first_name', 'last_name', 'city', 'team', 'race_number', 'chassis', 'position', 'points')
        import_id_fields = []
        skip_unchanged = True
        report_skipped = True

# ============= РЕГИСТРАЦИЯ МОДЕЛЕЙ =============
@admin.register(RaceResult)
class RaceResultAdmin(ImportExportModelAdmin):
    resource_class = RaceResultResource
    list_display = ('position', 'driver', 'team', 'points', 'group')
    list_filter = ('group__page', 'group__race_class')
    search_fields = ('driver__first_name', 'driver__last_name', 'team__name')

# ============= ДОБАВЛЯЕМ URL ДЛЯ АНАЛИТИКИ =============
def get_extra_urls():
    return [
        path('analytics/', analytics_dashboard, name='analytics_dashboard'),
    ]

# Переопределяем стандартное меню
original_get_app_list = admin.site.get_app_list

def get_app_list_with_analytics(self, request):
    app_list = original_get_app_list(self, request)

    app_list.append({
        'name': 'Аналитика',
        'app_label': 'analytics',
        'models': [{
            'name': 'Обновление рейтингов',
            'object_name': 'analytics_dashboard',
            'admin_url': '/admin/analytics/',
            'view_only': True,
        }]
    })
    return app_list

admin.site.get_app_list = get_app_list_with_analytics.__get__(admin.site)

# Добавляем URL
original_get_urls = admin.site.get_urls

def get_urls_with_analytics():
    urls = original_get_urls()
    return get_extra_urls() + urls

admin.site.get_urls = get_urls_with_analytics

from .models import TeamStaff, TeamStaffMembership

@admin.register(TeamStaff)
class TeamStaffAdmin(admin.ModelAdmin):
    list_display = ('last_name', 'first_name', 'position', 'phone', 'email')
    list_filter = ('position',)
    search_fields = ('last_name', 'first_name', 'position', 'phone', 'email')
    fieldsets = (
        ('Основная информация', {
            'fields': ('last_name', 'first_name', 'middle_name', 'slug', 'photo')
        }),
        ('Должность и контакты', {
            'fields': ('position', 'biography', 'phone', 'email')
        }),
    )

@admin.register(TeamStaffMembership)
class TeamStaffMembershipAdmin(admin.ModelAdmin):
    list_display = ('staff', 'team', 'is_active', 'joined_at', 'left_at')
    list_filter = ('is_active', 'team')
    search_fields = ('staff__last_name', 'staff__first_name', 'team__name')
