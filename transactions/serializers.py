from decimal import Decimal

from rest_framework import serializers

from accounts.models import Currency

from .models import Transaction


class TransferRequestSerializer(serializers.Serializer):
    recipient_account = serializers.CharField(max_length=34, trim_whitespace=True)
    amount = serializers.DecimalField(
        max_digits=19,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    currency = serializers.ChoiceField(choices=Currency)


class TransactionSerializer(serializers.ModelSerializer):
    sender_account = serializers.CharField(source="sender.account_number")
    recipient_account = serializers.CharField(source="recipient.account_number")

    class Meta:
        model = Transaction
        fields = (
            "id",
            "status",
            "amount",
            "currency",
            "sender_account",
            "recipient_account",
            "created_at",
        )
        read_only_fields = fields


class TransferResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()
    amount = serializers.DecimalField(max_digits=19, decimal_places=2)
    currency = serializers.CharField()
    sender_account = serializers.CharField()
    recipient_account = serializers.CharField()
    created_at = serializers.DateTimeField()


class ErrorDetailSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()


class ErrorResponseSerializer(serializers.Serializer):
    error = ErrorDetailSerializer()
