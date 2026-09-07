from django.conf import settings
from django.urls import reverse


def test_postgresql_is_configured():
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"


def test_admin_route_is_registered():
    assert reverse("admin:index") == "/admin/"
