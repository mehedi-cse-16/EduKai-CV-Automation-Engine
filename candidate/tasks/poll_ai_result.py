import logging

from celery import shared_task
from django.conf import settings
from django.db import models

import requests

logger = logging.getLogger(__name__)

# Quality check mapping from AI response to model choices
QUALITY_MAP = {
    "pass": "passed",
    "fail": "failed",
}

@shared_task(
    bind=True,
    max_retries=None,       # We control retries manually using AI_POLL_MAX_RETRIES
    name="candidate.tasks.poll_ai_result",
)
def poll_ai_result_task(self, candidate_id: str, ai_task_id: str):
    """
    Task 2 — Polls the AI service for task completion.

    Strategy: Retry with countdown instead of blocking sleep.
    Each retry = one poll attempt. Max attempts = AI_POLL_MAX_RETRIES.
    """
    from candidate.models import Candidate, AIProcessingStatus

    max_retries = settings.AI_POLL_MAX_RETRIES
    poll_interval = settings.AI_POLL_INTERVAL_SECONDS

    # Check how many times we've already retried
    current_attempt = self.request.retries

    if current_attempt >= max_retries:
        logger.error(
            f"[poll_ai] Candidate {candidate_id} exceeded max poll retries ({max_retries})."
        )
        Candidate.objects.filter(id=candidate_id).update(
            ai_processing_status=AIProcessingStatus.FAILED,
            ai_failure_reason=f"AI task polling timed out after {max_retries} attempts.",
        )
        _update_batch_failed(candidate_id)
        return

    try:
        response = requests.get(
            f"{settings.AI_BASE_URL}/api/v1/tasks/{ai_task_id}/",
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

    except requests.RequestException as exc:
        logger.warning(f"[poll_ai] Poll request failed for task {ai_task_id}: {exc}")
        raise self.retry(countdown=poll_interval)

    ai_status = data.get("status", "")

    # Still processing — retry after countdown
    if ai_status == "PENDING" or ai_status == "processing":
        logger.info(
            f"[poll_ai] Task {ai_task_id} still PENDING or processing. "
            f"Attempt {current_attempt + 1}/{max_retries}."
        )
        raise self.retry(countdown=poll_interval)

    # Failed on AI side
    if ai_status != "completed":
        logger.error(f"[poll_ai] Task {ai_task_id} returned unexpected status: {ai_status}")
        Candidate.objects.filter(id=candidate_id).update(
            ai_processing_status=AIProcessingStatus.FAILED,
            ai_failure_reason=f"AI returned status: {ai_status}",
        )
        _update_batch_failed(candidate_id)
        return

    # -------------------------------------------------------------------------
    # Completed — extract and save data
    # -------------------------------------------------------------------------
    result = data.get("result", {})
    personal_info = result.get("personal_info", {})
    data_extracted = result.get("data_extracted", {})
    quality_check = result.get("quality_check", "").lower()

    try:
        candidate = Candidate.objects.get(id=candidate_id)
    except Candidate.DoesNotExist:
        logger.error(f"[poll_ai] Candidate {candidate_id} not found during save.")
        return

    quality_status = QUALITY_MAP.get(quality_check, "manual")

    raw_experience = personal_info.get("experience", "")
    years_of_experience = _parse_experience(raw_experience)


    # Update candidate from AI data
    candidate.name = personal_info.get("full_name") or candidate.name
    candidate.email = personal_info.get("email") or candidate.email
    candidate.whatsapp_number = personal_info.get("whatsapp") or candidate.whatsapp_number
    candidate.location = personal_info.get("location") or candidate.location
    candidate.skills = personal_info.get("skill") or []
    candidate.years_of_experience = years_of_experience
    candidate.quality_status = quality_status
    candidate.email_subject = data_extracted.get("email_subject", "")
    candidate.email_body = data_extracted.get("email_body", "")
    candidate.ai_enhanced_cv_content = result
    candidate.ai_processing_status = AIProcessingStatus.IN_PROGRESS  # still needs PDF

    candidate.save(update_fields=[
        "name",
        "email",
        "whatsapp_number",
        "location",
        "skills",
        "years_of_experience",
        "quality_status",
        "email_subject",
        "email_body",
        "ai_enhanced_cv_content",
        "ai_processing_status",
        "updated_at",
    ])

    logger.info(f"[poll_ai] Candidate {candidate_id} data saved. Triggering PDF generation.")

    # Trigger PDF generation task
    from candidate.tasks.generate_pdf import generate_enhanced_cv_pdf_task
    generate_enhanced_cv_pdf_task.apply_async(
        args=[candidate_id],
        queue="pdf",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_experience(raw: str):
    """
    Parse experience string from AI response.
    '30 years' → 30.0
    '1.5 years' → 1.5
    '6 months' → 0.5
    """
    import re
    if not raw:
        return None
    raw = raw.lower().strip()

    # Match decimal or integer years
    match = re.search(r"(\d+\.?\d*)\s*year", raw)
    if match:
        return float(match.group(1))

    # Match months
    match = re.search(r"(\d+)\s*month", raw)
    if match:
        return round(int(match.group(1)) / 12, 1)

    # Try plain number
    try:
        return float(raw)
    except ValueError:
        return None


def _update_batch_failed(candidate_id: str):
    """Increment the failed count on the related batch."""
    from candidate.models import Candidate
    try:
        candidate = Candidate.objects.select_related("batch").get(id=candidate_id)
        if candidate.batch:
            candidate.batch.failed_count = models.F("failed_count") + 1
            candidate.batch.save(update_fields=["failed_count"])
    except Exception:
        pass