"""
TrustLedger AI — URL Routing
============================
    /                     Dashboard home (bento grid)
    /milestones/new/      Create milestone agreement        (POST)
    /pay/<uuid>/          Create PayPal order -> approval   (POST)
    /pay/<uuid>/capture/  PayPal return URL -> capture      (GET ?token=)
    /deliver/<uuid>/      TrustScore delivery audit         (POST)
    /release/<uuid>/      Human-review release approval     (POST)
    /dispute/<uuid>/      AI dispute mediation endpoint     (POST, JSON)
"""

from django.urls import path

from . import views

app_name = "trustledger"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("milestones/new/", views.milestone_create, name="milestone_create"),
    path("pay/<uuid:pk>/", views.fund_escrow, name="fund"),
    path("pay/<uuid:pk>/capture/", views.capture_escrow, name="capture"),
    path("deliver/<uuid:pk>/", views.submit_delivery, name="deliver"),
    path("release/<uuid:pk>/", views.approve_release, name="release"),
    path("dispute/<uuid:pk>/", views.dispute_mediate, name="dispute"),
]
