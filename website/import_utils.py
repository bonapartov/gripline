import csv
import io
from django import forms
from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Driver, Team, RaceResult, Chassis

class CSVUploadForm(forms.Form):
    csv_file = forms.FileField(label="Выберите CSV-файл")
    race_class_group = forms.ChoiceField(
        label="Класс заезда",
        choices=[],  # Будут заполнены динамически
        required=True
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
            # Поле для пилота
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

            # Добавляем поля для команды и шасси (ID)
            self.fields[f'team_{idx}'] = forms.CharField(
                required=False,
                widget=forms.HiddenInput
            )
            self.fields[f'chassis_{idx}'] = forms.CharField(
                required=False,
                widget=forms.HiddenInput
            )

            # Скрытые поля с данными
            for key in ['first_name', 'last_name', 'city', 'team_name',
                       'race_number', 'chassis', 'position', 'points']:
                if key in row:
                    self.fields[f'{key}_{idx}'] = forms.CharField(
                        initial=row[key],
                        widget=forms.HiddenInput,
                        required=False
                    )

def find_drivers(first_name, last_name, city, team_name):
    """Поиск пилотов по разным критериям"""
    found_drivers = []
    selected_id = None

    print(f"Поиск: {first_name} {last_name}, {city}, {team_name}")

    # Простой поиск по имени и фамилии
    if first_name and last_name:
        drivers = Driver.objects.filter(
            first_name__iexact=first_name,
            last_name__iexact=last_name
        )
        print(f"Найдено пилотов: {drivers.count()}")

        if drivers.count() == 1:
            selected_id = drivers.first().id
            found_drivers = list(drivers)
        elif drivers.count() > 1:
            found_drivers = list(drivers)

    return found_drivers, selected_id

def import_results(request, page_id=None):
    """Основная функция импорта"""
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
            csv_file = request.FILES['csv_file']

            decoded_file = csv_file.read().decode('utf-8-sig')
            io_string = io.StringIO(decoded_file)
            reader = csv.DictReader(io_string, delimiter=',')

            rows = list(reader)

            request.session['import_rows'] = rows
            request.session['import_group_id'] = group_id
            request.session['import_page_id'] = page.id

            return redirect('event_import_preview')

    else:
        form = CSVUploadForm(group_choices=group_choices)

    return render(request, 'admin/event_import.html', {
        'form': form,
        'page': page,
    })

def import_preview(request):
    """Предпросмотр импорта"""
    print("\n" + "="*50)
    print("НАЧАЛО import_preview")
    print("REQUEST METHOD:", request.method)

    rows = request.session.get('import_rows', [])
    print(f"Строк в сессии: {len(rows)}")

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

        team_exists = False
        team_obj = None
        if team_name:
            team_obj = Team.objects.filter(name__iexact=team_name).first()
            team_exists = team_obj is not None

        chassis_exists = False
        chassis_obj = None
        if chassis_name:
            chassis_obj = Chassis.objects.filter(name__iexact=chassis_name).first()
            chassis_exists = chassis_obj is not None

        found_drivers = []
        selected_id = None

        print(f"\n=== ПОИСК: '{first_name}' '{last_name}' ===")
        drivers = Driver.objects.filter(
            first_name__iexact=first_name,
            last_name__iexact=last_name
        )
        print(f"Найдено: {drivers.count()}")

        if drivers.count() == 1:
            selected_id = drivers.first().id
            found_drivers = list(drivers)
            print(f"Выбран пилот ID {selected_id}")
        elif drivers.count() > 1:
            print(f"Найдено несколько:")
            for d in drivers:
                print(f"  - {d.first_name} {d.last_name}, город: {d.city}")

            if city:
                drivers_by_city = drivers.filter(city__iexact=city)
                print(f"По городу '{city}': {drivers_by_city.count()}")
                if drivers_by_city.count() == 1:
                    selected_id = drivers_by_city.first().id
                    found_drivers = list(drivers_by_city)
                    print(f"Выбран по городу ID {selected_id}")
                else:
                    found_drivers = list(drivers)
            else:
                found_drivers = list(drivers)
        else:
            print("Пилот НЕ НАЙДЕН в базе")

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
            'found_drivers': found_drivers,
            'selected_driver_id': selected_id,
        })

    if request.method == 'POST':
        print("POST data keys:", request.POST.keys())
        print("Raw POST data:", dict(request.POST))

        form = PreviewForm(request.POST, rows_data=preview_rows)
        print("Form errors:", form.errors)

        if form.is_valid():
            selections = []
            group_id = request.session.get('import_group_id')

            for idx in range(len(preview_rows)):
                driver_id = form.cleaned_data.get(f'driver_{idx}')
                print(f"Строка {idx}, driver_id: {driver_id}")

                row_data = {}
                for key in ['first_name', 'last_name', 'city', 'team_name',
                           'race_number', 'chassis', 'position', 'points']:
                    row_data[key] = form.cleaned_data.get(f'{key}_{idx}')
                row_data['selected_driver_id'] = driver_id
                row_data['group_id'] = group_id
                selections.append(row_data)

            request.session['import_selections'] = selections
            return redirect('event_import_confirm')
        else:
            print("Форма НЕ валидна!")
            print("Form errors:", form.errors)
            messages.error(request, 'Форма содержит ошибки. Проверьте выбор пилота для всех строк.')
    else:
        form = PreviewForm(rows_data=preview_rows)

    return render(request, 'admin/import_preview.html', {
        'form': form,
        'rows': preview_rows,
    })

def import_confirm(request):
    """Подтверждение импорта"""
    if request.method != 'POST':
        selections = request.session.get('import_selections', [])
        return render(request, 'admin/import_confirm.html', {
            'selections': selections,
        })

    selections = request.session.get('import_selections', [])
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

            # Получаем команду по ID (если выбран)
            team = None
            team_id = row.get('team_id')
            if team_id and team_id.isdigit():
                try:
                    team = Team.objects.get(id=team_id)
                except Team.DoesNotExist:
                    # Если ID не найден, пробуем по названию (для обратной совместимости)
                    if row.get('team_name'):
                        team_name = row['team_name'].strip()
                        try:
                            team = Team.objects.get(name__iexact=team_name)
                        except Team.DoesNotExist:
                            raise Exception(f"Команда '{team_name}' не найдена в базе.")
            elif row.get('team_name'):
                # Если ID нет, но есть название — пробуем найти по нему
                team_name = row['team_name'].strip()
                try:
                    team = Team.objects.get(name__iexact=team_name)
                except Team.DoesNotExist:
                    raise Exception(f"Команда '{team_name}' не найдена в базе.")

            # Получаем шасси по ID (если выбран)
            chassis_obj = None
            chassis_id = row.get('chassis_id')
            if chassis_id and chassis_id.isdigit():
                try:
                    chassis_obj = Chassis.objects.get(id=chassis_id)
                except Chassis.DoesNotExist:
                    # Если ID не найден, пробуем по названию
                    if row.get('chassis'):
                        chassis_name = row['chassis'].strip()
                        try:
                            chassis_obj = Chassis.objects.get(name__iexact=chassis_name)
                        except Chassis.DoesNotExist:
                            raise Exception(f"Шасси '{chassis_name}' не найдено в базе.")
            elif row.get('chassis'):
                # Если ID нет, но есть название — пробуем найти по нему
                chassis_name = row['chassis'].strip()
                try:
                    chassis_obj = Chassis.objects.get(name__iexact=chassis_name)
                except Chassis.DoesNotExist:
                    raise Exception(f"Шасси '{chassis_name}' не найдено в базе.")
            result, created = RaceResult.objects.update_or_create(
                group_id=group_id,
                driver=driver,
                defaults={
                    'team': team,
                    'race_number': row.get('race_number', '') or None,
                    'chassis_new': chassis_obj,
                    'position': int(float(row['position'])) if row['position'] else 0,
                    'points': float(row['points'].replace(',', '.')) if row['points'] else 0,
                }
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        except Exception as e:
            error_count += 1
            errors.append(str(e))

    for key in ['import_rows', 'import_group_id', 'import_page_id', 'import_selections']:
        if key in request.session:
            del request.session[key]

    if errors:
        for error in errors:
            messages.error(request, f'Ошибка: {error}')

    messages.success(request, f'Импорт завершен. Создано: {created_count}, Обновлено: {updated_count}, Ошибок: {error_count}')

    if page_id:
        return redirect('wagtailadmin_pages:edit', page_id)
    else:
        from django.urls import reverse
        return redirect(reverse('admin:website_raceresult_changelist'))
