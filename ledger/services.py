from decimal import Decimal

from .models import LedgerEntry


class CurrencyMismatchError(ValueError):
    pass


def calculate_balance(account, *, currency=None):
    """Return an account balance derived exclusively from its ledger entries."""

    target_currency = currency or account.currency
    if target_currency != account.currency:
        raise CurrencyMismatchError(
            "The requested currency does not match the account currency."
        )

    entries = LedgerEntry.objects.filter(account=account)
    entry_currencies = set(entries.values_list("currency", flat=True).distinct())
    unexpected_currencies = entry_currencies - {target_currency}
    if unexpected_currencies:
        raise CurrencyMismatchError(
            "Ledger entries contain currencies that do not match the account currency."
        )

    balance = Decimal("0.00")
    for entry_type, amount in entries.values_list("entry_type", "amount"):
        if entry_type == LedgerEntry.EntryType.DEBIT:
            balance -= amount
        else:
            balance += amount
    return balance
