"""Начальное наполнение «Советов по шасси» (12.10.2026).

Какой симптом к какой регулировке ведёт — по разбору Kart Chassis Setup Pro 1.4.1 (только логика,
см. docs/chassis_analysis_rules.md в репозитории приложения). Тексты «почему» — свои. Дальше всё правится
в админке («Приложение» → «Советы по шасси»); миграция не трогает уже существующие советы.
"""
from django.db import migrations

# код: (что сделать, почему, поле, действие, значение)
ADVICES = {
    'narrow_rear_track': ('Сузить заднюю колею',
        'Узкая задняя колея сильнее разгружает внутреннее заднее колесо в повороте: зад держит меньше, '
        'карт охотнее поворачивает.', 'track_width_rear_cm', 'dec', ''),
    'widen_rear_track': ('Расширить заднюю колею',
        'Широкая задняя колея меньше разгружает внутреннее заднее колесо: зад становится спокойнее, '
        'подскоков меньше.', 'track_width_rear_cm', 'inc', ''),
    'widen_front_track': ('Расширить переднюю колею',
        'Шире передок — длиннее рычаг передних колёс: при повороте руля зад поднимается сильнее, '
        'карт легче входит в поворот.', 'track_width_front_cm', 'inc', ''),
    'narrow_front_track': ('Сузить переднюю колею',
        'Узкий передок меньше поднимает внутреннее заднее колесо и мягче реагирует на руль.',
        'track_width_front_cm', 'dec', ''),
    'install_front_torsion': ('Поставить передний стабилизатор',
        'Стабилизатор делает переднюю часть рамы жёстче: нагрузка на передние колёса приходит быстрее.',
        'torsion_front', '', ''),
    'remove_front_torsion': ('Снять передний стабилизатор',
        'Без стабилизатора передок мягче и меньше цепляется — меньше заноса на входе.',
        'torsion_front', 'set', 'Нет'),
    'install_rear_torsion': ('Поставить задний стабилизатор',
        'Задний стабилизатор добавляет жёсткости раме сзади: зад реагирует быстрее и держит увереннее.',
        'torsion_rear', '', ''),
    'remove_rear_torsion': ('Снять задний стабилизатор',
        'Рама сзади становится мягче, внутреннее заднее колесо поднимается легче, подскоков меньше.',
        'torsion_rear', 'set', 'Нет'),
    'tighten_front_bumper': ('Затянуть передний бампер',
        'Затянутый бампер добавляет жёсткости передней части рамы — передок цепляется острее.',
        'front_bumper', 'set', 'tight'),
    'loosen_sidepods': ('Ослабить крепления боковых понтонов',
        'Свободные понтоны не добавляют жёсткости раме — зад держит чуть меньше.',
        'sidepods', 'set', 'loose'),
    'ballast_forward': ('Перенести балласт вперёд',
        'Больше веса на передней оси — передние колёса цепляются сильнее.', '', '', ''),
    'ballast_rearward': ('Перенести балласт назад',
        'Больше веса на задней оси — зад держит лучше.', '', '', ''),
    'ballast_up': ('Поднять балласт выше',
        'Высоко расположенный груз сильнее переносит вес в повороте и помогает разгрузить внутреннее '
        'заднее колесо.', '', '', ''),
    'ballast_down': ('Опустить балласт ниже',
        'Низкий центр тяжести — меньше переноса веса, карт устойчивее и не встаёт на два колеса.', '', '', ''),
    'ballast_up_rear': ('Поднять балласт сзади',
        'Груз выше и ближе к задней оси сильнее нагружает внешнее заднее колесо — зад держит лучше.', '', '', ''),
    'ballast_down_rear': ('Опустить балласт сзади',
        'Груз ниже сзади уменьшает перенос веса на заднюю ось и подскоки.', '', '', ''),
    'toe_out_more': ('Больше расхождение передних колёс',
        'Небольшое расхождение делает реакцию на руль острее, особенно на входе в поворот.',
        'toe_mm', 'dec', ''),
    'toe_out_less': ('Меньше расхождение передних колёс',
        'Ближе к нулю — реакция на руль мягче, передок меньше «закусывает».', 'toe_mm', 'inc', ''),
    'camber_more': ('Камбер — на шаг в «+»',
        'Меняет пятно контакта передних шин. Подсказка — температура: внутренний край горячее '
        'наружного — камбер в «+».', 'camber', 'inc', ''),
    'camber_less': ('Камбер — на шаг в «−»',
        'Меняет пятно контакта передних шин. Подсказка — температура: наружный край горячее '
        'внутреннего — камбер в «−».', 'camber', 'dec', ''),
    'caster_more': ('Больше кастер',
        'Больший кастер сильнее поднимает зад при повороте руля — карт острее входит в поворот, руль тяжелее.',
        'caster', 'inc', ''),
    'caster_less': ('Меньше кастер',
        'Меньший кастер меньше поднимает зад — карт спокойнее, руль легче.', 'caster', 'dec', ''),
    'ackermann_more': ('Больше Аккерман',
        'Внутреннее колесо поворачивает сильнее наружного — вход в поворот острее.', 'ackermann', 'inc', ''),
    'ackermann_less': ('Меньше Аккерман',
        'Колёса поворачивают ближе к параллельному — передок мягче, меньше заноса на входе.',
        'ackermann', 'dec', ''),
    'front_higher': ('Поднять переднюю ось',
        'Выше перед — больше переноса веса на передние колёса в повороте.', 'front_height', 'inc', ''),
    'front_lower': ('Опустить переднюю ось',
        'Ниже перед — меняется перенос веса и поведение передка; проверьте по ощущениям пилота.',
        'front_height', 'dec', ''),
    'rear_higher': ('Поднять заднюю ось',
        'Выше зад — меньше подъёма внутреннего заднего колеса, зад держит увереннее.',
        'rear_axle_height', 'inc', ''),
    'rear_lower': ('Опустить заднюю ось',
        'Ниже зад — внутреннее заднее колесо поднимается легче, меньше подскоков.',
        'rear_axle_height', 'dec', ''),
    'heights_higher': ('Поднять переднюю и заднюю ось',
        'Выше центр тяжести — больше переноса веса и сцепления, когда карт скользит всеми колёсами.',
        'heights', 'inc', ''),
    'seat_forward': ('Сдвинуть сиденье вперёд',
        'Больше веса на передних колёсах — передок цепляется сильнее.', 'seat_shift_mm', 'dec', ''),
    'seat_rearward': ('Сдвинуть сиденье назад',
        'Больше веса на задних колёсах — зад держит лучше.', 'seat_shift_mm', 'inc', ''),
    'seat_up': ('Поднять сиденье',
        'Выше центр тяжести — больше переноса веса в повороте и сцепления на скользкой трассе.',
        'seat_raise_mm', 'inc', ''),
    'seat_down': ('Опустить сиденье',
        'Ниже центр тяжести — карт устойчивее, меньше подскоков и отрыва колёс.', 'seat_raise_mm', 'dec', ''),
    'rear_hubs_shorter': ('Короче задние ступицы',
        'Короткая ступица — ось гнётся свободнее, зад держит меньше и меньше подпрыгивает.',
        'hub_width_mm', 'dec', ''),
    'rear_hubs_longer': ('Длиннее задние ступицы',
        'Длинная ступица делает ось жёстче у колеса — зад держит лучше.', 'hub_width_mm', 'inc', ''),
    'front_hubs_longer': ('Длиннее передние ступицы',
        'Длинная передняя ступица добавляет передку сцепления.', 'front_hub_length_mm', 'inc', ''),
    'axle_softer': ('Мягче задняя ось',
        'Мягкая ось легче гнётся — внутреннее колесо поднимается легче, зад держит меньше.',
        'rear_axle_stiffness', 'dec', ''),
    'axle_stiffer': ('Жёстче задняя ось',
        'Жёсткая ось лучше передаёт нагрузку — зад держит увереннее.', 'rear_axle_stiffness', 'inc', ''),
    'seat_struts_remove': ('Снять распорки сиденья',
        'Без распорок рама сзади гибче — зад держит меньше.', 'seat_struts', 'dec', ''),
    'seat_struts_install': ('Поставить распорки сиденья',
        'Распорки делают раму сзади жёстче — зад держит лучше.', 'seat_struts', 'inc', ''),
    'middle_bearing_tighten': ('Затянуть средний подшипник задней оси',
        'Зажатый средний подшипник делает ось жёстче — зад держит лучше.', '', '', ''),
    'rear_pressure_up': ('Поднять давление в задних шинах',
        'Выше давление — шина жёстче и меньше пружинит, подскоков меньше.', '', '', ''),
    'rear_pressure_down': ('Снизить давление в задних шинах',
        'Ниже давление — больше пятно контакта и сцепление сзади.', '', '', ''),
    'all_pressure_down': ('Снизить давление во всех шинах',
        'Больше пятно контакта и быстрее прогрев — больше сцепления, когда карт скользит всеми колёсами.',
        '', '', ''),
    'rainmeister': ('Поставить Rainmeister',
        'Поднимает центр тяжести без перестановки сиденья: на мокрой или холодной трассе это нагружает '
        'внешние колёса и добавляет сцепления.', 'rain_meister', 'set', 'yes'),
    'drive_smooth_steering': ('Плавнее начинать поворот руля',
        'Резкий руль на входе срывает передние шины. Поворачивайте руль плавно и чуть раньше.', '', '', ''),
    'drive_ease_throttle': ('Мягче открывать газ на выходе',
        'Резкий газ разгружает передок — карт выносит наружу. Открывайте газ постепенно, с выпрямлением руля.',
        '', '', ''),
    'drive_less_trail_braking': ('Меньше тормозить в повороте',
        'Торможение в повороте разгружает зад — карт заносит. Тормозите по прямой до поворота.', '', '', ''),
    'drive_turn_in_later': ('Позже входить в поворот',
        'Поздний вход даёт выпрямить траекторию на выходе и раньше открыть газ без заноса.', '', '', ''),
    'drive_fewer_steering': ('Меньше движений рулём',
        'Каждая лишняя коррекция срывает шины. Держите руль спокойно, одной дугой.', '', '', ''),
}

# (симптом, фаза, сила, совет, эффект, балласт[, погода])
_U, _O, _H, _L, _D = 'understeer', 'oversteer', 'hopping', 'lifting', 'drift'
_EN, _MI, _EX, _ANY = 'entry', 'middle', 'exit', 'any'
_W, _M, _S = 'weak', 'medium', 'strong'
JU, JD, FU, FD, RU, RD, DR, OT = ('jacking_up', 'jacking_down', 'front_grip_up', 'front_grip_down',
                                  'rear_grip_up', 'rear_grip_down', 'driving', 'other')


def _rules():
    r = []

    def add(symptom, phase, level, items):
        for it in items:
            code, group, *rest = it
            r.append((symptom, phase, level, code, group, rest[0] if rest else 'any', rest[1] if len(rest) > 1 else 'any'))

    # Недостаточная поворачиваемость
    add(_U, _EN, _W, [('narrow_rear_track', JU), ('install_front_torsion', FU), ('tighten_front_bumper', FU),
                      ('ballast_forward', FU, 'low'), ('toe_out_more', FU)])
    add(_U, _MI, _W, [('toe_out_more', FU), ('camber_more', FU), ('loosen_sidepods', RD)])
    add(_U, _EX, _W, [('ballast_up', JU, 'low_normal'), ('rear_lower', JU), ('camber_more', FU), ('loosen_sidepods', RD)])
    add(_U, _EN, _M, [('rear_hubs_shorter', RD), ('axle_softer', RD), ('seat_struts_remove', RD),
                      ('ballast_forward', FU, 'normal'), ('caster_more', JU), ('front_hubs_longer', FU),
                      ('ackermann_more', JU), ('drive_smooth_steering', DR)])
    add(_U, _MI, _M, [('rear_hubs_shorter', RD), ('seat_struts_remove', RD), ('caster_more', JU),
                      ('front_hubs_longer', FU), ('ackermann_more', JU), ('front_lower', FU)])
    add(_U, _EX, _M, [('install_front_torsion', FU), ('rear_hubs_shorter', RD), ('caster_more', JU),
                      ('front_hubs_longer', FU), ('seat_struts_remove', RD), ('ballast_up', JU, 'high'),
                      ('ackermann_more', JU), ('axle_softer', RD), ('drive_ease_throttle', DR), ('front_lower', FU)])
    add(_U, _EN, _S, [('widen_front_track', JU), ('seat_forward', FU), ('front_higher', FU),
                      ('widen_rear_track', RD), ('remove_rear_torsion', RD), ('ballast_forward', FU, 'high')])
    add(_U, _MI, _S, [('widen_front_track', JU), ('remove_rear_torsion', RD), ('seat_forward', FU)])
    add(_U, _EX, _S, [('seat_forward', FU), ('widen_front_track', JU), ('remove_rear_torsion', RD)])

    # Избыточная поворачиваемость
    add(_O, _EN, _W, [('tighten_front_bumper', OT), ('ballast_rearward', RU, 'low'), ('rear_pressure_down', JD),
                      ('remove_front_torsion', FD)])
    add(_O, _MI, _W, [('camber_less', FD), ('rear_pressure_down', JD)])
    add(_O, _EX, _W, [('remove_front_torsion', FD), ('ballast_rearward', RU, 'low'), ('ballast_up_rear', RU),
                      ('camber_less', FD), ('rear_pressure_down', JD)])
    rear_up = [('rear_hubs_longer', RU), ('seat_struts_install', RU), ('axle_stiffer', RU),
               ('middle_bearing_tighten', RU), ('ballast_rearward', RU, 'normal')]
    add(_O, _EN, _M, rear_up + [('front_lower', FD), ('toe_out_less', FD), ('rear_higher', JD), ('caster_less', JD),
                                ('ackermann_less', JD), ('install_rear_torsion', RU), ('drive_less_trail_braking', DR)])
    add(_O, _MI, _M, rear_up + [('rear_higher', JD), ('caster_less', JD), ('install_rear_torsion', RU)])
    add(_O, _EX, _M, [('narrow_front_track', FD)] + rear_up + [('rear_higher', JD), ('caster_less', JD),
                                                               ('install_rear_torsion', RU), ('drive_turn_in_later', DR)])
    add(_O, _EN, _S, [('narrow_front_track', JD), ('widen_rear_track', JD)])
    add(_O, _EX, _S, [('seat_rearward', RU), ('narrow_rear_track', JD), ('ballast_rearward', RU, 'high')])

    # Прыжки одного колеса
    add(_H, _EN, _W, [('remove_rear_torsion', OT), ('ballast_forward', OT, 'low')])
    add(_H, _MI, _W, [('remove_rear_torsion', OT)])
    add(_H, _EX, _W, [('remove_rear_torsion', OT)])
    hop_m = [('rear_hubs_shorter', OT), ('seat_struts_remove', OT), ('axle_softer', OT)]
    add(_H, _EN, _M, hop_m + [('ballast_forward', OT, 'normal'), ('ballast_down_rear', OT, 'high'), ('rear_lower', OT)])
    add(_H, _MI, _M, hop_m + [('ballast_down_rear', OT, 'high'), ('rear_lower', OT)])
    add(_H, _EX, _M, hop_m + [('ballast_down_rear', OT, 'high'), ('rear_lower', OT)])
    add(_H, _EN, _S, [('widen_rear_track', OT), ('rear_pressure_up', OT), ('caster_less', OT),
                      ('ballast_forward', OT, 'high'), ('seat_down', OT), ('seat_forward', OT)])
    add(_H, _MI, _S, [('widen_rear_track', OT), ('rear_pressure_up', OT), ('caster_less', OT), ('seat_down', OT)])
    add(_H, _EX, _S, [('widen_rear_track', OT), ('caster_less', OT), ('seat_down', OT)])

    # Отрыв обоих внутренних колёс
    add(_L, _ANY, _M, [('widen_front_track', OT), ('widen_rear_track', OT), ('rear_lower', OT), ('seat_down', OT),
                       ('ballast_down', OT, 'normal')])

    # Скольжение всеми колёсами
    add(_D, _EN, _W, [('install_rear_torsion', FU), ('tighten_front_bumper', FU), ('ballast_up', JU, 'low')])
    add(_D, _MI, _W, [('install_rear_torsion', FU), ('tighten_front_bumper', FU), ('ballast_up', FU, 'low')])
    add(_D, _EX, _W, [('install_rear_torsion', FU), ('tighten_front_bumper', FU)])
    add(_D, _EN, _M, [('axle_stiffer', RU), ('widen_front_track', JU), ('rear_hubs_longer', RU),
                      ('ballast_up', JU, 'normal'), ('drive_fewer_steering', DR)])
    for ph in (_MI, _EX):
        add(_D, ph, _M, [('axle_stiffer', RU), ('widen_front_track', FU), ('rear_hubs_longer', RU),
                         ('ballast_up', JU, 'normal'), ('drive_fewer_steering', DR)])
    add(_D, _EN, _S, [('all_pressure_down', OT), ('heights_higher', JU), ('seat_up', JU), ('ballast_up', JU, 'high'),
                      ('narrow_rear_track', JU)])
    add(_D, _MI, _S, [('all_pressure_down', OT), ('heights_higher', JU), ('seat_up', JU), ('narrow_rear_track', JU)])
    add(_D, _EX, _S, [('axle_stiffer', JU), ('heights_higher', JU), ('seat_up', JU), ('narrow_rear_track', JU)])
    # Своё (в разборе Rainmeister не подключён к анализу): скольжение на мокрой трассе.
    add(_D, _ANY, _M, [('rainmeister', OT, 'any', 'wet')])
    return r


def seed(apps, schema_editor):
    Advice = apps.get_model('website', 'AppChassisAdvice')
    Rule = apps.get_model('website', 'AppChassisRule')
    if Advice.objects.exists():
        return
    objs = {}
    for i, (code, (title, text, target, action, value)) in enumerate(ADVICES.items()):
        objs[code] = Advice.objects.create(code=code, title=title, text=text, target=target, action=action,
                                           value=value, sort_order=i * 10)
    order = {}
    for symptom, phase, level, code, group, ballast, weather in _rules():
        a = objs[code]
        order[code] = order.get(code, 0) + 1
        Rule.objects.create(advice=a, symptom=symptom, phase=phase, level=level, group=group, ballast=ballast,
                            weather=weather, sort_order=order[code])


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0086_app_chassis_advice'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
