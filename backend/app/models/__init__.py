"""SQLAlchemy models."""

from app.database import Base
from app.models.character import Character, CharacterImage
from app.models.race import Race
from app.models.episode import Episode, EpisodeType, EpisodeStatus
from app.models.scene import Scene, SceneStatus
from app.models.logs import GenerationLog, LogLevel, LogComponent, APIUsage, APIProvider, CleanupLog
from app.models.scheduler import ScheduledJob, JobStatus, JobTriggerType
from app.models.news import NewsSource, NewsArticle, ArticleContext, EpisodeStoryline
from app.models.gag import RunningGag, GagUsage, GagStatus, GagCategory

__all__ = [
    "Base",
    "Character",
    "CharacterImage",
    "Race",
    "Episode",
    "EpisodeType",
    "EpisodeStatus",
    "Scene",
    "SceneStatus",
    "GenerationLog",
    "LogLevel",
    "LogComponent",
    "APIUsage",
    "APIProvider",
    "CleanupLog",
    # Scheduler
    "ScheduledJob",
    "JobStatus",
    "JobTriggerType",
    # News
    "NewsSource",
    "NewsArticle",
    "ArticleContext",
    "EpisodeStoryline",
    # Running Gags
    "RunningGag",
    "GagUsage",
    "GagStatus",
    "GagCategory",
]
