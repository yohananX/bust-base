import os

# Force DEBUG on before anything else imports settings or env reads .env.
os.environ['DEBUG'] = 'True'

from .settings import *

# Use simple static files storage for tests (no manifest required)
STORAGES['staticfiles']['BACKEND'] = 'django.contrib.staticfiles.storage.StaticFilesStorage'
