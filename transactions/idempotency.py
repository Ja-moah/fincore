import hashlib
import json

from django.db import IntegrityError, transaction as db_transaction

from .models import IdempotencyRecord
from .services import transfer_funds


class IdempotencyError(Exception):
    code = "IDEMPOTENCY_ERROR"


class IdempotencyConflictError(IdempotencyError):
    code = "IDEMPOTENCY_CONFLICT"


class IdempotencyStateError(IdempotencyError):
    code = "IDEMPOTENCY_STATE_ERROR"


def build_transfer_fingerprint(*, sender_account, recipient_account, amount, currency):
    normalized_payload = {
        "amount": f"{amount:.2f}",
        "currency": currency,
        "recipient_account": recipient_account.account_number,
        "sender_account": sender_account.account_number,
    }
    encoded = json.dumps(
        normalized_payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_transfer_response(financial_transaction):
    return {
        "id": str(financial_transaction.id),
        "status": financial_transaction.status,
        "amount": f"{financial_transaction.amount:.2f}",
        "currency": financial_transaction.currency,
        "sender_account": financial_transaction.sender.account_number,
        "recipient_account": financial_transaction.recipient.account_number,
        "created_at": financial_transaction.created_at.isoformat().replace(
            "+00:00", "Z"
        ),
    }


def execute_idempotent_transfer(
    *,
    user,
    key,
    fingerprint,
    sender_account,
    recipient_account,
    amount,
    currency,
    request_id=None,
):
    """Create or safely replay a transfer under a user-scoped key.

    The unique-key insert and transfer share one outer transaction. A competing
    insert waits for the first request to commit, then resolves the existing
    record without repeating the financial operation.
    """

    with db_transaction.atomic():
        try:
            with db_transaction.atomic():
                record = IdempotencyRecord.objects.create(
                    user=user,
                    key=key,
                    request_fingerprint=fingerprint,
                )
            created = True
        except IntegrityError:
            record = IdempotencyRecord.objects.select_for_update().get(
                user=user, key=key
            )
            created = False

        if not created:
            if record.request_fingerprint != fingerprint:
                raise IdempotencyConflictError(
                    "This idempotency key was already used for another request."
                )
            if record.transaction_id is None or record.response_body is None:
                raise IdempotencyStateError(
                    "The idempotency record has no completed response."
                )
            return record.response_body, record.response_status or 201, True

        financial_transaction = transfer_funds(
            sender_id=sender_account.pk,
            recipient_id=recipient_account.pk,
            amount=amount,
            currency=currency,
            actor=user,
            request_id=request_id,
        )
        response_body = build_transfer_response(financial_transaction)
        record.transaction = financial_transaction
        record.response_status = 201
        record.response_body = response_body
        record.save(
            update_fields=["transaction", "response_status", "response_body"]
        )
        return response_body, 201, False
