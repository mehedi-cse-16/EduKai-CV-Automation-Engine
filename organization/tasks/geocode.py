import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    name="organization.tasks.geocode_organization",
)
def geocode_organization_task(self, organization_id: str):
    """
    Automatically geocodes an organization's address using its postcode.
    Called after create or update when lat/lng is missing.
    Uses geopy with Nominatim (free, no API key needed).
    """
    from organization.models import Organization

    try:
        org = Organization.objects.get(id=organization_id)
    except Organization.DoesNotExist:
        logger.error(f"[geocode] Organization {organization_id} not found.")
        return

    # ── Already has coordinates — skip ───────────────────────────────────
    if org.latitude and org.longitude:
        logger.info(
            f"[geocode] Organization '{org.name}' already has coordinates. "
            f"Skipping."
        )
        return

    # ── Build search query — postcode is most accurate ────────────────────
    # Fall back to town + county if no postcode
    if org.postcode:
        query = f"{org.postcode}, UK"
    elif org.town:
        query = f"{org.town}, {org.county or ''}, UK".strip(", ")
    else:
        logger.warning(
            f"[geocode] Organization '{org.name}' has no postcode or town. "
            f"Cannot geocode."
        )
        return

    try:
        from geopy.geocoders import Nominatim
        from geopy.exc import GeocoderTimedOut, GeocoderServiceError

        geolocator = Nominatim(user_agent="edukai_geocoder")
        location = geolocator.geocode(query, timeout=10)

        if location:
            org.latitude  = round(location.latitude, 6)
            org.longitude = round(location.longitude, 6)
            org.save(update_fields=["latitude", "longitude", "updated_at"])
            logger.info(
                f"[geocode] ✅ Organization '{org.name}' geocoded: "
                f"lat={org.latitude}, lng={org.longitude} "
                f"(query: '{query}')"
            )
        else:
            logger.warning(
                f"[geocode] ⚠️ No location found for '{org.name}' "
                f"with query '{query}'."
            )

    except Exception as exc:
        logger.error(f"[geocode] ❌ Geocoding failed for '{org.name}': {exc}")
        raise self.retry(exc=exc)