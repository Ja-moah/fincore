import pytest
from django.templatetags.static import static
from django.urls import reverse


pytestmark = pytest.mark.django_db


def test_dashboard_is_public_and_exposes_the_existing_api_workflow(client):
    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    assert b"FinCore" in response.content
    assert b"Send money" in response.content
    assert b"Transaction history" in response.content
    assert b"/api/docs/" in response.content
    assert static("config/favicon.png").encode() in response.content


def test_dashboard_static_assets_resolve_through_django_static_storage(client):
    response = client.get(reverse("dashboard"))

    assert static("config/dashboard.css").encode() in response.content
    assert static("config/dashboard.js").encode() in response.content
