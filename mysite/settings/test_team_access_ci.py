"""Disposable CI PostgreSQL only; no production DSN or credentials are read."""
from .test_team_access import *

DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': 'gripline_synthetic',
    'HOST': '127.0.0.1',
    'PORT': '5432',
    'USER': 'postgres',
    'PASSWORD': 'synthetic-ci-only',
    'TEST': {'NAME': 'test_gripline_synthetic'},
}}
