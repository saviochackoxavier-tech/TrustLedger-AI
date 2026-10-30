"""TrustLedger AI — Root URL configuration (delegates to the app router)."""

from django.shortcuts import render

from django.urls import include, path

urlpatterns = [
    path("", include("trustledger.urls")),
]


# Dark, on-brand error pages (active when DEBUG=0; Django shows its debug
# pages in development).
def handler403(request, exception=None):
    return render(
        request, "trustledger/error.html",
        {"message": "Request blocked — CSRF verification failed.", "status": 403},
        status=403,
    )


def handler404(request, exception=None):
    return render(
        request, "trustledger/error.html",
        {"message": "This page does not exist.", "status": 404},
        status=404,
    )


def handler500(request):
    return render(
        request, "trustledger/error.html",
        {"message": "Something went wrong on our side. Nothing was settled.", "status": 500},
        status=500,
    )
