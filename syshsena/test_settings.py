import os
import tempfile
from pathlib import Path

from .settings import *

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": os.environ.get("WAYRA_TEST_DB", ":memory:")}}
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
MEDIA_ROOT = Path(tempfile.gettempdir()) / "wayra-pruebas-media"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
DEBUG = True
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
