from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Account
from accounts.services import (
    AmbiguousUserAccountError,
    UserAccountNotFoundError,
    get_user_account,
)

from .idempotency import (
    IdempotencyConflictError,
    IdempotencyStateError,
    build_transfer_fingerprint,
    execute_idempotent_transfer,
)
from .models import Transaction
from .serializers import (
    ErrorResponseSerializer,
    TransactionSerializer,
    TransferRequestSerializer,
    TransferResponseSerializer,
)
from .services import (
    AccountNotFoundError,
    AccountUnavailableError,
    CurrencyMismatchError,
    InsufficientFundsError,
    InvalidTransferError,
)


def error_response(code, message, http_status):
    return Response(
        {"error": {"code": code, "message": message}},
        status=http_status,
    )


class TransferCreateView(APIView):
    @extend_schema(
        request=TransferRequestSerializer,
        parameters=[
            OpenApiParameter(
                name="Idempotency-Key",
                type=str,
                location=OpenApiParameter.HEADER,
                required=True,
                description="User-scoped key used to safely replay this request.",
            )
        ],
        responses={
            201: TransferResponseSerializer,
            400: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
            422: ErrorResponseSerializer,
        },
    )
    def post(self, request):
        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        if not idempotency_key:
            return error_response(
                "IDEMPOTENCY_KEY_REQUIRED",
                "Idempotency-Key header is required.",
                status.HTTP_400_BAD_REQUEST,
            )
        if len(idempotency_key) > 255:
            return error_response(
                "INVALID_IDEMPOTENCY_KEY",
                "Idempotency-Key cannot exceed 255 characters.",
                status.HTTP_400_BAD_REQUEST,
            )

        request_serializer = TransferRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        data = request_serializer.validated_data

        try:
            sender = get_user_account(request.user)
        except UserAccountNotFoundError as exc:
            return error_response("ACCOUNT_NOT_FOUND", str(exc), status.HTTP_404_NOT_FOUND)
        except AmbiguousUserAccountError as exc:
            return error_response(
                "ACCOUNT_SELECTION_REQUIRED", str(exc), status.HTTP_409_CONFLICT
            )

        try:
            recipient = Account.objects.get(
                account_number=data["recipient_account"]
            )
        except Account.DoesNotExist:
            return error_response(
                "ACCOUNT_NOT_FOUND",
                "Recipient account does not exist.",
                status.HTTP_404_NOT_FOUND,
            )

        fingerprint = build_transfer_fingerprint(
            sender_account=sender,
            recipient_account=recipient,
            amount=data["amount"],
            currency=data["currency"],
        )
        try:
            response_body, response_status, _replayed = execute_idempotent_transfer(
                user=request.user,
                key=idempotency_key,
                fingerprint=fingerprint,
                sender_account=sender,
                recipient_account=recipient,
                amount=data["amount"],
                currency=data["currency"],
            )
        except IdempotencyConflictError as exc:
            return error_response(exc.code, str(exc), status.HTTP_409_CONFLICT)
        except IdempotencyStateError as exc:
            return error_response(exc.code, str(exc), status.HTTP_409_CONFLICT)
        except InsufficientFundsError as exc:
            return error_response("INSUFFICIENT_FUNDS", str(exc), 422)
        except InvalidTransferError as exc:
            return error_response("INVALID_TRANSFER", str(exc), 400)
        except AccountNotFoundError as exc:
            return error_response("ACCOUNT_NOT_FOUND", str(exc), 404)
        except AccountUnavailableError as exc:
            return error_response("ACCOUNT_UNAVAILABLE", str(exc), 409)
        except CurrencyMismatchError as exc:
            return error_response("CURRENCY_MISMATCH", str(exc), 409)

        return Response(response_body, status=response_status)


class UserTransactionQuerysetMixin:
    def get_queryset(self):
        return (
            Transaction.objects.filter(
                Q(sender__user=self.request.user) | Q(recipient__user=self.request.user)
            )
            .select_related("sender", "recipient")
            .distinct()
            .order_by("-created_at")
        )


@extend_schema(responses=TransactionSerializer(many=True))
class TransactionListView(UserTransactionQuerysetMixin, generics.ListAPIView):
    serializer_class = TransactionSerializer


@extend_schema(
    responses={
        200: TransactionSerializer,
        404: ErrorResponseSerializer,
    }
)
class TransactionDetailView(UserTransactionQuerysetMixin, generics.RetrieveAPIView):
    serializer_class = TransactionSerializer
    lookup_field = "id"
    lookup_url_kwarg = "transaction_id"
