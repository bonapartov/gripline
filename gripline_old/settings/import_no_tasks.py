from .prod import *  # noqa

TASKS = {
    'default': {
        'BACKEND': 'django_tasks.backends.dummy.DummyBackend',
    }
}
