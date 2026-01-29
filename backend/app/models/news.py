"""News scraping models."""

import enum
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ArticleContext(str, enum.Enum):
    """Context for news article usage."""
    RACE_WEEKEND = "race-weekend"
    OFF_WEEK = "off-week"
    BREAKING = "breaking"
    FEATURE = "feature"


class NewsSource(Base):
    """F1 news sources for automated scraping."""
    
    __tablename__ = "news_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    feed_url: Mapped[Optional[str]] = mapped_column(String(500))  # RSS feed
    scrape_selector: Mapped[Optional[str]] = mapped_column(String(255))  # CSS selector
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)  # 1-10
    last_scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    articles: Mapped[List["NewsArticle"]] = relationship("NewsArticle", back_populates="source")

    def __repr__(self) -> str:
        return f"<NewsSource {self.name}>"


class NewsArticle(Base):
    """Cached news articles for content generation."""
    
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("news_sources.id"))
    
    # Article content
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), unique=True, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    full_content: Mapped[Optional[str]] = mapped_column(Text)
    
    # Categorization
    context: Mapped[ArticleContext] = mapped_column(Enum(ArticleContext), default=ArticleContext.RACE_WEEKEND)
    keywords: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text))
    mentioned_drivers: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text))
    mentioned_teams: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text))
    sentiment_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2))  # -1 to 1
    
    # Usage tracking
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    used_in_episode_id: Mapped[Optional[int]] = mapped_column(ForeignKey("episodes.id"))
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    # Processing
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False)
    processing_error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    source: Mapped[Optional["NewsSource"]] = relationship("NewsSource", back_populates="articles")
    episode: Mapped[Optional["Episode"]] = relationship("Episode", backref="news_articles")

    def __repr__(self) -> str:
        return f"<NewsArticle {self.id}: {self.title[:50]}...>"


class EpisodeStoryline(Base):
    """Storyline development and source tracking per episode."""
    
    __tablename__ = "episode_storylines"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False)
    
    # Storyline metadata
    main_storyline: Mapped[str] = mapped_column(Text, nullable=False)
    secondary_storylines: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text))
    comedic_angle: Mapped[Optional[str]] = mapped_column(Text)
    
    # Source material
    news_article_ids: Mapped[Optional[List[int]]] = mapped_column(ARRAY(Integer))
    key_facts: Mapped[Optional[dict]] = mapped_column(JSONB)
    
    # Generation tracking
    prompt_used: Mapped[Optional[str]] = mapped_column(Text)
    model_used: Mapped[Optional[str]] = mapped_column(String(100))
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    episode: Mapped["Episode"] = relationship("Episode", backref="storyline")

    def __repr__(self) -> str:
        return f"<EpisodeStoryline {self.episode_id}: {self.main_storyline[:50]}...>"


# Import to avoid circular imports
from app.models.episode import Episode
