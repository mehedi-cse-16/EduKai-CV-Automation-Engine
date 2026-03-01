import boto3
from botocore.client import Config
from django.conf import settings


def get_presigned_url(file_field, expires_in: int = 3600) -> str:
    """
    Generate a pre-signed URL for a MinIO/S3 file field.

    Args:
        file_field : A Django FileField instance (e.g. candidate.original_cv_file)
        expires_in : URL validity in seconds (default: 1 hour)

    Returns:
        A pre-signed URL string that allows temporary public access.
    """
    s3_client = boto3.client(
        "s3",
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},   # MinIO MUST use path-style
        ),
        region_name=settings.AWS_S3_REGION_NAME,
    )

    presigned_url = s3_client.generate_presigned_url(
        ClientMethod="get_object",
        Params={
            "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
            "Key":    file_field.name,   # e.g. candidates/original/<uuid>/<file>.pdf
        },
        ExpiresIn=expires_in,
    )

    return presigned_url