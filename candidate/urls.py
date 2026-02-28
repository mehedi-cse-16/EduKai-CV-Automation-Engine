from django.urls import path
from candidate.views import (
    BatchStatusView,
    BulkCVUploadView,
    CandidateDetailView,
    CandidateListView,
)

app_name = "candidate"

urlpatterns = [
    path("", CandidateListView.as_view(), name="candidate_list"),
    path("upload/", BulkCVUploadView.as_view(), name="bulk_upload"),
    path("batches/<uuid:batch_id>/", BatchStatusView.as_view(), name="batch_status"),
    path("<uuid:candidate_id>/", CandidateDetailView.as_view(), name="candidate_detail"),
]