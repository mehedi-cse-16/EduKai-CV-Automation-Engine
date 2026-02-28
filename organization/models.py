import uuid

from django.db import models


# Choices for status
class StatusChoices(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"

class Organization(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for the organization"
    )
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    contact_person_name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.ACTIVE
    )
    industry_type = models.CharField(max_length=255, null=True, blank=True)
    location = models.CharField(max_length=255, null=True, blank=True)
    job_title = models.CharField(max_length=255, null=True, blank=True)
    radius = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Radius in kilometers or miles"
    )
    skill_requirements = models.JSONField(
        default=list,
        blank=True,
        help_text='List of required skills, e.g., ["Python", "Django"]'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.status})"