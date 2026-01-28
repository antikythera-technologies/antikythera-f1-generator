"""MinIO storage service."""

import logging
from io import BytesIO
from pathlib import Path
from typing import Optional

from minio import Minio
from minio.error import S3Error

from app.config import settings
from app.exceptions import StorageError

logger = logging.getLogger(__name__)


class StorageService:
    """Service for managing object storage with MinIO."""

    def __init__(self):
        self.endpoint = settings.MINIO_ENDPOINT
        self.access_key = settings.MINIO_ACCESS_KEY
        self.secret_key = settings.MINIO_SECRET_KEY
        self.secure = settings.MINIO_SECURE

        self._client: Optional[Minio] = None

    @property
    def client(self) -> Minio:
        """Lazy initialization of MinIO client."""
        if self._client is None:
            self._client = Minio(
                self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure,
            )
        return self._client

    async def ensure_buckets(self) -> None:
        """Ensure all required buckets exist."""
        buckets = [
            settings.MINIO_BUCKET_CHARACTERS,
            settings.MINIO_BUCKET_SCENE_IMAGES,
            settings.MINIO_BUCKET_VIDEO_CLIPS,
            settings.MINIO_BUCKET_FINAL_VIDEOS,
        ]

        for bucket in buckets:
            try:
                if not self.client.bucket_exists(bucket):
                    self.client.make_bucket(bucket)
                    logger.info(f"Created bucket: {bucket}")
            except S3Error as e:
                logger.error(f"Failed to create bucket {bucket}: {e}")
                raise StorageError(f"Failed to create bucket {bucket}: {e}")

    async def upload_file(
        self,
        bucket: str,
        object_name: str,
        file_path: str,
    ) -> str:
        """
        Upload a file to MinIO.

        Returns:
            Full path in format: bucket/object_name
        """
        logger.info(f"Uploading to MinIO: {bucket}/{object_name}")

        try:
            self.client.fput_object(bucket, object_name, file_path)
            full_path = f"{bucket}/{object_name}"
            logger.debug(f"Upload complete: {full_path}")
            return full_path
        except S3Error as e:
            logger.error(f"Upload failed: {e}")
            raise StorageError(f"Upload failed: {e}")

    async def upload_bytes(
        self,
        bucket: str,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload bytes data to MinIO."""
        logger.info(f"Uploading bytes to MinIO: {bucket}/{object_name}")

        try:
            self.client.put_object(
                bucket,
                object_name,
                BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            full_path = f"{bucket}/{object_name}"
            return full_path
        except S3Error as e:
            logger.error(f"Upload failed: {e}")
            raise StorageError(f"Upload failed: {e}")

    async def download_file(
        self,
        bucket: str,
        object_name: str,
        file_path: str,
    ) -> None:
        """Download a file from MinIO."""
        logger.info(f"Downloading from MinIO: {bucket}/{object_name}")

        try:
            self.client.fget_object(bucket, object_name, file_path)
            logger.debug(f"Downloaded to: {file_path}")
        except S3Error as e:
            logger.error(f"Download failed: {e}")
            raise StorageError(f"Download failed: {e}")

    async def delete_file(self, bucket: str, object_name: str) -> None:
        """Delete a file from MinIO."""
        try:
            self.client.remove_object(bucket, object_name)
            logger.debug(f"Deleted: {bucket}/{object_name}")
        except S3Error as e:
            logger.error(f"Delete failed: {e}")
            raise StorageError(f"Delete failed: {e}")

    async def list_objects(
        self,
        bucket: str,
        prefix: str = "",
        recursive: bool = True,
    ) -> list:
        """List objects in a bucket with optional prefix."""
        try:
            objects = self.client.list_objects(
                bucket,
                prefix=prefix,
                recursive=recursive,
            )
            return list(objects)
        except S3Error as e:
            logger.error(f"List failed: {e}")
            raise StorageError(f"List failed: {e}")

    async def upload_character_image(
        self,
        object_name: str,
        data: bytes,
    ) -> str:
        """Upload a character reference image."""
        content_type = "image/png"
        if object_name.lower().endswith(".jpg") or object_name.lower().endswith(".jpeg"):
            content_type = "image/jpeg"

        return await self.upload_bytes(
            settings.MINIO_BUCKET_CHARACTERS,
            object_name,
            data,
            content_type,
        )

    async def download_character_image(self, storage_path: str) -> str:
        """
        Download a character reference image to local temp.
        
        Args:
            storage_path: Full path like "f1-characters/max_verstappen.png" or just object name
            
        Returns:
            Local file path to downloaded image
        """
        import tempfile
        from pathlib import Path
        
        # Parse bucket and object name from path
        if "/" in storage_path:
            parts = storage_path.split("/", 1)
            if parts[0] == settings.MINIO_BUCKET_CHARACTERS:
                object_name = parts[1]
            else:
                object_name = storage_path
        else:
            object_name = storage_path
        
        # Create temp file with correct extension
        ext = Path(object_name).suffix or ".png"
        temp_dir = Path(tempfile.gettempdir()) / "f1-characters"
        temp_dir.mkdir(parents=True, exist_ok=True)
        local_path = str(temp_dir / f"{Path(object_name).stem}{ext}")
        
        await self.download_file(
            settings.MINIO_BUCKET_CHARACTERS,
            object_name,
            local_path,
        )
        
        return local_path

    async def upload_scene_image(
        self,
        race_id: int,
        episode_id: int,
        scene_number: int,
        file_path: str,
    ) -> str:
        """Upload a scene source image."""
        object_name = f"race_{race_id:03d}/episode_{episode_id}/scene_{scene_number:02d}.png"
        return await self.upload_file(
            settings.MINIO_BUCKET_SCENE_IMAGES,
            object_name,
            file_path,
        )

    async def upload_video_clip(
        self,
        race_id: int,
        episode_id: int,
        scene_number: int,
        file_path: str,
    ) -> str:
        """Upload a generated video clip."""
        object_name = f"race_{race_id:03d}/episode_{episode_id}/scene_{scene_number:02d}.mp4"
        return await self.upload_file(
            settings.MINIO_BUCKET_VIDEO_CLIPS,
            object_name,
            file_path,
        )

    async def upload_final_video(
        self,
        race_id: int,
        episode_id: int,
        file_path: str,
    ) -> str:
        """Upload the final stitched video."""
        object_name = f"race_{race_id:03d}/episode_{episode_id}/final.mp4"
        return await self.upload_file(
            settings.MINIO_BUCKET_FINAL_VIDEOS,
            object_name,
            file_path,
        )

    async def cleanup_old_race(self, race_number: int) -> tuple[int, int]:
        """
        Clean up scene images and video clips for an old race.

        Returns:
            Tuple of (files_deleted, bytes_freed)
        """
        logger.info(f"Cleaning up assets for race {race_number}")

        prefix = f"race_{race_number:03d}/"
        total_deleted = 0
        total_bytes = 0

        for bucket in [settings.MINIO_BUCKET_SCENE_IMAGES, settings.MINIO_BUCKET_VIDEO_CLIPS]:
            objects = await self.list_objects(bucket, prefix=prefix)

            for obj in objects:
                await self.delete_file(bucket, obj.object_name)
                total_deleted += 1
                total_bytes += obj.size or 0

        logger.info(f"Cleanup complete: {total_deleted} files, {total_bytes / 1024 / 1024:.2f} MB freed")

        return total_deleted, total_bytes
