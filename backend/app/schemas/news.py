"""News schemas for API."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.news import ArticleContext


class NewsSourceBase(BaseModel):
    """Base news source schema."""
    name: str
    url: str
    feed_url: Optional[str] = None
    scrape_selector: Optional[str] = None
    priority: int = 5
    is_active: bool = True


class NewsSourceCreate(NewsSourceBase):
    """Schema for creating a news source."""
    pass


class NewsSourceResponse(NewsSourceBase):
    """Schema for news source response."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    last_scraped_at: Optional[datetime]
    created_at: datetime


class NewsArticleBase(BaseModel):
    """Base news article schema."""
    title: str
    url: str
    summary: Optional[str] = None
    context: ArticleContext = ArticleContext.RACE_WEEKEND


class NewsArticleCreate(NewsArticleBase):
    """Schema for creating a news article."""
    source_id: Optional[int] = None


class NewsArticleResponse(NewsArticleBase):
    """Schema for news article response."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    source_id: Optional[int]
    full_content: Optional[str]
    keywords: Optional[list[str]]
    mentioned_drivers: Optional[list[str]]
    mentioned_teams: Optional[list[str]]
    sentiment_score: Optional[Decimal]
    published_at: Optional[datetime]
    scraped_at: datetime
    used_in_episode_id: Optional[int]
    used_at: Optional[datetime]
    is_processed: bool
    created_at: datetime


class NewsArticleWithSource(NewsArticleResponse):
    """Article with source details."""
    source_name: Optional[str] = None


class EpisodeStorylineBase(BaseModel):
    """Base storyline schema."""
    main_storyline: str
    secondary_storylines: Optional[list[str]] = None
    comedic_angle: Optional[str] = None


class EpisodeStorylineCreate(EpisodeStorylineBase):
    """Schema for creating a storyline."""
    episode_id: int
    news_article_ids: Optional[list[int]] = None
    key_facts: Optional[dict] = None


class EpisodeStorylineResponse(EpisodeStorylineBase):
    """Schema for storyline response."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    episode_id: int
    news_article_ids: Optional[list[int]]
    key_facts: Optional[dict]
    prompt_used: Optional[str]
    model_used: Optional[str]
    tokens_used: Optional[int]
    created_at: datetime


class ScrapeRequest(BaseModel):
    """Request to trigger a news scrape."""
    context_type: str = "race-weekend"
    focus_areas: list[str] = []
    date_range_hours: Optional[int] = None
    date_range_days: Optional[int] = None
    max_articles: int = 20


class ScrapeResponse(BaseModel):
    """Response from a scrape operation."""
    articles_scraped: int
    sources_checked: int
    errors: list[str]
