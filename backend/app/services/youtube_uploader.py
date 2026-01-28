"""YouTube upload service using YouTube Data API v3."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.config import settings
from app.exceptions import YouTubeUploadError

logger = logging.getLogger(__name__)

# OAuth2 scopes required for YouTube upload
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


@dataclass
class UploadResult:
    """Result of YouTube upload."""
    video_id: str
    youtube_url: str
    title: str


class YouTubeUploader:
    """Service for uploading videos to YouTube."""

    def __init__(self):
        self.credentials_path = Path(settings.YOUTUBE_CREDENTIALS_PATH).expanduser()
        self._credentials: Optional[Credentials] = None
        self._youtube = None

    def _get_credentials(self) -> Credentials:
        """Get or refresh OAuth2 credentials."""
        if self._credentials and self._credentials.valid:
            return self._credentials

        token_path = self.credentials_path.parent / "token.json"

        # Load existing token
        if token_path.exists():
            self._credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        # Refresh or get new credentials
        if not self._credentials or not self._credentials.valid:
            if self._credentials and self._credentials.expired and self._credentials.refresh_token:
                logger.info("Refreshing YouTube credentials")
                self._credentials.refresh(Request())
            else:
                logger.info("Starting OAuth flow for YouTube credentials")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path.parent / "client_secret.json"),
                    SCOPES,
                )
                self._credentials = flow.run_local_server(port=8080)

            # Save token for future use
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(self._credentials.to_json())

        return self._credentials

    @property
    def youtube(self):
        """Get authenticated YouTube API client."""
        if self._youtube is None:
            credentials = self._get_credentials()
            self._youtube = build("youtube", "v3", credentials=credentials)
        return self._youtube

    async def upload(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: List[str],
        category_id: str = "17",  # Sports
        privacy_status: str = "public",
    ) -> UploadResult:
        """
        Upload a video to YouTube.

        Args:
            video_path: Local path to the video file
            title: Video title
            description: Video description
            tags: List of tags
            category_id: YouTube category ID (17 = Sports)
            privacy_status: 'public', 'private', or 'unlisted'

        Returns:
            UploadResult with video ID and URL
        """
        logger.info(f"Starting YouTube upload: {title}")
        logger.debug(f"Video path: {video_path}")

        if not Path(video_path).exists():
            raise YouTubeUploadError(f"Video file not found: {video_path}")

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }

        logger.debug(f"Upload body: {body}")

        media = MediaFileUpload(
            video_path,
            mimetype="video/mp4",
            resumable=True,
            chunksize=1024 * 1024,  # 1MB chunks
        )

        try:
            request = self.youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    logger.info(f"Upload progress: {progress}%")

            video_id = response["id"]
            youtube_url = f"https://www.youtube.com/watch?v={video_id}"

            logger.info(f"Upload complete. Video ID: {video_id}")
            logger.info(f"YouTube URL: {youtube_url}")

            return UploadResult(
                video_id=video_id,
                youtube_url=youtube_url,
                title=title,
            )

        except Exception as e:
            logger.error(f"YouTube upload failed: {e}")
            raise YouTubeUploadError(f"Upload failed: {e}")

    async def get_video_status(self, video_id: str) -> dict:
        """Get the processing status of an uploaded video."""
        try:
            response = self.youtube.videos().list(
                part="status,processingDetails",
                id=video_id,
            ).execute()

            if response["items"]:
                return response["items"][0]
            return {}
        except Exception as e:
            logger.error(f"Failed to get video status: {e}")
            return {}
