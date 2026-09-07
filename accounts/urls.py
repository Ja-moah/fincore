from django.urls import path

from .views import BalanceView, MeView


urlpatterns = [
    path("accounts/me/", MeView.as_view(), name="account-me"),
    path("accounts/me/balance/", BalanceView.as_view(), name="account-balance"),
]
