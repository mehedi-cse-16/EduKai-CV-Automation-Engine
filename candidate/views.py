import logging
from typing import cast

from django.http import QueryDict

from drf_spectacular.utils import extend_schema, OpenApiResponse

from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from account.permissions import IsSuperUser
from candidate.models import Candidate, CandidateUploadBatch, SourceChoices
from candidate.serializers import (
    BulkCVUploadSerializer,
    CandidateDetailSerializer,
    CandidateListSerializer,
    UploadBatchSerializer,
)
from candidate.tasks.process_cv import process_cv_task

logger = logging.getLogger(__name__)


class BulkCVUploadView(APIView):
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated, IsSuperUser]

    @extend_schema(
        request=BulkCVUploadSerializer,
        responses={
            202: OpenApiResponse(description="Batch accepted and processing started"),
            400: OpenApiResponse(description="Validation error"),
        },
        summary="Bulk upload CVs for AI processing",
        tags=["Candidates"],
    )
    def post(self, request):
        files = request.FILES.getlist("files")
        query_data = cast(QueryDict, request.data)

        data = {
            "files":      files,
            "experience": query_data.get("experience", None),
            "skills":     query_data.getlist("skills"),
            "job_role":   query_data.getlist("job_role"),
        }

        serializer = cast(BulkCVUploadSerializer, BulkCVUploadSerializer(data=data))
        serializer.is_valid(raise_exception=True)

        validated_data  = cast(dict, serializer.validated_data)
        validated_files = validated_data["files"]
        additional_info = serializer.get_additional_info()

        batch = CandidateUploadBatch.objects.create(
            additional_info=additional_info,
            total_count=len(validated_files),
        )

        logger.info(f"[upload] Batch {batch.id} created with {batch.total_count} CVs.")

        candidates_created = 0
        for cv_file in validated_files:
            candidate = Candidate.objects.create(
                batch=batch,
                source=SourceChoices.LOCAL_UPLOAD,
                original_cv_file=cv_file,
            )
            candidates_created += 1

            process_cv_task.apply_async(
                args=[str(candidate.id), additional_info],
                countdown=0,
            )

        logger.info(f"[upload] Batch {batch.id}: {candidates_created} tasks queued.")

        return Response(
            {
                "message": f"{candidates_created} CV(s) accepted and queued for processing.",
                "batch":   UploadBatchSerializer(batch).data,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class BatchStatusView(APIView):
    """
    GET /api/candidates/batches/<batch_id>/
    Returns the processing status of a batch.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: UploadBatchSerializer},
        summary="Get batch processing status",
        tags=["Candidates"],
    )
    def get(self, request, batch_id):
        try:
            batch = CandidateUploadBatch.objects.get(id=batch_id)
        except CandidateUploadBatch.DoesNotExist:
            return Response(
                {"detail": "Batch not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(UploadBatchSerializer(batch).data)


class CandidateListView(APIView):
    """
    GET /api/candidates/
    Returns paginated list of candidates with optional filters.
    """

    permission_classes = [IsAuthenticated, IsSuperUser]

    @extend_schema(
        responses={200: CandidateListSerializer(many=True)},
        summary="List all candidates",
        tags=["Candidates"],
    )
    def get(self, request):
        qs = Candidate.objects.select_related("batch").all()

        # Simple filters
        quality = request.query_params.get("quality_status")
        availability = request.query_params.get("availability_status")
        ai_status = request.query_params.get("ai_processing_status")
        source = request.query_params.get("source")

        if quality:
            qs = qs.filter(quality_status=quality)
        if availability:
            qs = qs.filter(availability_status=availability)
        if ai_status:
            qs = qs.filter(ai_processing_status=ai_status)
        if source:
            qs = qs.filter(source=source)

        serializer = CandidateListSerializer(qs, many=True)
        return Response(serializer.data)


class CandidateDetailView(APIView):
    """
    GET /api/candidates/<candidate_id>/
    Returns full candidate details including AI content.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: CandidateDetailSerializer},
        summary="Get candidate details",
        tags=["Candidates"],
    )
    def get(self, request, candidate_id):
        try:
            candidate = Candidate.objects.get(id=candidate_id)
        except Candidate.DoesNotExist:
            return Response(
                {"detail": "Candidate not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CandidateDetailSerializer(candidate)
        return Response(serializer.data)