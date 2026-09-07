import uuid

import pytest
from django.db import OperationalError
from rest_framework.test import APIClient

from config import views as config_views


pytestmark = pytest.mark.django_db


def test_health_reports_application_and_database_status_without_authentication():
    response = APIClient().get("/health/")

    assert response.status_code == 200
    assert response.data == {"status": "healthy", "database": "available"}
    assert uuid.UUID(response["X-Request-ID"])


def test_health_returns_503_without_leaking_database_error(monkeypatch):
    def unavailable_cursor():
        raise OperationalError("sensitive database connection detail")

    monkeypatch.setattr(config_views.connection, "cursor", unavailable_cursor)

    response = APIClient().get("/health/")

    assert response.status_code == 503
    assert response.data == {"status": "unhealthy", "database": "unavailable"}
    assert b"sensitive" not in response.content


def test_valid_request_id_is_returned_and_invalid_value_is_replaced():
    request_id = str(uuid.uuid4())

    accepted = APIClient().get("/health/", HTTP_X_REQUEST_ID=request_id)
    replaced = APIClient().get("/health/", HTTP_X_REQUEST_ID="not-a-uuid")

    assert accepted["X-Request-ID"] == request_id
    assert replaced["X-Request-ID"] != "not-a-uuid"
    assert uuid.UUID(replaced["X-Request-ID"])
