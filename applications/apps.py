from django.apps import AppConfig


class ApplicationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'applications'
    verbose_name = 'Заявки на участие'

    def ready(self):
        # Сигналы accounts/teams (создание Driver/Team при одобрении заявки) должны быть
        # подключены раньше наших — иначе привязка заявок сработает до создания профиля.
        # Приложение стоит в INSTALLED_APPS раньше них, поэтому импортируем их явно.
        import accounts.signals  # noqa: F401
        import teams.signals  # noqa: F401
        from . import signals  # noqa: F401
