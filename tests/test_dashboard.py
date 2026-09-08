import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_dashboard_is_public(client):
    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    assert b"Move value with confidence" in response.content
    assert b"/api/docs/" in response.content
