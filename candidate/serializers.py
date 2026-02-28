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

    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------
    def validate_experience(self, value):
        """
        form-data always sends strings.
        Accept: "2", "2.0", "1.5", "", None
        Reject: "abc", "-1", "999"
        """
        if value in (None, "", "null", "none"):
            return None
        try:
            result = float(value)
        except (ValueError, TypeError):
            raise serializers.ValidationError(
                "Enter a valid number. e.g. 2.0, 1.5, 0.5"
            )
        if result < 0 or result > 60:
            raise serializers.ValidationError(
                "Experience must be between 0 and 60."
            )
        return result   # returns a float, not a string

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

    # -------------------------------------------------------------------------
    # List field helper — handles repeated keys AND JSON strings
    # -------------------------------------------------------------------------
    def _parse_list_field(self, value, field_name: str) -> list:
        if not value:
            return []

        if isinstance(value, list):
            # Check if it's a single-item list containing a JSON string
            # e.g. ['["math", "physics"]']  ← sent as JSON string in one field
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
            # Normal repeated-key list
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

    # -------------------------------------------------------------------------
    # Output
    # -------------------------------------------------------------------------
    def get_additional_info(self) -> dict:
        data = self.validated_data
        info = {}
        if data.get("experience") is not None:
            info["experience"] = data["experience"]     # already a float from validate_experience
        if data.get("skills"):
            info["skills"] = data["skills"]
        if data.get("job_role"):
            info["job_role"] = data["job_role"]
        return info


class CandidateListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""

    class Meta:
        model = Candidate
        fields = [
            "id",
            "name",
            "email",
            "location",
            "years_of_experience",
            "skills",
            "source",
            "availability_status",
            "quality_status",
            "ai_processing_status",
            "created_at",
        ]


class CandidateDetailSerializer(serializers.ModelSerializer):
    """Full serializer for detail view."""

    class Meta:
        model = Candidate
        fields = "__all__"


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