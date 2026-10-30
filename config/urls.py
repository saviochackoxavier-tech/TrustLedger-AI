"""TrustLedger AI — Root URL configuration (delegates to the app router)."""

from django.urls import include, path

urlpatterns = [
    path("", include("trustledger.urls")),
]
