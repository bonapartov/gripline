from .base import *

SECRET_KEY = "qdq2i*4v@%lq!qovq^jg!ovp!)*0)k*p=v178jv8w^m$njpb="

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'gripline_dev',
        'USER': 'v',
        'PASSWORD': 'gripline',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
DEBUG = True
