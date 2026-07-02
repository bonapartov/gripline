import csv
import io
from django import forms
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import Driver, Team, RaceResult, Chassis

SESSION_CONFIGS = {
    'qual': {
        'label': 'Квалификация',
        'hint': 'first_name, last_name, position, best_lap, s1, s2, s3',
        'has_timing': True,
        'has_start_position': False,
        'has_team_chassis': False,
    },
    'pre_final': {
        'label': 'Предфинал',
        'hint': 'first_name, last_name, start_position, position, best_lap, s1, s2, s3',
        'has_timing': True,
        'has_start_position': True,
        'has_team_chassis': False,
    },
    'final': {
        'label': 'Финал (хронометраж)',
        'hint': 'first_name, last_name, start_position, position, best_lap, s1, s2, s3',
        'has_timing': True,
        'has_start_position': True,
        'has_team_chassis': False,
    },
    'protocol': {
        'label': 'Протокол судейской комиссии',
        'hint': 'first_name, last_name, city, team_name, race_number, chassis, position, points',
        'has_timing': False,
        'has_start_position': False,
        'has_team_chassis': True,
    },
}

# Все скрытые поля передаваемые через форму предпросмотра
HIDDEN_FIELDS = [
    'first_name', 'last_name', 'city', 'team_name', 'race_number', 'chassis',
    'position', 'points', 'start_position', 'best_lap', 's1', 's2', 's3',
]


def seconds_to_ms(value_str):
    """Конвертирует '55.420' или '0:55.420' или '1:06.640' → мс"""
    if not value_str:
        return None
    try:
        s = str(value_str).strip().replace(',', '.')
        if ':' in s:
            minutes, seconds = s.split(':', 1)
            return int(round((int(minutes) * 60 + float(seconds)) * 1000))
        return int(round(float(s) * 1000))
    except (ValueError, AttributeError, IndexError):
        return None


class CSVUploadForm(forms.Form):
    csv_file = forms.FileField(label="Выберите CSV-файл")
    race_class_group = forms.ChoiceField(
        label="Класс заезда",
        choices=[],
        required=True
    )
    session_type = forms.ChoiceField(
        label="Тип загрузки",
        choices=[(k, v['label']) for k, v in SESSION_CONFIGS.items()],
        required=True,
        initial='protocol',
    )

    def __init__(self, *args, **kwargs):
        group_choices = kwargs.pop('group_choices', [])
        super().__init__(*args, **kwargs)
        self.fields['race_class_group'].choices = group_choices


class PreviewChoiceField(forms.ChoiceField):
    def __init__(self, choices, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.choices = choices
        self.widget.attrs.update({'class': 'form-select form-select-sm'})


class PreviewForm(forms.Form):
    def __init__(self, *args, **kwargs):
        rows_data = kwargs.pop('rows_data', [])
        super().__init__(*args, **kwargs)

        for idx, row in enumerate(rows_data):
            field_name = f'driver_{idx}'
            choices = [('', '--- Выберите пилота ---')]
            for driver in row.get('found_drivers', []):
                label = f"{driver.full_name} (ID:{driver.id}) - {driver.city or 'город не указан'}"
                choices.append((driver.id, label))
            choices.append(('new', '✚ Создать нового пилота'))

            self.fields[field_name] = PreviewChoiceField(
                choices=choices,
                required=True,
                initial=row.get('selected_driver_id'),
                label=f"Строка {idx+1}: {row['first_name']} {row['last_name']}"
            )

            self.fields[f'team_{idx}'] = forms.CharField(required=False, widget=forms.HiddenInput)
            self.fields[f'chassis_{idx}'] = forms.CharField(required=False, widget=forms.HiddenInput)

            for key in HIDDEN_FIELDS:
                if key in row:
                    self.fields[f'{key}_{idx}'] = forms.CharField(
                        initial=row.get(key, ''),
                        widget=forms.HiddenInput,
                        required=False
                    )


def find_drivers(first_name, last_name, city=None):
    found_drivers = []
    selected_id = None

    if first_name and last_name:
        drivers = Driver.objects.filter(
            first_name__iexact=first_name,
            last_name__iexact=last_name
        )
        if drivers.count() == 1:
            selected_id = drivers.first().id
            found_drivers = list(drivers)
        elif drivers.count() > 1:
            if city:
                drivers_by_city = drivers.filter(city__iexact=city)
                if drivers_by_city.count() == 1:
                    selected_id = drivers_by_city.first().id
                    found_drivers = list(drivers_by_city)
                else:
                    found_drivers = list(drivers)
            else:
                found_drivers = list(drivers)

    return found_drivers, selected_id


@require_POST
def import_add_driver(request):
    """AJAX: быстро создать пилота прямо со страницы предпросмотра импорта."""
    first_name = request.POST.get('first_name', '').strip()
    last_name = request.POST.get('last_name', '').strip()
    city = request.POST.get('city', '').strip()

    if not first_name or not last_name:
        return JsonResponse({'error': 'Укажите имя и фамилию'}, status=400)

    driver = Driver.objects.filter(
        first_name__iexact=first_name,
        last_name__iexact=last_name,
    ).first()

    if not driver:
        driver = Driver.objects.create(
            first_name=first_name,
            last_name=last_name,
            city=city or None,
        )

    return JsonResponse({
        'id': driver.id,
        'full_name': driver.full_name,
        'city': driver.city or '',
    })


def import_results(request, page_id=None):
    from .models import EventPage

    try:
        page = EventPage.objects.get(id=page_id)
    except EventPage.DoesNotExist:
        messages.error(request, 'Страница не найдена')
        return redirect('wagtailadmin_home')

    groups = page.race_class_groups.all()
    group_choices = [(g.id, str(g)) for g in groups]

    if request.method == 'POST' and 'upload' in request.POST:
        form = CSVUploadForm(request.POST, request.FILES, group_choices=group_choices)
        if form.is_valid():
            group_id = form.cleaned_data['race_class_group']
            session_type = form.cleaned_data['session_type']
            csv_file = request.FILES['csv_file']

            decoded_file = csv_file.read().decode('utf-8-sig')
            io_string = io.StringIO(decoded_file)
            reader = csv.DictReader(io_string, delimiter=',')
            rows = list(reader)

            request.session['import_rows'] = rows
            request.session['import_group_id'] = group_id
            request.session['import_page_id'] = page.id
            request.session['import_session_type'] = session_type

            return redirect('event_import_preview')
    else:
        form = CSVUploadForm(group_choices=group_choices)

    return render(request, 'admin/event_import.html', {
        'form': form,
        'page': page,
        'session_configs_json': {k: v['hint'] for k, v in SESSION_CONFIGS.items()},
    })


def import_preview(request):
    rows = request.session.get('import_rows', [])
    session_type = request.session.get('import_session_type', 'protocol')
    cfg = SESSION_CONFIGS.get(session_type, SESSION_CONFIGS['protocol'])

    if not rows:
        messages.error(request, 'Сессия истекла')
        return redirect('wagtailadmin_home')

    preview_rows = []
    for row in rows:
        if not row.get('first_name') or not row.get('last_name'):
            continue

        first_name = row.get('first_name', '').strip()
        last_name = row.get('last_name', '').strip()
        city = row.get('city', '').strip()
        team_name = row.get('team_name', '').strip()
        chassis_name = row.get('chassis', '').strip()

        team_obj = None
        team_exists = False
        if cfg['has_team_chassis'] and team_name:
            team_obj = Team.objects.filter(name__iexact=team_name).first()
            team_exists = team_obj is not None

        chassis_obj = None
        chassis_exists = False
        if cfg['has_team_chassis'] and chassis_name:
            chassis_obj = Chassis.objects.filter(name__iexact=chassis_name).first()
            chassis_exists = chassis_obj is not None

        found_drivers, selected_id = find_drivers(first_name, last_name, city or None)

        preview_rows.append({
            'first_name': first_name,
            'last_name': last_name,
            'city': city,
            'team_name': team_name,
            'team_exists': team_exists,
            'team_id': team_obj.id if team_obj else None,
            'chassis': chassis_name,
            'chassis_exists': chassis_exists,
            'chassis_id': chassis_obj.id if chassis_obj else None,
            'race_number': row.get('race_number', ''),
            'position': row.get('position', ''),
            'points': row.get('points', ''),
            'start_position': row.get('start_position', ''),
            'best_lap': row.get('best_lap', ''),
            's1': row.get('s1', ''),
            's2': row.get('s2', ''),
            's3': row.get('s3', ''),
            'found_drivers': found_drivers,
            'selected_driver_id': selected_id,
        })

    if request.method == 'POST':
        form = PreviewForm(request.POST, rows_data=preview_rows)
        if form.is_valid():
            selections = []
            group_id = request.session.get('import_group_id')

            for idx in range(len(preview_rows)):
                driver_id = form.cleaned_data.get(f'driver_{idx}')
                row_data = {'selected_driver_id': driver_id, 'group_id': group_id}
                for key in HIDDEN_FIELDS:
                    row_data[key] = form.cleaned_data.get(f'{key}_{idx}', '')
                row_data['team_id'] = form.cleaned_data.get(f'team_{idx}', '')
                row_data['chassis_id'] = form.cleaned_data.get(f'chassis_{idx}', '')
                selections.append(row_data)

            request.session['import_selections'] = selections
            request.session['import_session_type'] = session_type
            return redirect('event_import_confirm')
        else:
            messages.error(request, 'Форма содержит ошибки. Проверьте выбор пилота для всех строк.')
    else:
        form = PreviewForm(rows_data=preview_rows)

    return render(request, 'admin/import_preview.html', {
        'form': form,
        'rows': preview_rows,
        'session_type': session_type,
        'session_label': cfg['label'],
        'cfg': cfg,
    })


def _build_defaults(row, session_type, team, chassis_obj):
    """Строит словарь defaults для update_or_create в зависимости от типа сессии."""
    s = session_type

    def pos(field):
        val = row.get(field, '')
        if val == '' or val is None:
            return None
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return None

    if s == 'qual':
        return {
            'qual_position': pos('position'),
            'qual_best_lap_ms': seconds_to_ms(row.get('best_lap')),
            'qual_s1_ms': seconds_to_ms(row.get('s1')),
            'qual_s2_ms': seconds_to_ms(row.get('s2')),
            'qual_s3_ms': seconds_to_ms(row.get('s3')),
        }
    elif s == 'pre_final':
        return {
            'pre_final_position': pos('position'),
            'pre_final_start_pos': pos('start_position'),
            'pre_final_best_lap_ms': seconds_to_ms(row.get('best_lap')),
            'pre_final_s1_ms': seconds_to_ms(row.get('s1')),
            'pre_final_s2_ms': seconds_to_ms(row.get('s2')),
            'pre_final_s3_ms': seconds_to_ms(row.get('s3')),
        }
    elif s == 'final':
        return {
            'start_position': pos('start_position'),
            'position': pos('position') or 0,
            'best_lap_ms': seconds_to_ms(row.get('best_lap')),
            'best_s1_ms': seconds_to_ms(row.get('s1')),
            'best_s2_ms': seconds_to_ms(row.get('s2')),
            'best_s3_ms': seconds_to_ms(row.get('s3')),
        }
    else:  # protocol
        defaults = {
            'position': pos('position') or 0,
            'team': team,
            'race_number': row.get('race_number', '') or None,
            'chassis_new': chassis_obj,
        }
        points_str = row.get('points', '')
        if points_str:
            try:
                defaults['points'] = float(str(points_str).replace(',', '.'))
            except (ValueError, TypeError):
                defaults['points'] = 0
        else:
            defaults['points'] = 0
        return defaults


def import_confirm(request):
    if request.method != 'POST':
        selections = request.session.get('import_selections', [])
        session_type = request.session.get('import_session_type', 'protocol')
        cfg = SESSION_CONFIGS.get(session_type, SESSION_CONFIGS['protocol'])
        return render(request, 'admin/import_confirm.html', {
            'selections': selections,
            'session_type': session_type,
            'session_label': cfg['label'],
            'cfg': cfg,
        })

    selections = request.session.get('import_selections', [])
    session_type = request.session.get('import_session_type', 'protocol')

    if not selections:
        messages.error(request, 'Сессия истекла. Начните импорт заново.')
        return redirect('wagtailadmin_home')

    page_id = request.session.get('import_page_id')
    created_count = 0
    updated_count = 0
    error_count = 0
    errors = []

    for row in selections:
        try:
            driver_id = row.get('selected_driver_id')
            group_id = row.get('group_id') or request.session.get('import_group_id')

            if driver_id == 'new':
                driver = Driver.objects.create(
                    first_name=row['first_name'],
                    last_name=row['last_name'],
                    city=row.get('city', '') or None
                )
            elif driver_id:
                driver = Driver.objects.get(id=driver_id)
            else:
                driver = Driver.objects.create(
                    first_name=row['first_name'],
                    last_name=row['last_name'],
                    city=row.get('city', '') or None
                )

            # Команда и шасси нужны только для протокола
            team = None
            chassis_obj = None
            if session_type == 'protocol':
                team_id = row.get('team_id', '')
                if team_id and str(team_id).isdigit():
                    try:
                        team = Team.objects.get(id=team_id)
                    except Team.DoesNotExist:
                        if row.get('team_name'):
                            team = Team.objects.filter(name__iexact=row['team_name'].strip()).first()
                            if not team:
                                raise Exception(f"Команда '{row['team_name']}' не найдена в базе.")
                elif row.get('team_name'):
                    team = Team.objects.filter(name__iexact=row['team_name'].strip()).first()
                    if not team:
                        raise Exception(f"Команда '{row['team_name']}' не найдена в базе.")

                chassis_id = row.get('chassis_id', '')
                if chassis_id and str(chassis_id).isdigit():
                    try:
                        chassis_obj = Chassis.objects.get(id=chassis_id)
                    except Chassis.DoesNotExist:
                        if row.get('chassis'):
                            chassis_obj = Chassis.objects.filter(name__iexact=row['chassis'].strip()).first()
                            if not chassis_obj:
                                raise Exception(f"Шасси '{row['chassis']}' не найдено в базе.")
                elif row.get('chassis'):
                    chassis_obj = Chassis.objects.filter(name__iexact=row['chassis'].strip()).first()
                    if not chassis_obj:
                        raise Exception(f"Шасси '{row['chassis']}' не найдено в базе.")

            defaults = _build_defaults(row, session_type, team, chassis_obj)

            if session_type == 'protocol':
                result, created = RaceResult.objects.update_or_create(
                    group_id=group_id,
                    driver=driver,
                    defaults=defaults,
                )
            else:
                # qual/pre_final/final: не перетирать position если запись уже есть
                result, created = RaceResult.objects.get_or_create(
                    group_id=group_id,
                    driver=driver,
                    defaults={'position': 0, **defaults},
                )
                if not created:
                    for key, val in defaults.items():
                        setattr(result, key, val)
                    result.save()

            if created:
                created_count += 1
            else:
                updated_count += 1

        except Exception as e:
            error_count += 1
            errors.append(str(e))

    for key in ['import_rows', 'import_group_id', 'import_page_id', 'import_selections', 'import_session_type']:
        request.session.pop(key, None)

    for error in errors:
        messages.error(request, f'Ошибка: {error}')

    cfg = SESSION_CONFIGS.get(session_type, SESSION_CONFIGS['protocol'])
    messages.success(
        request,
        f'Импорт [{cfg["label"]}] завершён. Создано: {created_count}, Обновлено: {updated_count}, Ошибок: {error_count}'
    )

    if page_id:
        return redirect('wagtailadmin_pages:edit', page_id)
    else:
        from django.urls import reverse
        return redirect(reverse('admin:website_raceresult_changelist'))
