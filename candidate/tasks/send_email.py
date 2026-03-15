import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)

AVAILABILITY_EMAIL_SUBJECT = "Are you looking for a new challenge?"

AVAILABILITY_EMAIL_PLAIN = """
Are you looking for a new challenge?

Schools need passionate, reliable, and inspiring Educators & Support Staff now more than ever.
If you're ready for your next opportunity, we're ready for you!

WE ARE THE EDUCATION SPECIALISTS AGENCY

Whether you're looking for flexibility, progression, or your next temp role,
let's get you placed where you can truly shine.

Interested? Drop me a quick email with:
- Your availability (what date can you start?)
- Full-time or part-time preference?
- Your location?
- Job title(s) you're looking for?

Up to £250 refer-a-friend bonus! (T&Cs apply)

Tag or share with friends, family & colleagues.
Your next role could be one message away.
"""

AVAILABILITY_EMAIL_BODY = """
<p>✨ <strong>Are you looking for a new challenge?</strong> ✨</p>

<p>Schools need passionate, reliable, and inspiring Educators &amp; Support Staff now more than ever.
If you're ready for your next opportunity, we're ready for you!</p>

<p>🔊 <strong>WE ARE THE EDUCATION SPECIALISTS AGENCY</strong> 📚👨🏿‍🏫👩🏼‍🏫🏫</p>

<p>Whether you're looking for flexibility, progression, or your next temp role —
let's get you placed where you can truly shine 🌟</p>

<p>📩 <strong>Interested? Drop me a quick email with:</strong><br>
📅 Your availability (what date can you start?)<br>
🕒 Full-time or part-time preference?<br>
📍 Your location?<br>
🎯 Job title(s) you're looking for?</p>

<p>💷 <strong>Up to £250 refer-a-friend bonus!</strong> 💷 (T&amp;Cs apply)</p>

<p>Tag or share with friends, family &amp; colleagues 📱📞📧🤝</p>

<p>Your next role could be one message away. 🚀</p>
"""


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="candidate.tasks.send_availability_email",
)
def send_availability_email_task(self, candidate_id: str):
    """
    Task — Sends availability email to candidate via SendGrid.
    Only called when AI extraction found a valid email address.
    Availability status is NOT touched — managed manually by the user.
    """
    from candidate.models import Candidate

    # ── Guard: skip if SendGrid not configured ────────────────────────────
    if not settings.SENDGRID_API_KEY:
        logger.warning(
            f"[send_email] SENDGRID_API_KEY not set. "
            f"Skipping email for candidate {candidate_id}."
        )
        return

    try:
        candidate = Candidate.objects.get(id=candidate_id)
    except Candidate.DoesNotExist:
        logger.error(f"[send_email] Candidate {candidate_id} not found.")
        return

    # ── Guard: skip if no email found by AI ──────────────────────────────
    if not candidate.email:
        logger.info(
            f"[send_email] Candidate {candidate_id} has no email. Skipping."
        )
        return

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import (
            Mail, From, To, Subject,
            HtmlContent, PlainTextContent,
        )

        message = Mail(
            from_email=From(settings.SENDGRID_FROM_EMAIL, settings.SENDGRID_FROM_NAME),
            to_emails=To(candidate.email),
            subject=Subject(AVAILABILITY_EMAIL_SUBJECT),
            plain_text_content=PlainTextContent(AVAILABILITY_EMAIL_PLAIN),
            html_content=HtmlContent(AVAILABILITY_EMAIL_BODY),
        )

        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)

        if response.status_code in (200, 202):
            logger.info(
                f"[send_email] ✅ Email sent to {candidate.email} "
                f"for candidate {candidate_id}. "
                f"SendGrid status: {response.status_code}"
            )
        else:
            logger.warning(
                f"[send_email] Unexpected SendGrid status {response.status_code} "
                f"for candidate {candidate_id}."
            )
            raise self.retry(
                exc=Exception(f"SendGrid status: {response.status_code}")
            )

    except Exception as exc:
        logger.error(
            f"[send_email] Failed to send email for candidate {candidate_id}: {exc}"
        )
        raise self.retry(exc=exc)