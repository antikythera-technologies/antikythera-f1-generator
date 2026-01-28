"""Custom exceptions for the application."""


class AntiktheraException(Exception):
    """Base exception for the application."""
    pass


class ScriptGenerationError(AntiktheraException):
    """Error during script generation."""
    pass


class VideoGenerationError(AntiktheraException):
    """Error during video clip generation."""
    pass


class VideoStitchError(AntiktheraException):
    """Error during video stitching."""
    pass


class StorageError(AntiktheraException):
    """Error with MinIO storage operations."""
    pass


class YouTubeUploadError(AntiktheraException):
    """Error during YouTube upload."""
    pass


class RetryableError(AntiktheraException):
    """Error that can be retried."""
    
    def __init__(self, message: str, retry_after: int = 5):
        super().__init__(message)
        self.retry_after = retry_after


class RateLimitError(RetryableError):
    """Rate limit exceeded."""
    pass


class EpisodeAlreadyExistsError(AntiktheraException):
    """Episode already exists for this race/type."""
    pass


class SceneGenerationError(AntiktheraException):
    """Error generating a specific scene."""
    
    def __init__(self, scene_number: int, message: str):
        super().__init__(f"Scene {scene_number}: {message}")
        self.scene_number = scene_number
