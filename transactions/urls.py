from django.urls import path

from .views import TransactionDetailView, TransactionListView, TransferCreateView


urlpatterns = [
    path("transfers/", TransferCreateView.as_view(), name="transfer-create"),
    path("transactions/", TransactionListView.as_view(), name="transaction-list"),
    path(
        "transactions/<uuid:transaction_id>/",
        TransactionDetailView.as_view(),
        name="transaction-detail",
    ),
]
