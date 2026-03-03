import uuid
import boto3
from botocore.client import Config
from django.conf import settings


# ---------------------------------------------------------------------------
# Internal client — used for signing (uses fast internal URL)
# ---------------------------------------------------------------------------
def _get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,      # http://127.0.0.1:9000
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
        region_name=settings.AWS_S3_REGION_NAME,
    )


# ---------------------------------------------------------------------------
# ✅ replace internal host with public host in pre-signed URL
# ---------------------------------------------------------------------------
def _to_public_url(presigned_url: str) -> str:
    """
    Pre-signed URLs are generated using the internal endpoint (127.0.0.1:9000).
    This replaces the internal host with the public-facing MinIO URL
    so browsers and external services can actually access the file.

    Example:
        IN:  http://127.0.0.1:9000/edukai/candidates/original/...?X-Amz-...
        OUT: http://test3.fireai.agency:9000/edukai/candidates/original/...?X-Amz-...
    """
    public_url = getattr(settings, "MINIO_PUBLIC_URL", "").rstrip("/")
    internal_url = getattr(settings, "AWS_S3_ENDPOINT_URL", "").rstrip("/")

    if not public_url or not internal_url:
        return presigned_url

    # Only replace if the URL starts with the internal endpoint
    if presigned_url.startswith(internal_url):
        return presigned_url.replace(internal_url, public_url, 1)

    return presigned_url


# ---------------------------------------------------------------------------
# GET — Pre-signed download URL
# ---------------------------------------------------------------------------
def get_presigned_url(file_field, expires_in: int | None = None) -> str | None:
    """
    Generate a pre-signed GET URL for any FileField / ImageField.
    Returns a PUBLIC URL (browser-accessible), not the internal one.
    """
    if expires_in is None:
        expires_in = getattr(settings, "PRESIGNED_URL_EXPIRE_SECONDS", 3600)

    if not file_field or not file_field.name:
        return None

    presigned = _get_s3_client().generate_presigned_url(
        ClientMethod="get_object",
        Params={
            "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
            "Key":    file_field.name,
        },
        ExpiresIn=expires_in,
    )

    # ✅ Swap internal URL → public URL
    return _to_public_url(presigned)


# ---------------------------------------------------------------------------
# PUT — Pre-signed upload URL
# ---------------------------------------------------------------------------
def get_presigned_upload_url(
    object_key: str,
    content_type: str = "application/pdf",
    expires_in: int = 900,
) -> dict:
    """
    Generate a pre-signed PUT URL for direct browser → MinIO uploads.
    Returns a PUBLIC URL so the browser can PUT directly to MinIO.
    """
    presigned = _get_s3_client().generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket":      settings.AWS_STORAGE_BUCKET_NAME,
            "Key":         object_key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
    )

    return {
        "upload_url": _to_public_url(presigned),
        "object_key": object_key,
        "expires_in": expires_in,
    }


# ---------------------------------------------------------------------------
# Smart resolver — used in serializers
# ---------------------------------------------------------------------------
def resolve_file_url(file_field, expires_in: int | None = None) -> str | None:
    """
    Works for ANY FileField or ImageField — CVs, profile pics, anything.
    - USE_S3=True  → pre-signed public MinIO URL
    - USE_S3=False → plain local Django URL
    """
    if expires_in is None:
        expires_in = getattr(settings, "PRESIGNED_URL_EXPIRE_SECONDS", 3600)

    if not file_field or not file_field.name:
        return None

    if getattr(settings, "USE_S3", False):
        return get_presigned_url(file_field, expires_in=expires_in)
    else:
        try:
            return file_field.url
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Object key builders
# ---------------------------------------------------------------------------
def build_cv_object_key(candidate_id: str, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    return f"candidates/original/{candidate_id}/{uuid.uuid4().hex}.{ext}"


def build_enhanced_cv_object_key(candidate_id: str, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    return f"candidates/enhanced/{candidate_id}/{uuid.uuid4().hex}.{ext}"