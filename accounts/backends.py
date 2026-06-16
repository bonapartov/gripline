from social_core.backends.yandex import YandexOAuth2


class GriplineYandexOAuth2(YandexOAuth2):
    """Yandex OAuth2 backend that reads credentials from SocialAuthSettings (DB)."""

    def get_key_and_secret(self):
        from accounts.models import SocialAuthSettings
        s = SocialAuthSettings.get()
        return s.yandex_client_id, s.yandex_client_secret
