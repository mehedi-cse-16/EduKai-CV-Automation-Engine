from django.urls import path
from organization.views import (
    OrganizationListCreateView,
    OrganizationDetailView,
    ContactListCreateView,
    ContactDetailView,
    AllContactsListView,
)

app_name = "organization"

urlpatterns = [
    # Organization CRUD
    path("", OrganizationListCreateView.as_view(), name="organization_list_create"),

    # All contacts — must be before <uuid:org_id>/ to avoid conflict
    path("contacts/", AllContactsListView.as_view(), name="all_contacts_list"),

    # Contact CRUD (standalone)
    path("contacts/<uuid:contact_id>/", ContactDetailView.as_view(), name="contact_detail"),

    # Organization detail
    path("<uuid:org_id>/", OrganizationDetailView.as_view(), name="organization_detail"),

    # Contacts under a specific organization
    path("<uuid:org_id>/contacts/", ContactListCreateView.as_view(), name="contact_list_create"),
]