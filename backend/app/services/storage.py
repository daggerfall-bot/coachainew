"""
CoachAI — Object storage (S3-compatible: AWS S3, Cloudflare R2, MinIO).

Async wrappers over aioboto3 for uploading clips/VODs/reports and minting
presigned URLs the frontend uses to stream clips directly from storage
(keeps large video bytes off your API servers).
"""
from __future__ import annotations

from app.core.config import settings


def _session():
    # aioboto3 imported lazily: the bundled desktop server runs in local mode
    # and never touches S3, so it isn't installed there.
    import aioboto3
    return aioboto3.Session()


def _client():
    return _session().client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )


async def upload_file(local_path: str, key: str) -> str:
    if settings.local_mode:
        import shutil
        from pathlib import Path
        dest = Path(settings.local_data_dir) / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, dest)
        return key
    async with _client() as s3:
        await s3.upload_file(local_path, settings.s3_bucket, key)
    return key


async def download_file(key: str, local_path: str) -> str:
    if settings.local_mode:
        import shutil
        from pathlib import Path
        src = Path(settings.local_data_dir) / key
        shutil.copyfile(src, local_path)
        return local_path
    async with _client() as s3:
        await s3.download_file(settings.s3_bucket, key, local_path)
    return local_path


async def presign_get(key: str, expires: int = 3600) -> str:
    if settings.local_mode:
        return f"http://127.0.0.1:{settings.local_port()}/api/v1/local-storage/{key}"
    async with _client() as s3:
        return await s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket, "Key": key},
            ExpiresIn=expires,
        )


async def presign_put(key: str, expires: int = 3600) -> str:
    """Frontend uploads VODs straight to storage with this URL."""
    if settings.local_mode:
        return f"http://127.0.0.1:{settings.local_port()}/api/v1/local-storage/{key}"
    async with _client() as s3:
        return await s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": settings.s3_bucket, "Key": key},
            ExpiresIn=expires,
        )
