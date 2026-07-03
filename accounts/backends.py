from social_core.backends.yandex import YandexOAuth2
from social_core.backends.oauth import BaseOAuth2PKCE


class GriplineYandexOAuth2(YandexOAuth2):
    """Yandex OAuth2 backend that reads credentials from SocialAuthSettings (DB)."""

    def get_key_and_secret(self):
        from accounts.models import SocialAuthSettings
        s = SocialAuthSettings.get()
        return s.yandex_client_id, s.yandex_client_secret


class GriplineVKID(BaseOAuth2PKCE):
    """
    VK ID (id.vk.ru) OAuth 2.1 + PKCE backend.

    VK ID заменил классический VK OAuth для всех новых приложений и не даёт
    готового backend в social_core, поэтому реализован здесь напрямую по
    докам VK ID. Особенности, которых нет в стандартном OAuth2/PKCE:
      - обмен кода на токен идёт БЕЗ client_secret (его роль выполняет PKCE);
      - в callback вместе с code/state приходит device_id, который надо
        вернуть обратно при обмене кода на токен — иначе обмен не пройдёт;
      - redirect_uri должен буквально совпадать со значением в кабинете VK ID,
        поэтому REDIRECT_STATE выключен (иначе social_core допишет к нему
        свой параметр).
      - данные пользователя отдаёт отдельный эндпоинт user_info, вложенные
        в ключ "user" (не на верхнем уровне ответа).
    """

    name = 'vk-id'
    AUTHORIZATION_URL = 'https://id.vk.ru/authorize'
    ACCESS_TOKEN_URL = 'https://id.vk.ru/oauth2/auth'
    USER_DATA_URL = 'https://id.vk.ru/oauth2/user_info'
    ACCESS_TOKEN_METHOD = 'POST'
    RESPONSE_TYPE = 'code'
    REDIRECT_STATE = False
    PKCE_DEFAULT_CODE_CHALLENGE_METHOD = 'S256'
    DEFAULT_SCOPE = ['email']

    def get_key_and_secret(self):
        from accounts.models import SocialAuthSettings
        s = SocialAuthSettings.get()
        return s.vk_client_id, s.vk_client_secret

    def auth_complete_params(self, state=None):
        client_id, _client_secret = self.get_key_and_secret()
        params = {
            'grant_type': 'authorization_code',
            'code': self.data.get('code', ''),
            'redirect_uri': self.get_redirect_uri(state),
            'client_id': client_id,
            'code_verifier': self.get_code_verifier(),
            'state': state,
        }
        device_id = self.data.get('device_id')
        if device_id:
            params['device_id'] = device_id
        return params

    def user_data(self, access_token, *args, **kwargs):
        client_id, _client_secret = self.get_key_and_secret()
        result = self.get_json(
            self.USER_DATA_URL,
            method='POST',
            data={'client_id': client_id, 'access_token': access_token},
        )
        return result.get('user') or {}

    def get_user_id(self, details, response):
        return response.get('user_id') or response.get('id')

    def get_user_details(self, response):
        fullname, first_name, last_name = self.get_user_names(
            first_name=response.get('first_name', ''),
            last_name=response.get('last_name', ''),
        )
        return {
            'username': response.get('user_id') or response.get('id'),
            'email': response.get('email', ''),
            'fullname': fullname,
            'first_name': first_name,
            'last_name': last_name,
        }
