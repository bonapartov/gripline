"""Админка бота обратной связи: настройки/токен, права, закрытые вложения."""
import pytest
from django.contrib.auth.models import Group, Permission, User
from django.urls import reverse

from website.feedback import service
from website.models import (
    Feedback, FeedbackAttachment, FeedbackBotSettings, FeedbackCategory, FeedbackStep,
)
from website.tests.test_feedback_service import PNG  # noqa: F401

FERNET = 'cmV6b2x2ZXpvbHZlenJlem9sdmV6b2x2ZXpvbHZlenI='
TOKEN = '123456789:AAFabcdefghijklmnopqrstuvwxyz0123'


@pytest.fixture(autouse=True)
def cfg(settings, tmp_path):
    settings.FEEDBACK_FERNET_KEY = FERNET
    settings.PRIVATE_MEDIA_ROOT = tmp_path / 'private'


@pytest.fixture
def admin_client(client, db):
    client.force_login(User.objects.create_superuser('root', 'r@example.com', 'pw'))
    return client


def settings_url():
    obj = FeedbackBotSettings.get()
    return f'/admin/website/feedbackbotsettings/edit/{obj.pk}/'


def valid_post(**over):
    data = {
        'bot_username': 'gripline_support_bot', 'use_vpn': 'on', 'settings_refresh_sec': 60,
        'rate_limit_per_hour': 5, 'max_text_length': 2000, 'max_file_size_mb': 10,
        'max_files_per_feedback': 3, 'allowed_file_types': 'jpg, png, pdf',
        'retention_months': 12, 'privacy_policy_url': 'https://gripline.ru/legal/privacy/',
        'new_bot_token': '',
    }
    data.update(over)
    return data


def test_menu_pages_render(admin_client, db):
    FeedbackCategory.objects.create(slug='a', title='A')
    for path in (
        '/admin/website/feedback/', '/admin/website/feedbackcategory/',
        '/admin/website/feedbacktext/', '/admin/website/feedbackmoderator/',
        '/admin/website/feedbackuser/',
    ):
        assert admin_client.get(path).status_code == 200, path


def test_settings_index_redirects_to_form_and_form_renders(admin_client):
    resp = admin_client.get('/admin/website/feedbackbotsettings/')
    assert resp.status_code == 302
    page = admin_client.get(settings_url())
    assert page.status_code == 200
    assert 'Проверить соединение' in page.content.decode()


def test_token_saved_encrypted_and_masked(admin_client):
    resp = admin_client.post(settings_url(), valid_post(new_bot_token=TOKEN))
    assert resp.status_code == 302, resp.content.decode()[:500]
    cfg = FeedbackBotSettings.get()
    assert cfg.get_token() == TOKEN
    assert TOKEN not in cfg.bot_token_encrypted
    html = admin_client.get(settings_url()).content.decode()
    assert TOKEN not in html and '123456789:AA••••' in html


def test_empty_token_field_keeps_old_token(admin_client):
    cfg = FeedbackBotSettings.get()
    cfg.set_token(TOKEN)
    cfg.save()
    resp = admin_client.post(settings_url(), valid_post(new_bot_token='', rate_limit_per_hour=7))
    assert resp.status_code == 302
    cfg.refresh_from_db()
    assert cfg.get_token() == TOKEN and cfg.rate_limit_per_hour == 7


def test_invalid_token_rejected(admin_client):
    resp = admin_client.post(settings_url(), valid_post(new_bot_token='не токен'))
    assert resp.status_code == 200
    assert FeedbackBotSettings.get().get_token() == ''


def test_refresh_period_min_10(admin_client):
    resp = admin_client.post(settings_url(), valid_post(settings_refresh_sec=5))
    assert resp.status_code == 200


def test_restart_button_sets_flag(admin_client):
    assert FeedbackBotSettings.get().restart_requested_at is None
    resp = admin_client.post(reverse('feedback_bot_restart'))
    assert resp.json()['ok'] is True
    assert FeedbackBotSettings.get().restart_requested_at is not None


def test_bot_actions_forbidden_without_permission(client, db):
    plain = User.objects.create_user('plain', password='pw')
    plain.user_permissions.add(Permission.objects.get(codename='access_admin'))
    client.force_login(plain)
    assert client.post(reverse('feedback_bot_restart')).status_code == 403
    assert client.get(reverse('feedback_bot_status')).status_code == 403


def test_check_connection_never_leaks_token(admin_client, monkeypatch):
    import requests
    cfg = FeedbackBotSettings.get()
    cfg.set_token(TOKEN)
    cfg.save()

    def boom(url, **kw):
        raise requests.ConnectionError(f'failed {url}')
    monkeypatch.setattr(requests, 'post', boom)
    data = admin_client.post(reverse('feedback_bot_check')).json()
    assert data['ok'] is False and TOKEN not in data['message']


def test_check_connection_ok(admin_client, monkeypatch):
    import requests
    cfg = FeedbackBotSettings.get()
    cfg.set_token(TOKEN)
    cfg.save()

    class Resp:
        status_code = 200
        def json(self):
            return {'ok': True, 'result': {'id': 1, 'username': 'gripline_support_bot'}}
    seen = {}

    def fake(url, **kw):
        seen.update(kw)
        return Resp()
    monkeypatch.setattr(requests, 'post', fake)
    data = admin_client.post(reverse('feedback_bot_check')).json()
    assert data['ok'] and '@gripline_support_bot' in data['message']


def test_attachment_not_public_and_permission_gated(admin_client, client, db):
    cat = FeedbackCategory.objects.create(slug='c', title='C')
    FeedbackStep.objects.create(category=cat, key='s', prompt_text='?', type='attachment', is_required=False)
    user = service.get_or_create_user('telegram', 5, 'u', 'U')
    service.begin(user, cat)
    draft = service.get_draft(user)
    service.add_attachment(draft, PNG, 'шот.png')
    fb = service.done_attachments(draft).feedback
    att = fb.attachments.first()
    # файл не под публичным MEDIA_ROOT, у поля нет публичного URL
    from django.conf import settings
    assert str(settings.MEDIA_ROOT) not in att.file.path
    with pytest.raises(ValueError):
        att.file.url
    resp = admin_client.get(reverse('feedback_attachment', args=[att.pk]))
    assert resp.status_code == 200 and resp.headers['Content-Type'] == 'image/png'
    client.logout()
    anon = client.get(reverse('feedback_attachment', args=[att.pk]))
    assert anon.status_code in (302, 403)


def test_view_permission_enough_for_attachment_not_for_settings(client, db):
    cat = FeedbackCategory.objects.create(slug='c', title='C')
    FeedbackStep.objects.create(category=cat, key='s', prompt_text='?', type='attachment', is_required=False)
    user = service.get_or_create_user('telegram', 5, 'u', 'U')
    service.begin(user, cat)
    draft = service.get_draft(user)
    service.add_attachment(draft, PNG, 'a.png')
    fb = service.done_attachments(draft).feedback
    att = fb.attachments.first()
    moderator = User.objects.create_user('mod', password='pw')
    moderator.user_permissions.add(Permission.objects.get(codename='view_feedback'))
    moderator.user_permissions.add(Permission.objects.get(codename='access_admin'))
    client.force_login(moderator)
    assert client.get(reverse('feedback_attachment', args=[att.pk])).status_code == 200
    assert client.post(reverse('feedback_bot_restart')).status_code == 403
