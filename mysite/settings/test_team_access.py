"""Synthetic-only PostgreSQL checks. Never inherits a production DSN.

Start an isolated local PostgreSQL listening on /tmp/gripline-test-pg.
The connection and test database names are intentionally fixed.
"""
from .dev import *

DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql', 'NAME': 'gripline_synthetic',
    'HOST': '/tmp/gripline-test-pg', 'USER': 'postgres',
    'TEST': {'NAME': 'test_gripline_synthetic'},
}}
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
MEDIA_ROOT = '/tmp/gripline-synthetic-media'
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
TEAM_ACCESS_LEGACY_ENABLED = False
