from django.urls import path

from . import views

urlpatterns = [
    path("orgs/", views.OrgListView.as_view()),
    path("discrepancies/", views.DiscrepancyListView.as_view()),
    path("summary/", views.SummaryView.as_view()),
]
