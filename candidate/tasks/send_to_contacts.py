import logging
import mimetypes
import os
import base64
from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="candidate.tasks.send_to_contacts",
)
def send_to_contacts_task(self, candidate_id: str, contact_ids: list):
    """
    Sends candidate's email_subject + email_body to a list of
    organization contacts via SendGrid.
    Returns a summary dict.
    """
    from django.utils import timezone
    from candidate.models import Candidate
    from organization.models import OrganizationContact

    summary = {
        "total":   len(contact_ids),
        "sent":    0,
        "failed":  0,
        "errors":  [],
    }

    if not settings.SENDGRID_API_KEY:
        logger.error("[send_contacts] SENDGRID_API_KEY not set.")
        summary["errors"].append("SendGrid API key not configured.")
        return summary

    try:
        candidate = Candidate.objects.get(id=candidate_id)
    except Candidate.DoesNotExist:
        logger.error(f"[send_contacts] Candidate {candidate_id} not found.")
        summary["errors"].append("Candidate not found.")
        return summary

    if not candidate.email_subject or not candidate.email_body:
        summary["errors"].append(
            "Candidate has no email subject or body. Process the CV through AI first."
        )
        return summary

    contacts = OrganizationContact.objects.select_related("organization").filter(id__in=contact_ids)
    if not contacts.exists():
        summary["errors"].append("No valid contacts found.")
        return summary

    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import (
        Mail, From, To, Subject, HtmlContent, PlainTextContent, ReplyTo, Attachment
    )

    sg = SendGridAPIClient(settings.SENDGRID_API_KEY)

    # Build reusable attachment payloads once
    profile_attachment = _build_attachment_from_field(candidate.profile_photo, fallback_name="candidate_photo")
    cv_attachment = _build_attachment_from_field(candidate.ai_enhanced_cv_file, fallback_name="enhanced_cv")

    # Send individually to each contact
    for contact in contacts:
        try:
            # Personalized bodies
            plain_body = _build_personalized_plain_body(candidate.email_body, contact.contact_person)
            html_body = _build_html_body(plain_body)

            message = Mail(
                from_email=From(
                    settings.SENDGRID_FROM_EMAIL,
                    settings.SENDGRID_FROM_NAME,
                ),
                to_emails=To(contact.work_email),
                subject=Subject(candidate.email_subject),
                plain_text_content=PlainTextContent(plain_body),
                html_content=HtmlContent(html_body),
            )

            if settings.SENDGRID_REPLY_TO_EMAIL:
                message.reply_to = ReplyTo(
                    email=settings.SENDGRID_REPLY_TO_EMAIL,
                    name=settings.SENDGRID_REPLY_TO_NAME or None,
                )

            # Attach profile photo if available
            if profile_attachment:
                message.add_attachment(profile_attachment)

            # Attach enhanced CV if available
            if cv_attachment:
                message.add_attachment(cv_attachment)

            response = sg.send(message)

            if response.status_code in (200, 202):
                summary["sent"] += 1
                logger.info(
                    f"[send_contacts] ✅ Sent to {contact.work_email} ({contact.organization.name})"
                )
            else:
                raise Exception(f"Unexpected SendGrid status: {response.status_code}")

        except Exception as exc:
            summary["failed"] += 1
            summary["errors"].append(f"{contact.work_email}: {str(exc)}")
            logger.error(f"[send_contacts] ❌ Failed to send to {contact.work_email}: {exc}")

    if summary["sent"] > 0:
        from django.db.models import F
        candidate.last_contacted_at = timezone.now()
        candidate.contacts_emailed_count = F("contacts_emailed_count") + summary["sent"]
        candidate.save(update_fields=["last_contacted_at", "contacts_emailed_count", "updated_at"])

        from account.utils.activity import log_activity
        log_activity(
            event_type="emails_sent",
            severity="success",
            title=f"Emails sent for {candidate.name}",
            message=f"Sent to {summary['sent']} contacts. Failed: {summary['failed']}.",
            candidate_id=candidate.id,
        )

    logger.info(
        f"[send_contacts] ✅ Done for candidate '{candidate.name}' — "
        f"sent={summary['sent']}, failed={summary['failed']}"
    )
    return summary


def _build_personalized_plain_body(original_body: str, contact_person: str | None) -> str:
    """
    Prefix a greeting to make each email individual.
    """
    person = (contact_person or "").strip()
    greeting = f"Dear {person}," if person else "Dear Sir/Madam,"
    return f"{greeting}\n\n{original_body}"


def _build_attachment_from_field(file_field, fallback_name: str = "attachment"):
    """
    Build SendGrid attachment from Django FileField (S3/local compatible).
    Returns Attachment or None.
    """
    from sendgrid.helpers.mail import Attachment, FileContent, FileName, FileType, Disposition

    if not file_field:
        return None

    try:
        # Read bytes from storage backend
        with file_field.open("rb") as f:
            raw = f.read()

        filename = os.path.basename(file_field.name) or fallback_name
        mime_type, _ = mimetypes.guess_type(filename)
        mime_type = mime_type or "application/octet-stream"

        encoded = base64.b64encode(raw).decode("utf-8")

        return Attachment(
            file_content=FileContent(encoded),
            file_name=FileName(filename),
            file_type=FileType(mime_type),
            disposition=Disposition("attachment"),
        )
    except Exception as exc:
        logger.warning(f"[send_contacts] Could not attach '{file_field}': {exc}")
        return None


def _build_html_body(plain_text: str) -> str:
    import re

    text = (
        plain_text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    text = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", text)
    text = text.replace("\n", "<br>")

    reply_to = getattr(settings, "SENDGRID_REPLY_TO_EMAIL", "")

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family: Arial, sans-serif; font-size: 14px;
             color: #222; max-width: 600px;
             margin: 0 auto; padding: 20px;">
  <div>{text}</div>
  <br>
  <p style="color: #555; font-size: 12px;">
    Education Specialists Agency<br>
    <a href="mailto:{reply_to}">{reply_to}</a>
  </p>
</body>
</html>"""