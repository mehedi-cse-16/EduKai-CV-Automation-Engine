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
    CandidateUpdateSerializer,
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
        for index, cv_file in enumerate(validated_files):
            candidate = Candidate.objects.create(
                batch=batch,
                source=SourceChoices.LOCAL_UPLOAD,
                original_cv_file=cv_file,
            )
            candidates_created += 1

            process_cv_task.apply_async(
                args=[str(candidate.id), additional_info],
                countdown=index * 2,
                queue="default",
            )

        logger.info(f"[upload] Batch {batch.id}: {candidates_created} tasks queued.")

        return Response(
            {
                "message": f"{candidates_created} CV(s) accepted and queued for processing.",
                "batch":   UploadBatchSerializer(batch).data,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class BatchListView(APIView):
    """
    GET /api/candidates/batches/
    Returns all upload batches with optional filters.

    Query params:
        ?ordering=created_at        → oldest first
        ?ordering=-created_at       → newest first (default)
    """

    permission_classes = [IsAuthenticated, IsSuperUser]

    @extend_schema(
        responses={200: UploadBatchSerializer(many=True)},
        summary="List all upload batches",
        tags=["Candidates"],
    )
    def get(self, request):
        qs = CandidateUploadBatch.objects.all()

        # Optional ordering
        ordering = request.query_params.get("ordering", "-created_at")
        allowed_orderings = {
            "created_at", "-created_at",
            "total_count", "-total_count",
            "processed_count", "-processed_count",
            "failed_count", "-failed_count",
        }
        if ordering in allowed_orderings:
            qs = qs.order_by(ordering)

        serializer = UploadBatchSerializer(qs, many=True)
        return Response(serializer.data)


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


class CandidateDeleteView(APIView):
    """
    DELETE /api/candidates/<candidate_id>/delete/
    Deletes candidate from DB instantly.
    MinIO file cleanup happens async via Celery.
    """
    permission_classes = [IsAuthenticated, IsSuperUser]

    @extend_schema(
        responses={
            200: OpenApiResponse(description="Candidate deleted successfully"),
            404: OpenApiResponse(description="Candidate not found"),
        },
        summary="Delete a candidate and their MinIO files",
        tags=["Candidates"],
    )
    def delete(self, request, candidate_id):
        try:
            candidate = Candidate.objects.get(id=candidate_id)
        except Candidate.DoesNotExist:
            return Response(
                {"detail": "Candidate not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        name = candidate.name or str(candidate_id)

        # ✅ Collect file keys BEFORE deleting (after delete they're gone from instance)
        file_keys = [
            k for k in [
                candidate.original_cv_file.name  if candidate.original_cv_file  else None,
                candidate.ai_enhanced_cv_file.name if candidate.ai_enhanced_cv_file else None,
            ]
            if k
        ]

        # ✅ Delete DB record instantly — no waiting for MinIO
        candidate.delete()

        # ✅ Clean up MinIO async — won't block the response
        if file_keys:
            from candidate.tasks.cleanup import cleanup_minio_files_task
            cleanup_minio_files_task.apply_async(args=[file_keys])

        logger.info(
            f"[delete] Candidate '{name}' ({candidate_id}) DB deleted. "
            f"MinIO cleanup queued for {len(file_keys)} file(s)."
        )

        return Response(
            {
                "message": f"Candidate '{name}' deleted. "
                           f"{len(file_keys)} file(s) queued for MinIO cleanup.",
            },
            status=status.HTTP_200_OK,
        )


class BatchDeleteView(APIView):
    """
    DELETE /api/candidates/batches/<batch_id>/delete/
    Deletes batch + ALL candidates instantly.
    MinIO cleanup for ALL files happens async via Celery.
    """
    permission_classes = [IsAuthenticated, IsSuperUser]

    @extend_schema(
        responses={
            200: OpenApiResponse(description="Batch and all candidates deleted"),
            404: OpenApiResponse(description="Batch not found"),
        },
        summary="Delete a batch and all its candidates + MinIO files",
        tags=["Candidates"],
    )
    def delete(self, request, batch_id):
        try:
            batch = CandidateUploadBatch.objects.get(id=batch_id)
        except CandidateUploadBatch.DoesNotExist:
            return Response(
                {"detail": "Batch not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ✅ Collect ALL file keys from ALL candidates BEFORE any deletion
        file_keys = []
        candidates = batch.candidates.all()
        candidate_count = candidates.count()

        for candidate in candidates:
            if candidate.original_cv_file and candidate.original_cv_file.name:
                file_keys.append(candidate.original_cv_file.name)
            if candidate.ai_enhanced_cv_file and candidate.ai_enhanced_cv_file.name:
                file_keys.append(candidate.ai_enhanced_cv_file.name)

        # ✅ Delete DB records instantly (CASCADE deletes all candidates too)
        # post_delete signal is now disconnected from MinIO cleanup
        # so this is fast — pure DB operation only
        batch.delete()

        # ✅ Queue MinIO cleanup as a single async Celery task
        # Uses S3 batch delete_objects — deletes 1000 files per API call
        if file_keys:
            from candidate.tasks.cleanup import cleanup_minio_files_task
            cleanup_minio_files_task.apply_async(args=[file_keys])

        logger.info(
            f"[delete] Batch {batch_id} deleted. "
            f"{candidate_count} candidates removed from DB. "
            f"MinIO cleanup queued for {len(file_keys)} file(s)."
        )

        return Response(                              # ✅ 200 so body is always visible
            {
                "message":         f"Batch deleted successfully.",
                "candidates_deleted": candidate_count,
                "files_queued":    len(file_keys),
            },
            status=status.HTTP_200_OK,
        )


class CandidateUpdateView(APIView):
    """
    PATCH /api/candidates/<candidate_id>/update/

    Partially update editable candidate fields.
    All fields are optional — only send what you want to change.

    ✅ Editable:  name, email, whatsapp_number, location,
                  years_of_experience, skills, source,
                  availability_status, quality_status,
                  email_subject, email_body, notes

    ❌ NOT editable via this endpoint:
                  id, batch, created_at, updated_at,
                  ai_processing_status, ai_task_id,
                  ai_enhanced_cv_content, ai_enhanced_cv_file,
                  ai_failure_reason, ai_retry_count,
                  original_cv_file  (use separate CV upload flow)
    """
    permission_classes = [IsAuthenticated, IsSuperUser]

    @extend_schema(
        request=CandidateUpdateSerializer,
        responses={
            200: CandidateDetailSerializer,
            400: OpenApiResponse(description="Validation error"),
            404: OpenApiResponse(description="Candidate not found"),
        },
        summary="Partially update candidate information",
        tags=["Candidates"],
    )
    def patch(self, request, candidate_id):
        try:
            candidate = Candidate.objects.get(id=candidate_id)
        except Candidate.DoesNotExist:
            return Response(
                {"detail": "Candidate not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CandidateUpdateSerializer(
            candidate,
            data=request.data,
            partial=True,           # ✅ all fields optional
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()           # calls update() internally

        logger.info(
            f"[update] Candidate {candidate_id} updated. "
            f"Fields changed: {list(serializer.validated_data.keys())}"
        )

        # ✅ Return full detail response so frontend gets updated pre-signed URLs too
        return Response(
            CandidateDetailSerializer(candidate, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )