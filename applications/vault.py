"""
Документы ЛК пилота (accounts.PilotDocument) ↔ документы заявки.

- В заявку: при отправке строки требуемых документов заполняются из ЛК — постоянные типы
  по типу, «другие» по названию. Документ подставляется, только если действует на все дни
  этапа и не был отклонён организатором.
- Из заявки: файл постоянного типа, загруженный в заявку, становится текущим документом
  этого типа в ЛК (прежний заменяется; в старых заявках остаются свои копии).
- Отклонение: организатор отклонил файл — документ ЛК помечается и сам больше не подставляется.

Хранилище — у заявок, поданных самим пилотом (или родителем из аккаунта пилота), и у заявок
команды за пилота из её состава: по решению владельца (17.10.2026) активное членство в команде —
согласие пилота, что менеджер берёт документы из его ЛК и сохраняет туда загруженные. Пилот,
добавленный в заявку команды не из состава, и заявки организатора ЛК не трогают.
"""
import os

from django.core.files.base import ContentFile
from django.utils import timezone

from . import document_kinds


def vault_profile(application):
    if application.submitted_by_type == 'pilot':
        return getattr(application.submitted_by, 'profile', None)
    if application.submitted_by_type == 'team' and application.team_entry_id:
        return team_pilot_profile(application)
    return None


def team_pilot_profile(application):
    """ЛК пилота заявки команды: только подтверждённый профиль пилота из активного состава
    этой команды."""
    from accounts.models import UserProfile
    from website.models import TeamMembership
    pilot = getattr(application, 'pilot', None)
    driver_id = pilot.driver_id if pilot is not None else None
    if not driver_id or not TeamMembership.objects.filter(
            team_id=application.team_entry.team_id, driver_id=driver_id, is_active=True).exists():
        return None
    return UserProfile.objects.filter(driver_id=driver_id, verified=True).first()


def stage_last_day(stage):
    return timezone.localtime(stage.end_date or stage.start_date).date()


def _copy_file(src_field, dst_field):
    src_field.open('rb')
    try:
        content = src_field.read()
    finally:
        src_field.close()
    dst_field.save(os.path.basename(src_field.name), ContentFile(content), save=False)


def _match(vault_docs, stage_document):
    if stage_document.is_fixed_kind:
        return next((d for d in vault_docs if d.kind == stage_document.kind), None)
    name = stage_document.name.strip().lower()
    return next((d for d in vault_docs if d.kind == document_kinds.OTHER and d.name.strip().lower() == name), None)


def required_documents(stage, is_minor):
    return [d for d in stage.required_documents.filter(is_active=True) if is_minor or not d.minors_only]


def preview(stage, profile, is_minor):
    """Для шага «Проверка»: [(документ этапа, документ ЛК или None, состояние)], состояние —
    'ok' (подставится), 'expired' (истекает до конца этапа), 'rejected', 'missing'."""
    vault_docs = list(profile.documents.all()) if profile else []
    last_day = stage_last_day(stage)
    rows = []
    for stage_doc in required_documents(stage, is_minor):
        match = _match(vault_docs, stage_doc)
        if match is None:
            state = 'missing'
        elif match.rejected_at:
            state = 'rejected'
        elif not match.valid_through(last_day):
            state = 'expired'
        else:
            state = 'ok'
        rows.append((stage_doc, match, state))
    return rows


def create_document_rows(application, is_minor):
    """Строки требуемых документов заявки; подходящие из ЛК — сразу «загружены»."""
    from .models import ApplicationDocument
    if application.documents.exists():
        return
    profile = vault_profile(application)
    rows = preview(application.stage, profile, is_minor) if profile else [
        (d, None, 'missing') for d in required_documents(application.stage, is_minor)]
    for stage_doc, match, state in rows:
        row = ApplicationDocument(application=application, stage_document=stage_doc)
        if state == 'ok':
            _copy_file(match.file, row.file)
            row.status, row.uploaded_at = 'uploaded', timezone.now()
            row.expiry_date, row.vault_document = match.expiry_date, match
        row.save()


def save_from_application(app_doc):
    """Файл постоянного типа из заявки → текущий документ этого типа в ЛК. Возвращает
    документ ЛК или None (тип «другой», у заявки нет ЛК — см. vault_profile)."""
    from accounts.models import PilotDocument
    kind = app_doc.stage_document.kind
    profile = vault_profile(app_doc.application)
    if profile is None or not document_kinds.is_fixed(kind) or not app_doc.file:
        return None
    previous = list(profile.documents.filter(kind=kind))
    doc = PilotDocument(profile=profile, kind=kind, name=document_kinds.label(kind),
                        expiry_date=app_doc.expiry_date)
    _copy_file(app_doc.file, doc.file)
    doc.save()
    replace_previous(previous)
    app_doc.vault_document = doc
    app_doc.save(update_fields=['vault_document'])
    return doc


def replace_previous(documents):
    """Убирает прежние документы того же типа из ЛК (файлы — тоже). Заявки хранят свои копии."""
    for old in documents:
        old.file.delete(save=False)
        old.delete()


def mark_rejected(app_doc, comment):
    """Организатор отклонил файл — его копия в ЛК больше не подставляется сама."""
    if app_doc.vault_document_id:
        type(app_doc.vault_document).objects.filter(pk=app_doc.vault_document_id).update(
            rejected_at=timezone.now(), rejected_comment=comment)
