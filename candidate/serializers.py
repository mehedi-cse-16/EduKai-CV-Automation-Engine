import os
import json

from django.conf import settings
from rest_framework import serializers

from candidate.models import Candidate, CandidateUploadBatch


class BulkCVUploadSerializer(serializers.Serializer):

    files = serializers.ListField(
        child=serializers.FileField(
            max_length=100,
            allow_empty_file=False,
        ),
        min_length=1,
        max_length=10000,
    )

    experience = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        default=None,
        help_text="e.g. 2.0 — minimum years of experience",
    )

    skills = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        default=list,
    )

    job_role = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        default=list,
    )

    def validate_experience(self, value):
        if value in (None, "", "null", "none"):
            return None
        try:
            result = float(value)
        except (ValueError, TypeError):
            raise serializers.ValidationError("Enter a valid number. e.g. 2.0, 1.5, 0.5")
        if result < 0 or result > 60:
            raise serializers.ValidationError("Experience must be between 0 and 60.")
        return result

    def validate_skills(self, value):
        return self._parse_list_field(value, "skills")

    def validate_job_role(self, value):
        return self._parse_list_field(value, "job_role")

    def validate_files(self, files):
        allowed_extensions = {"pdf", "doc", "docx"}
        max_size_mb = 10
        for f in files:
            ext = f.name.rsplit(".", 1)[-1].lower()
            if ext not in allowed_extensions:
                raise serializers.ValidationError(
                    f"File '{f.name}' has unsupported type '.{ext}'. "
                    f"Allowed: {', '.join(allowed_extensions)}"
                )
            if f.size > max_size_mb * 1024 * 1024:
                raise serializers.ValidationError(
                    f"File '{f.name}' exceeds {max_size_mb}MB limit."
                )
        return files

    def _parse_list_field(self, value, field_name: str) -> list:
        if not value:
            return []
        if isinstance(value, list):
            if len(value) == 1 and isinstance(value[0], str):
                stripped = value[0].strip()
                if stripped.startswith("["):
                    try:
                        parsed = json.loads(stripped)
                        if isinstance(parsed, list):
                            return [str(i).strip() for i in parsed if str(i).strip()]
                    except json.JSONDecodeError:
                        raise serializers.ValidationError(
                            f"Invalid JSON array for '{field_name}'. "
                            f'Use: ["val1", "val2"] or send as repeated keys.'
                        )
            return [str(i).strip() for i in value if str(i).strip()]
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return [str(i).strip() for i in parsed if str(i).strip()]
                except json.JSONDecodeError:
                    raise serializers.ValidationError(
                        f"Invalid JSON array for '{field_name}'."
                    )
            return [stripped] if stripped else []
        return []

    def get_additional_info(self) -> dict:
        data = self.validated_data
        info = {}
        if data.get("experience") is not None:
            info["experience"] = data["experience"]
        if data.get("skills"):
            info["skills"] = data["skills"]
        if data.get("job_role"):
            info["job_role"] = data["job_role"]
        return info


# =============================================================================
# ✅ Mixin — reusable pre-signed URL fields for any Candidate serializer
# =============================================================================
class CandidateFileMixin:
    """
    Adds pre-signed (or local) URLs for:
      - original_cv_file  → original_cv_url
      - ai_enhanced_cv_file → enhanced_cv_url
    """

    def get_original_cv_url(self, obj) -> str | None:
        from candidate.utils.minio_utils import resolve_file_url
        return resolve_file_url(obj.original_cv_file)

    def get_enhanced_cv_url(self, obj) -> str | None:
        from candidate.utils.minio_utils import resolve_file_url
        return resolve_file_url(obj.ai_enhanced_cv_file)


# =============================================================================
# List Serializer — lightweight, includes CV URLs
# =============================================================================
class CandidateListSerializer(CandidateFileMixin, serializers.ModelSerializer):
    """Lightweight serializer for list views."""

    # ✅ These replace the raw FileField values with pre-signed URLs
    # original_cv_url  = serializers.SerializerMethodField()
    # enhanced_cv_url  = serializers.SerializerMethodField()

    class Meta:
        model = Candidate
        fields = [
            "id",
            "name",
            "email",
            "whatsapp_number",
            "location",
            "years_of_experience",
            "skills",
            "source",
            "availability_status",
            "quality_status",
            "ai_processing_status",
            # "original_cv_url",        # ✅ pre-signed original CV URL
            # "enhanced_cv_url",        # ✅ pre-signed enhanced CV URL
            "created_at",
        ]


# =============================================================================
# Detail Serializer — full data, includes CV URLs
# =============================================================================
class CandidateDetailSerializer(CandidateFileMixin, serializers.ModelSerializer):
    """Full serializer for detail view."""

    # ✅ These replace the raw FileField values with pre-signed URLs
    original_cv_url  = serializers.SerializerMethodField()
    enhanced_cv_url  = serializers.SerializerMethodField()

    class Meta:
        model = Candidate
        fields = [
            "id",
            "batch",
            "name",
            "email",
            "whatsapp_number",
            "location",
            "years_of_experience",
            "skills",
            "source",
            "availability_status",
            "quality_status",
            "ai_processing_status",
            "ai_task_id",
            "ai_enhanced_cv_content",
            "ai_failure_reason",
            "ai_retry_count",
            "email_subject",
            "email_body",
            "notes",
            "original_cv_url",        # ✅ pre-signed original CV URL
            "enhanced_cv_url",        # ✅ pre-signed enhanced CV URL
            "created_at",
            "updated_at",
        ]


# =============================================================================
# Batch Serializer
# =============================================================================
class UploadBatchSerializer(serializers.ModelSerializer):
    """Serializer for batch status tracking."""

    class Meta:
        model = CandidateUploadBatch
        fields = [
            "id",
            "additional_info",
            "total_count",
            "processed_count",
            "failed_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class UploadBatchSerializer(serializers.ModelSerializer):
    """Serializer for batch status tracking."""

    # ✅ Computed fields — useful for frontend progress bars
    progress_percentage = serializers.SerializerMethodField()
    status              = serializers.SerializerMethodField()

    class Meta:
        model = CandidateUploadBatch
        fields = [
            "id",
            "additional_info",
            "total_count",
            "processed_count",
            "failed_count",
            "progress_percentage",   # ✅ e.g. 75
            "status",                # ✅ e.g. "in_progress" / "completed" / "partial"
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_progress_percentage(self, obj) -> int:
        """
        Returns integer percentage of successfully processed CVs.
        e.g. 3 processed out of 4 total → 75
        """
        if not obj.total_count:
            return 0
        return int((obj.processed_count / obj.total_count) * 100)

    def get_status(self, obj) -> str:
        """
        Derives batch status from counts:
          completed → all CVs processed successfully
          partial   → some failed, some succeeded
          failed    → all failed
          in_progress → still processing (none done yet or still running)
        """
        if obj.total_count == 0:
            return "empty"

        finished = obj.processed_count + obj.failed_count

        if finished < obj.total_count:
            return "in_progress"

        # All finished — determine outcome
        if obj.failed_count == 0:
            return "completed"
        elif obj.processed_count == 0:
            return "failed"
        else:
            return "partial"   # some passed, some failed