from django.urls import path
from candidate.views import (
    BatchListView,
    BatchStatusView,
    BatchDeleteView,
    BulkCVUploadView,
    CandidateDetailView,
    CandidateDeleteView,
    CandidateListView,
    CandidateUpdateView,
)

app_name = "candidate"

urlpatterns = [
    path("",                                    CandidateListView.as_view(),   name="candidate_list"),
    path("upload/",                             BulkCVUploadView.as_view(),    name="bulk_upload"),
    path("<uuid:candidate_id>/",                CandidateDetailView.as_view(), name="candidate_detail"),
    path("<uuid:candidate_id>/update/",         CandidateUpdateView.as_view(), name="candidate_update"),
    path("<uuid:candidate_id>/delete/",         CandidateDeleteView.as_view(), name="candidate_delete"),


    path("batches/",                            BatchListView.as_view(),        name="batch_list"),
    path("batches/<uuid:batch_id>/",            BatchStatusView.as_view(),     name="batch_status"),
    path("batches/<uuid:batch_id>/delete/",     BatchDeleteView.as_view(),     name="batch_delete"),
]