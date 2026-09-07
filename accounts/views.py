from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from ledger.services import CurrencyMismatchError, calculate_balance

from .serializers import AccountSerializer, BalanceSerializer
from .services import (
    AmbiguousUserAccountError,
    UserAccountNotFoundError,
    get_user_account,
)


def account_error_response(exc):
    if isinstance(exc, UserAccountNotFoundError):
        return Response(
            {"error": {"code": "ACCOUNT_NOT_FOUND", "message": str(exc)}},
            status=404,
        )
    return Response(
        {"error": {"code": "ACCOUNT_SELECTION_REQUIRED", "message": str(exc)}},
        status=409,
    )


class MeView(APIView):
    @extend_schema(responses=AccountSerializer)
    def get(self, request):
        try:
            account = get_user_account(request.user)
        except (UserAccountNotFoundError, AmbiguousUserAccountError) as exc:
            return account_error_response(exc)
        return Response(AccountSerializer(account).data)


class BalanceView(APIView):
    @extend_schema(responses=BalanceSerializer)
    def get(self, request):
        try:
            account = get_user_account(request.user)
            balance = calculate_balance(account)
        except (UserAccountNotFoundError, AmbiguousUserAccountError) as exc:
            return account_error_response(exc)
        except CurrencyMismatchError as exc:
            return Response(
                {"error": {"code": "CURRENCY_MISMATCH", "message": str(exc)}},
                status=409,
            )
        data = {
            "account_number": account.account_number,
            "currency": account.currency,
            "balance": balance,
        }
        return Response(BalanceSerializer(data).data)
