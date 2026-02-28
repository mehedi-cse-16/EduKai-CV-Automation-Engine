from django.contrib import admin
from .models import Organization

@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "email",
        "contact_person_name",
        "status",
        "industry_type",
        "location",
        "job_title",
        "radius",
    )
    list_filter = ("status", "industry_type", "location")
    search_fields = ("name", "email", "contact_person_name", "job_title")
    ordering = ("-created_at",)