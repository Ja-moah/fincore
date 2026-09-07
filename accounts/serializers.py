from rest_framework import serializers

from .models import Account


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = ("account_number", "currency", "status", "created_at")
        read_only_fields = fields


class BalanceSerializer(serializers.Serializer):
    account_number = serializers.CharField()
    currency = serializers.CharField()
    balance = serializers.DecimalField(max_digits=19, decimal_places=2)
