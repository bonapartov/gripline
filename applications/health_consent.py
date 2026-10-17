"""Согласие на обработку сведений о здоровье (медицинская справка).

Медсправка — специальная категория персональных данных (ст. 10 152-ФЗ). Сайту эти сведения
не нужны (решение владельца 17.10.2026): справка хранится только для передачи организатору
этапа для допуска к соревнованию. Поэтому при каждой загрузке медсправки — отдельная отметка
согласия, а кто и когда её поставил, записывается рядом с файлом (health_consent_at/_by
у ApplicationDocument и accounts.PilotDocument) и переносится при копировании в ЛК и обратно.
"""
from django.utils import timezone

from . import document_kinds

PILOT_TEXT = ('Даю согласие на обработку сведений о состоянии здоровья, содержащихся в медицинской справке. '
              'Сайту gripline.ru эти сведения не нужны: справка хранится только для передачи организатору этапа '
              'для допуска к соревнованию, не публикуется и в других целях не используется.')
TEAM_TEXT = ('Подтверждаю, что пилот (его законный представитель) согласен на обработку сведений о состоянии '
             'здоровья из медицинской справки для передачи организатору этапа. Сайту gripline.ru эти сведения '
             'не нужны: справка не публикуется и в других целях не используется.')
ERROR = 'Отметьте согласие на обработку сведений о здоровье — без него медицинскую справку загрузить нельзя.'


def needed(kind):
    return kind == document_kinds.MEDICAL


def given(data):
    return (data.get('health_consent') or '').lower() in ('1', 'on', 'true', 'yes')


def text_for(application):
    return PILOT_TEXT if application.submitted_by_type == 'pilot' else TEAM_TEXT


def stamp(obj, user):
    obj.health_consent_at = timezone.now()
    obj.health_consent_by = user if user is not None and user.is_authenticated else None


def copy(src, dst):
    dst.health_consent_at = getattr(src, 'health_consent_at', None)
    dst.health_consent_by_id = getattr(src, 'health_consent_by_id', None)
