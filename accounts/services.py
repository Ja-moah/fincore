class UserAccountNotFoundError(Exception):
    pass


class AmbiguousUserAccountError(Exception):
    pass


def get_user_account(user):
    accounts = list(user.financial_accounts.order_by("pk")[:2])
    if not accounts:
        raise UserAccountNotFoundError("The authenticated user has no account.")
    if len(accounts) > 1:
        raise AmbiguousUserAccountError(
            "The authenticated user has multiple accounts; explicit account "
            "selection is not supported yet."
        )
    return accounts[0]
