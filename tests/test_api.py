import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import Account, Currency
from audit.models import AuditEvent
from ledger.models import LedgerEntry
from ledger.services import calculate_balance
from transactions import services as transfer_services
from transactions.models import IdempotencyRecord, Transaction


pytestmark = pytest.mark.django_db


TRANSFER_URL = "/api/v1/transfers/"


@pytest.fixture
def api_context():
    user_model = get_user_model()
    treasury_user = user_model.objects.create_user(username="api-treasury")
    sender_user = user_model.objects.create_user(username="api-sender")
    recipient_user = user_model.objects.create_user(username="api-recipient")
    unrelated_user = user_model.objects.create_user(username="api-unrelated")
    treasury = Account.objects.create(
        user=treasury_user, account_number="API-TREASURY"
    )
    sender = Account.objects.create(user=sender_user, account_number="API-SENDER")
    recipient = Account.objects.create(
        user=recipient_user, account_number="API-RECIPIENT"
    )
    unrelated = Account.objects.create(
        user=unrelated_user, account_number="API-UNRELATED"
    )
    return {
        "treasury": treasury,
        "sender": sender,
        "recipient": recipient,
        "unrelated": unrelated,
        "sender_user": sender_user,
        "recipient_user": recipient_user,
        "unrelated_user": unrelated_user,
    }


def fund_account(treasury, account, amount=Decimal("500.00")):
    funding = Transaction.objects.create(
        sender=treasury,
        recipient=account,
        amount=amount,
        currency=Currency.GHS,
        status=Transaction.Status.SUCCEEDED,
    )
    LedgerEntry.objects.create(
        transaction=funding,
        account=treasury,
        entry_type=LedgerEntry.EntryType.DEBIT,
        amount=amount,
        currency=Currency.GHS,
    )
    LedgerEntry.objects.create(
        transaction=funding,
        account=account,
        entry_type=LedgerEntry.EntryType.CREDIT,
        amount=amount,
        currency=Currency.GHS,
    )
    return funding


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def transfer_payload(recipient, amount="100.00"):
    return {
        "recipient_account": recipient.account_number,
        "amount": amount,
        "currency": Currency.GHS,
    }


def test_jwt_login_and_refresh_endpoints(api_context):
    api_context["sender_user"].set_password("test-pass-123")
    api_context["sender_user"].save(update_fields=["password"])
    client = APIClient()
    login = client.post(
        "/api/v1/auth/token/",
        {"username": "api-sender", "password": "test-pass-123"},
        format="json",
    )

    assert login.status_code == 200
    assert set(login.data) == {"access", "refresh"}

    refreshed = client.post(
        "/api/v1/auth/token/refresh/",
        {"refresh": login.data["refresh"]},
        format="json",
    )
    assert refreshed.status_code == 200
    assert "access" in refreshed.data


def test_unauthenticated_transfer_is_rejected(api_context):
    response = APIClient().post(
        TRANSFER_URL,
        transfer_payload(api_context["recipient"]),
        format="json",
        HTTP_IDEMPOTENCY_KEY="unauthenticated",
    )

    assert response.status_code == 401
    assert response.data["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_authenticated_transfer_uses_owned_sender_and_balances_ledger(api_context):
    fund_account(api_context["treasury"], api_context["sender"])
    payload = transfer_payload(api_context["recipient"], "125.00")
    payload["sender_account"] = api_context["unrelated"].account_number
    request_id = str(uuid.uuid4())

    response = authenticated_client(api_context["sender_user"]).post(
        TRANSFER_URL,
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="owned-sender",
        HTTP_X_REQUEST_ID=request_id,
    )

    assert response.status_code == 201
    assert response.data["sender_account"] == api_context["sender"].account_number
    transaction = Transaction.objects.get(id=response.data["id"])
    entries = list(transaction.ledger_entries.all())
    assert transaction.sender == api_context["sender"]
    assert len(entries) == 2
    assert sum(entry.signed_amount for entry in entries) == Decimal("0.00")
    assert AuditEvent.objects.get(resource_id=str(transaction.id)).request_id == uuid.UUID(
        request_id
    )
    assert response["X-Request-ID"] == request_id


def test_insufficient_funds_returns_stable_error(api_context):
    response = authenticated_client(api_context["sender_user"]).post(
        TRANSFER_URL,
        transfer_payload(api_context["recipient"]),
        format="json",
        HTTP_IDEMPOTENCY_KEY="insufficient",
    )

    assert response.status_code == 422
    assert response.data["error"]["code"] == "INSUFFICIENT_FUNDS"
    assert not IdempotencyRecord.objects.filter(key="insufficient").exists()


@pytest.mark.parametrize("amount", ["0.00", "-1.00", "1.001"])
def test_invalid_amount_is_rejected(api_context, amount):
    response = authenticated_client(api_context["sender_user"]).post(
        TRANSFER_URL,
        transfer_payload(api_context["recipient"], amount),
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"invalid-{amount}",
    )

    assert response.status_code == 400
    assert response.data["error"]["code"] == "INVALID_AMOUNT"


def test_self_transfer_is_rejected(api_context):
    response = authenticated_client(api_context["sender_user"]).post(
        TRANSFER_URL,
        transfer_payload(api_context["sender"], "1.00"),
        format="json",
        HTTP_IDEMPOTENCY_KEY="self-transfer",
    )

    assert response.status_code == 400
    assert response.data["error"]["code"] == "INVALID_TRANSFER"


@pytest.mark.parametrize("status", [Account.Status.FROZEN, Account.Status.CLOSED])
def test_frozen_or_closed_sender_is_rejected(api_context, status):
    sender = api_context["sender"]
    sender.status = status
    sender.save(update_fields=["status", "updated_at"])

    response = authenticated_client(api_context["sender_user"]).post(
        TRANSFER_URL,
        transfer_payload(api_context["recipient"], "1.00"),
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"sender-{status}",
    )

    assert response.status_code == 409
    assert response.data["error"]["code"] == "ACCOUNT_UNAVAILABLE"


@pytest.mark.parametrize(
    ("recipient_status", "expected_status"),
    [(Account.Status.FROZEN, 201), (Account.Status.CLOSED, 409)],
)
def test_recipient_status_policy(api_context, recipient_status, expected_status):
    sender = api_context["sender"]
    recipient = api_context["recipient"]
    recipient.status = recipient_status
    recipient.save(update_fields=["status", "updated_at"])
    fund_account(api_context["treasury"], sender)

    response = authenticated_client(api_context["sender_user"]).post(
        TRANSFER_URL,
        transfer_payload(recipient, "1.00"),
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"recipient-{recipient_status}",
    )

    assert response.status_code == expected_status


def test_missing_idempotency_key_is_rejected(api_context):
    response = authenticated_client(api_context["sender_user"]).post(
        TRANSFER_URL,
        transfer_payload(api_context["recipient"]),
        format="json",
    )

    assert response.status_code == 400
    assert response.data["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_exact_retry_returns_original_result_without_duplicate_movement(api_context):
    sender = api_context["sender"]
    recipient = api_context["recipient"]
    fund_account(api_context["treasury"], sender)
    client = authenticated_client(api_context["sender_user"])

    first = client.post(
        TRANSFER_URL,
        transfer_payload(recipient, "100.0"),
        format="json",
        HTTP_IDEMPOTENCY_KEY="ABC123",
    )
    second = client.post(
        TRANSFER_URL,
        transfer_payload(recipient, "100.00"),
        format="json",
        HTTP_IDEMPOTENCY_KEY="ABC123",
    )

    assert first.status_code == second.status_code == 201
    assert first.data == second.data
    assert Transaction.objects.filter(sender=sender, amount=Decimal("100.00")).count() == 1
    transaction = Transaction.objects.get(id=first.data["id"])
    assert transaction.ledger_entries.count() == 2
    assert calculate_balance(sender) == Decimal("400.00")


def test_same_key_with_different_payload_returns_conflict(api_context):
    fund_account(api_context["treasury"], api_context["sender"])
    client = authenticated_client(api_context["sender_user"])
    first = client.post(
        TRANSFER_URL,
        transfer_payload(api_context["recipient"], "100.00"),
        format="json",
        HTTP_IDEMPOTENCY_KEY="conflicting-key",
    )
    second = client.post(
        TRANSFER_URL,
        transfer_payload(api_context["recipient"], "101.00"),
        format="json",
        HTTP_IDEMPOTENCY_KEY="conflicting-key",
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.data["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_failed_transfer_does_not_consume_idempotency_key(api_context):
    sender = api_context["sender"]
    recipient = api_context["recipient"]
    client = authenticated_client(api_context["sender_user"])
    payload = transfer_payload(recipient)

    failed = client.post(
        TRANSFER_URL,
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="retry-after-failure",
    )
    fund_account(api_context["treasury"], sender)
    retried = client.post(
        TRANSFER_URL,
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="retry-after-failure",
    )

    assert failed.status_code == 422
    assert retried.status_code == 201
    assert IdempotencyRecord.objects.filter(key="retry-after-failure").count() == 1


def test_account_and_balance_endpoints_are_user_scoped_and_ledger_derived(api_context):
    sender = api_context["sender"]
    fund_account(api_context["treasury"], sender, Decimal("321.50"))
    client = authenticated_client(api_context["sender_user"])

    account_response = client.get("/api/v1/accounts/me/")
    balance_response = client.get("/api/v1/accounts/me/balance/")

    assert account_response.status_code == 200
    assert account_response.data["account_number"] == sender.account_number
    assert balance_response.status_code == 200
    assert balance_response.data == {
        "account_number": sender.account_number,
        "currency": Currency.GHS,
        "balance": "321.50",
    }
    assert not hasattr(sender, "balance")


def test_transaction_history_excludes_unrelated_transactions(api_context):
    own_transaction = fund_account(
        api_context["treasury"], api_context["sender"], Decimal("20.00")
    )
    unrelated_transaction = fund_account(
        api_context["treasury"], api_context["unrelated"], Decimal("30.00")
    )

    response = authenticated_client(api_context["sender_user"]).get(
        "/api/v1/transactions/"
    )

    assert response.status_code == 200
    returned_ids = {item["id"] for item in response.data["results"]}
    assert str(own_transaction.id) in returned_ids
    assert str(unrelated_transaction.id) not in returned_ids


def test_transaction_detail_is_visible_to_sender_and_recipient_only(api_context):
    transaction = fund_account(
        api_context["treasury"], api_context["sender"], Decimal("20.00")
    )
    url = f"/api/v1/transactions/{transaction.id}/"

    sender_response = authenticated_client(api_context["sender_user"]).get(url)
    recipient_response = authenticated_client(
        api_context["treasury"].user
    ).get(url)
    unrelated_response = authenticated_client(api_context["unrelated_user"]).get(url)

    assert sender_response.status_code == 200
    assert recipient_response.status_code == 200
    assert unrelated_response.status_code == 404


def test_invalid_jwt_is_rejected(api_context):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer invalid-token")

    response = client.get("/api/v1/accounts/me/")

    assert response.status_code == 401
    assert response.data["error"]["code"] == "INVALID_AUTHENTICATION"


def test_expired_jwt_is_rejected(api_context):
    token = AccessToken.for_user(api_context["sender_user"])
    token.set_exp(lifetime=timedelta(seconds=-1))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    response = client.get("/api/v1/accounts/me/")

    assert response.status_code == 401
    assert response.data["error"]["code"] == "INVALID_AUTHENTICATION"


def test_openapi_schema_and_swagger_endpoints_work():
    client = APIClient()

    schema_response = client.get("/api/schema/")
    docs_response = client.get("/api/docs/")

    assert schema_response.status_code == 200
    assert b"Idempotency-Key" in schema_response.content
    assert docs_response.status_code == 200


@pytest.mark.django_db(transaction=True)
def test_concurrent_duplicate_requests_create_one_movement(api_context, monkeypatch):
    sender = api_context["sender"]
    recipient = api_context["recipient"]
    fund_account(api_context["treasury"], sender)
    token = str(AccessToken.for_user(api_context["sender_user"]))

    first_balance_read = threading.Event()
    release_first_request = threading.Event()
    second_worker_started = threading.Event()
    invocation_lock = threading.Lock()
    invocation_count = 0
    original_calculate_balance = calculate_balance

    def controlled_balance(account, *, currency=None):
        nonlocal invocation_count
        with invocation_lock:
            invocation_count += 1
            is_first_read = invocation_count == 1
        if is_first_read:
            first_balance_read.set()
            if not release_first_request.wait(timeout=5):
                raise RuntimeError("concurrent idempotency test timed out")
        return original_calculate_balance(account, currency=currency)

    monkeypatch.setattr(
        transfer_services, "calculate_balance", controlled_balance
    )

    def make_request(started_event=None):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                backend_pid = cursor.fetchone()[0]
            if started_event is not None:
                started_event.set()
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
            response = client.post(
                TRANSFER_URL,
                transfer_payload(recipient),
                format="json",
                HTTP_IDEMPOTENCY_KEY="concurrent-duplicate",
            )
            return response.status_code, response.data, backend_pid
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(make_request)
        assert first_balance_read.wait(timeout=5)
        second = executor.submit(make_request, second_worker_started)
        assert second_worker_started.wait(timeout=5)
        time.sleep(0.2)
        assert not second.done(), "duplicate request did not wait for the first request"
        release_first_request.set()
        results = [first.result(timeout=5), second.result(timeout=5)]

    assert [result[0] for result in results] == [201, 201]
    assert results[0][1] == results[1][1]
    assert len({result[2] for result in results}) == 2
    transaction_id = results[0][1]["id"]
    assert IdempotencyRecord.objects.filter(key="concurrent-duplicate").count() == 1
    assert Transaction.objects.filter(id=transaction_id).count() == 1
    assert LedgerEntry.objects.filter(transaction_id=transaction_id).count() == 2
    assert calculate_balance(sender) == Decimal("400.00")
