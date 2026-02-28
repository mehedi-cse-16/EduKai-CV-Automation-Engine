import logging
import os
import platform

from celery import shared_task
from django.conf import settings
from django.core.files.base import ContentFile
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=15,
    name="candidate.tasks.generate_pdf",
)
def generate_enhanced_cv_pdf_task(self, candidate_id: str):
    from candidate.models import Candidate, AIProcessingStatus

    try:
        candidate = Candidate.objects.get(id=candidate_id)
    except Candidate.DoesNotExist:
        logger.error(f"[generate_pdf] Candidate {candidate_id} not found.")
        return

    result = candidate.ai_enhanced_cv_content
    if not result:
        candidate.ai_processing_status = AIProcessingStatus.FAILED
        candidate.ai_failure_reason = "No AI content found to generate PDF."
        candidate.save(update_fields=["ai_processing_status", "ai_failure_reason", "updated_at"])
        return

    data_extracted = result.get("data_extracted", {})

    # -------------------------------------------------------------------------
    # Build template context
    # ✅ availability intentionally excluded — managed manually by system owner
    # -------------------------------------------------------------------------
    cv_context = {
        "name":                 data_extracted.get("name", ""),
        "role":                 data_extracted.get("role", ""),
        "location":             data_extracted.get("location", ""),
        "professional_profile": data_extracted.get("professional_profile", ""),
        "employment_history":   data_extracted.get("employment_history", []),
        "qualifications":       data_extracted.get("qualifications", []),
        "interests":            data_extracted.get("interests", ""),
    }

    logo_path = getattr(settings, "CV_LOGO_PATH", "")
    if logo_path and os.path.exists(logo_path):
        logo_url = "file:///" + logo_path.replace("\\", "/")
    else:
        logo_url = ""

    context = {
        "cv":        cv_context,
        "logo_path": logo_url,
    }

    # -------------------------------------------------------------------------
    # Render HTML template
    # -------------------------------------------------------------------------
    try:
        html_string = render_to_string("candidate/enhanced_cv.html", context)
    except Exception as exc:
        logger.error(f"[generate_pdf] Template rendering failed for {candidate_id}: {exc}")
        candidate.ai_processing_status = AIProcessingStatus.FAILED
        candidate.ai_failure_reason = f"Template rendering failed: {exc}"
        candidate.save(update_fields=["ai_processing_status", "ai_failure_reason", "updated_at"])
        raise self.retry(exc=exc)

    # -------------------------------------------------------------------------
    # Generate PDF
    # -------------------------------------------------------------------------
    try:
        pdf_bytes = _render_pdf(html_string)
    except Exception as exc:
        logger.error(f"[generate_pdf] PDF generation failed for {candidate_id}: {exc}")
        candidate.ai_processing_status = AIProcessingStatus.FAILED
        candidate.ai_failure_reason = f"PDF generation failed: {exc}"
        candidate.save(update_fields=["ai_processing_status", "ai_failure_reason", "updated_at"])
        raise self.retry(exc=exc)

    # -------------------------------------------------------------------------
    # Upload PDF to MinIO
    # -------------------------------------------------------------------------
    safe_name = (
        candidate.name.replace(" ", "_").lower()
        if candidate.name
        else str(candidate_id)
    )
    file_name = f"{safe_name}_enhanced_cv.pdf"

    try:
        candidate.ai_enhanced_cv_file.save(
            file_name,
            ContentFile(pdf_bytes),
            save=False,
        )
    except Exception as exc:
        logger.error(f"[generate_pdf] MinIO upload failed for {candidate_id}: {exc}")
        candidate.ai_processing_status = AIProcessingStatus.FAILED
        candidate.ai_failure_reason = f"MinIO upload failed: {exc}"
        candidate.save(update_fields=["ai_processing_status", "ai_failure_reason", "updated_at"])
        raise self.retry(exc=exc)

    # -------------------------------------------------------------------------
    # Final DB save — mark completed
    # -------------------------------------------------------------------------
    candidate.ai_processing_status = AIProcessingStatus.COMPLETED
    candidate.save(update_fields=[
        "ai_enhanced_cv_file",
        "ai_processing_status",
        "updated_at",
    ])

    if candidate.batch:
        from django.db.models import F
        candidate.batch.processed_count = F("processed_count") + 1
        candidate.batch.save(update_fields=["processed_count", "updated_at"])

    logger.info(f"[generate_pdf] ✅ PDF generated and saved for candidate {candidate_id}.")


# ---------------------------------------------------------------------------
# PDF rendering — Windows uses xhtml2pdf, Linux/Mac uses WeasyPrint
# ---------------------------------------------------------------------------
def _render_pdf(html_string: str) -> bytes:
        from weasyprint import HTML
        return HTML(string=html_string).write_pdf()