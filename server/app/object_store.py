"""Private blob storage. Local disk and S3 share one bounded, immutable interface."""

import asyncio
import base64
import hashlib
import os
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.settings import Settings


class ObjectStoreError(Exception):
    pass


class BlobStore(Protocol):
    async def get_bytes(self, key: str) -> bytes: ...
    def read(self, key: str) -> bytes: ...
    def put(self, key: str, payload: bytes) -> None: ...
    def delete(self, key: str) -> None: ...


def validate_key(key: str) -> str:
    from uuid import UUID

    try:
        if str(UUID(key)) != key:
            raise ValueError
    except ValueError as exc:
        raise ObjectStoreError("Invalid storage key") from exc
    return key


class LocalObjectStore:
    def __init__(self, root: Path, max_bytes: int = 32 * 1024 * 1024):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.max_bytes = max_bytes

    def path(self, key: str) -> Path:
        validate_key(key)
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ObjectStoreError("Invalid storage key")
        return path

    def read(self, key: str) -> bytes:
        with self.path(key).open("rb") as source:
            payload = source.read(self.max_bytes + 1)
        if len(payload) > self.max_bytes:
            raise ObjectStoreError("Stored content exceeds the configured limit")
        return payload

    async def get_bytes(self, key: str) -> bytes:
        try:
            return await asyncio.to_thread(self.read, key)
        except OSError as exc:
            raise ObjectStoreError("Stored content unavailable") from exc

    def put(self, key: str, payload: bytes) -> None:
        if len(payload) > self.max_bytes:
            raise ObjectStoreError("Content exceeds the configured limit")
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4()}.tmp")
        try:
            with temporary.open("xb") as target:
                os.chmod(temporary, 0o600)
                target.write(payload)
                target.flush()
                os.fsync(target.fileno())
            try:
                # link is atomic and cannot overwrite an already published blob.
                os.link(temporary, path)
            except FileExistsError:
                if self.read(key) != payload:
                    raise ObjectStoreError("An immutable object already exists") from None
            directory = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)


class S3ObjectStore:
    def __init__(self, settings: Settings):
        import boto3
        from botocore.config import Config

        if not settings.s3_bucket:
            raise ValueError("CORNAGENT_S3_BUCKET is required for S3 storage")
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix.strip("/")
        self.max_bytes = max(settings.agent_file_image_max_bytes, settings.agent_file_pdf_max_bytes)
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id.get_secret_value()
            if settings.s3_access_key_id
            else None,
            aws_secret_access_key=settings.s3_secret_access_key.get_secret_value()
            if settings.s3_secret_access_key
            else None,
            aws_session_token=settings.s3_session_token.get_secret_value()
            if settings.s3_session_token
            else None,
            config=Config(
                signature_version="s3v4",
                connect_timeout=5,
                read_timeout=30,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    def _key(self, key: str) -> str:
        return "/".join(filter(None, (self.prefix, validate_key(key))))

    def read(self, key: str) -> bytes:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            result = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
            with result["Body"] as body:
                if result["ContentLength"] > self.max_bytes:
                    raise ObjectStoreError("Stored content exceeds the configured limit")
                payload = body.read(self.max_bytes + 1)
            if len(payload) > self.max_bytes:
                raise ObjectStoreError("Stored content exceeds the configured limit")
            return payload
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStoreError("Stored content unavailable") from exc

    async def get_bytes(self, key: str) -> bytes:
        return await asyncio.to_thread(self.read, key)

    def put(self, key: str, payload: bytes) -> None:
        from botocore.exceptions import BotoCoreError, ClientError

        if len(payload) > self.max_bytes:
            raise ObjectStoreError("Content exceeds the configured limit")
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=self._key(key),
                Body=payload,
                ContentType="application/octet-stream",
                IfNoneMatch="*",
                ChecksumSHA256=base64.b64encode(hashlib.sha256(payload).digest()).decode("ascii"),
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"PreconditionFailed", "412"}:
                if self.read(key) == payload:
                    return
                raise ObjectStoreError("An immutable object already exists") from exc
            raise ObjectStoreError("Object upload failed") from exc
        except BotoCoreError as exc:
            raise ObjectStoreError("Object upload failed") from exc

    def delete(self, key: str) -> None:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            self.client.delete_object(Bucket=self.bucket, Key=self._key(key))
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStoreError("Object deletion failed") from exc


def build_blob_store(settings: Settings) -> BlobStore:
    if settings.file_store_backend == "s3":
        return S3ObjectStore(settings)
    return LocalObjectStore(
        settings.file_store_path,
        max_bytes=max(settings.agent_file_image_max_bytes, settings.agent_file_pdf_max_bytes),
    )
