"""Ядро бота обратной связи (website/feedback/service.py) — без Telegram."""
import io
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from website.feedback import crypto, service, sources
from website.models import (
    Feedback, FeedbackAttachment, FeedbackBotSettings, FeedbackCategory,
    FeedbackDraft, FeedbackModerator, FeedbackStep, FeedbackUser,
)

# минимальный валидный PNG 1x1
PNG = bytes.fromhex(
    '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
    '0000000d49444154789c6360f8cfc0f01f0005000201a5f645400000000049454e44ae426082'
)


@pytest.fixture(autouse=True)
def private_media(tmp_path, settings):
    settings.PRIVATE_MEDIA_ROOT = tmp_path / 'private'
    settings.FEEDBACK_FERNET_KEY = 'cmV6b2x2ZXpvbHZlenJlem9sdmV6b2x2ZXpvbHZlenI='  # base64 из 32 байт


@pytest.fixture
def category(db):
    cat = FeedbackCategory.objects.create(slug='data-error', title='Ошибка', deep_link_code='err')
    FeedbackStep.objects.create(category=cat, sort_order=10, key='where', prompt_text='Где?', skip_if_source_set=True)
    FeedbackStep.objects.create(category=cat, sort_order=20, key='what', prompt_text='Что?')
    FeedbackStep.objects.create(
        category=cat, sort_order=30, key='shot', prompt_text='Скрин', type='attachment',
        is_required=False, skip_button_text='Пропустить',
    )
    return cat


@pytest.fixture
def user(db):
    return service.get_or_create_user('telegram', 111, 'vasya', 'Вася')


def test_crypto_roundtrip_and_mask(settings):
    token = '123456:AAFxyzSECRET'
    enc = crypto.encrypt(token)
    assert enc != token and 'SECRET' not in enc
    assert crypto.decrypt(enc) == token
    assert crypto.mask_token(token) == '123456:AA••••'
    assert crypto.decrypt('мусор') == ''


def test_token_stored_encrypted(db):
    cfg = FeedbackBotSettings.get()
    cfg.set_token('123456:AAFxyz')
    cfg.save()
    cfg.refresh_from_db()
    assert 'AAFxyz' not in cfg.bot_token_encrypted
    assert cfg.get_token() == '123456:AAFxyz'


def test_full_scenario(category, user):
    out = service.begin(user, category)
    assert out.kind == 'ask' and out.step.key == 'where'
    draft = service.get_draft(user)
    assert service.answer_text(draft, 'Страница рейтинга').step.key == 'what'
    out = service.answer_text(draft, 'Неверное место')
    assert out.step.key == 'shot'
    out = service.add_attachment(draft, PNG, 'a.png')
    assert out.kind == 'saved'
    out = service.done_attachments(draft)
    assert out.kind == 'complete'
    fb = out.feedback
    assert fb.answers == {'where': 'Страница рейтинга', 'what': 'Неверное место'}
    assert fb.attachments.count() == 1
    assert not FeedbackDraft.objects.exists()


def test_skip_if_source_set(category, user):
    out = service.begin(user, category, 'stage', 5)
    assert out.step.key == 'what'


def test_skip_optional_step_and_required_cannot(category, user):
    service.begin(user, category)
    draft = service.get_draft(user)
    # обязательный шаг пропустить нельзя
    assert service.skip_step(draft).step.key == 'where'
    service.answer_text(draft, 'x')
    service.answer_text(draft, 'y')
    assert service.skip_step(draft).kind == 'complete'


def test_text_too_long(category, user):
    cfg = FeedbackBotSettings.get()
    cfg.max_text_length = 10
    cfg.save()
    service.begin(user, category)
    out = service.answer_text(service.get_draft(user), 'а' * 11)
    assert out.kind == 'too_long'


def test_attachment_rejected_by_content_and_size(category, user):
    service.begin(user, category)
    draft = service.get_draft(user)
    service.answer_text(draft, 'a')
    service.answer_text(draft, 'b')
    # .png в имени, но внутри текст — отклоняется по содержимому
    assert service.add_attachment(draft, b'not an image at all', 'x.png').kind == 'rejected'
    cfg = FeedbackBotSettings.get()
    cfg.max_file_size_mb = 0
    cfg.save()
    assert service.add_attachment(draft, PNG, 'x.png').kind == 'rejected'
    assert draft.attachments.count() == 0


def test_attachment_limit_auto_advances(category, user):
    cfg = FeedbackBotSettings.get()
    cfg.max_files_per_feedback = 2
    cfg.save()
    service.begin(user, category)
    draft = service.get_draft(user)
    service.answer_text(draft, 'a')
    service.answer_text(draft, 'b')
    assert service.add_attachment(draft, PNG).kind == 'saved'
    assert service.add_attachment(draft, PNG).kind == 'complete'


def test_rate_limit(category, user):
    cfg = FeedbackBotSettings.get()
    cfg.rate_limit_per_hour = 1
    cfg.save()
    for expected in ('complete', 'rate_limited'):
        service.begin(user, category, 'stage', 1)
        draft = service.get_draft(user)
        out = service.answer_text(draft, 'что-то')
        assert out.kind == 'ask'  # шаг с вложением
        assert service.skip_step(draft).kind == expected


def test_cancel_removes_draft_and_files(category, user):
    service.begin(user, category)
    draft = service.get_draft(user)
    service.answer_text(draft, 'a')
    service.answer_text(draft, 'b')
    service.add_attachment(draft, PNG)
    path = draft.attachments.first().file.path
    assert service.cancel(user) is True
    assert not FeedbackDraft.objects.exists()
    import os
    assert not os.path.exists(path)


def test_status_change_idempotent(category, user):
    fb = Feedback.objects.create(user=user, category=category)
    mod = FeedbackModerator.objects.create(external_user_id='9', name='Мод')
    assert service.change_status(fb, 'in_work', mod) is True
    assert service.change_status(fb, 'in_work', mod) is False
    assert fb.assigned_to == mod
    assert service.change_status(fb, 'done', mod) is True
    assert fb.closed_at is not None


def test_only_active_moderators(db):
    FeedbackModerator.objects.create(external_user_id='9', name='A', is_active=False)
    assert service.get_moderator('telegram', 9) is None
    FeedbackModerator.objects.filter(external_user_id='9').update(is_active=True)
    assert service.get_moderator('telegram', 9) is not None


def test_forget_user_removes_pii(category, user):
    service.begin(user, category)
    draft = service.get_draft(user)
    service.answer_text(draft, 'a')
    service.answer_text(draft, 'b')
    service.add_attachment(draft, PNG)
    fb = service.done_attachments(draft).feedback
    service.add_message(fb, 'in', 'привет')
    path = fb.attachments.first().file.path
    affected = service.forget_user(user)
    fb.refresh_from_db()
    assert affected[0].pk == fb.pk
    assert fb.user is None and fb.answers == {} and fb.anonymized_at
    assert not fb.attachments.exists() and not fb.messages.exists()
    assert not FeedbackUser.objects.filter(pk=user.pk).exists()
    import os
    assert not os.path.exists(path)


def test_forget_keeps_ban_without_pii(category, user):
    service.set_banned(user, True, 'спам')
    service.forget_user(user)
    user = FeedbackUser.objects.get(pk=user.pk)
    assert user.is_banned and user.username == '' and user.anonymized_at


def test_cleanup_by_retention(category, user):
    old = Feedback.objects.create(user=user, category=category, answers={'a': 'b'})
    Feedback.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=400))
    new = Feedback.objects.create(user=user, category=category, answers={'a': 'b'})
    affected, _, _ = service.cleanup_expired()
    assert [f.pk for f in affected] == [old.pk]
    old.refresh_from_db()
    new.refresh_from_db()
    assert old.user is None and old.answers == {}
    assert new.user == user and new.answers == {'a': 'b'}


def test_cleanup_stale_drafts(category, user):
    service.begin(user, category)
    FeedbackDraft.objects.update(updated_at=timezone.now() - timedelta(hours=25))
    _, drafts, _ = service.cleanup_expired()
    assert drafts == 1 and not FeedbackDraft.objects.exists()


def test_render_text_is_safe():
    assert service.render('Привет {name} {unknown}', name='Вася') == 'Привет Вася {unknown}'
    assert service.render('{', ) == '{'


def test_start_param_parsing():
    assert sources.parse_start_param('err_s_142') == ('err', 'stage', 142)
    assert sources.parse_start_param('err_p_7') == ('err', 'pilot', 7)
    assert sources.parse_start_param('мусор') is None
    assert sources.parse_start_param('err_x_1') is None
    assert sources.parse_start_param('err_s_') is None


def test_find_feedback_by_admin_message(category, user):
    fb = Feedback.objects.create(user=user, category=category, admin_chat_message_id=500)
    msg_fb = Feedback.objects.create(user=user, category=category)
    service.add_message(msg_fb, 'in', 'x', admin_chat_message_id=600)
    assert service.find_feedback_by_admin_message(500) == fb
    assert service.find_feedback_by_admin_message(600) == msg_fb
    assert service.find_feedback_by_admin_message(1) is None
