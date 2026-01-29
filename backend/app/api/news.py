"""News API endpoints."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import NewsSource, NewsArticle, ArticleContext
from app.models.scheduler import JobTriggerType
from app.services import NewsScraperService
from app.schemas.news import (
    NewsSourceCreate,
    NewsSourceResponse,
    NewsArticleResponse,
    NewsArticleWithSource,
    ScrapeRequest,
    ScrapeResponse,
)

router = APIRouter(prefix="/news", tags=["News"])


# ============================================
# NEWS SOURCES
# ============================================

@router.get("/sources", response_model=List[NewsSourceResponse])
async def list_sources(
    active_only: bool = Query(default=True),
    session: AsyncSession = Depends(get_db),
):
    """List all news sources."""
    query = select(NewsSource).order_by(desc(NewsSource.priority))
    if active_only:
        query = query.where(NewsSource.is_active == True)
    
    result = await session.execute(query)
    return result.scalars().all()


@router.post("/sources", response_model=NewsSourceResponse)
async def create_source(
    source_data: NewsSourceCreate,
    session: AsyncSession = Depends(get_db),
):
    """Add a new news source."""
    source = NewsSource(**source_data.model_dump())
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


@router.patch("/sources/{source_id}", response_model=NewsSourceResponse)
async def update_source(
    source_id: int,
    is_active: Optional[bool] = None,
    priority: Optional[int] = None,
    session: AsyncSession = Depends(get_db),
):
    """Update a news source."""
    result = await session.execute(
        select(NewsSource).where(NewsSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    
    if is_active is not None:
        source.is_active = is_active
    if priority is not None:
        source.priority = priority
    
    await session.commit()
    await session.refresh(source)
    return source


@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: int,
    session: AsyncSession = Depends(get_db),
):
    """Delete a news source."""
    result = await session.execute(
        select(NewsSource).where(NewsSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    
    await session.delete(source)
    await session.commit()
    return {"status": "deleted"}


# ============================================
# NEWS ARTICLES
# ============================================

@router.get("/articles", response_model=List[NewsArticleResponse])
async def list_articles(
    context: Optional[ArticleContext] = None,
    source_id: Optional[int] = None,
    used: Optional[bool] = None,
    limit: int = Query(default=50, le=200),
    session: AsyncSession = Depends(get_db),
):
    """List news articles with filters."""
    query = select(NewsArticle).order_by(desc(NewsArticle.scraped_at))
    
    if context:
        query = query.where(NewsArticle.context == context)
    if source_id:
        query = query.where(NewsArticle.source_id == source_id)
    if used is not None:
        if used:
            query = query.where(NewsArticle.used_in_episode_id.is_not(None))
        else:
            query = query.where(NewsArticle.used_in_episode_id.is_(None))
    
    query = query.limit(limit)
    result = await session.execute(query)
    return result.scalars().all()


@router.get("/articles/{article_id}", response_model=NewsArticleWithSource)
async def get_article(
    article_id: int,
    session: AsyncSession = Depends(get_db),
):
    """Get a specific article with source details."""
    result = await session.execute(
        select(NewsArticle).where(NewsArticle.id == article_id)
    )
    article = result.scalar_one_or_none()
    
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    response = NewsArticleWithSource.model_validate(article)
    if article.source:
        response.source_name = article.source.name
    
    return response


@router.post("/articles/{article_id}/fetch-content")
async def fetch_article_content(
    article_id: int,
    session: AsyncSession = Depends(get_db),
):
    """Fetch full content for an article."""
    result = await session.execute(
        select(NewsArticle).where(NewsArticle.id == article_id)
    )
    article = result.scalar_one_or_none()
    
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    scraper = NewsScraperService(session)
    try:
        content = await scraper.fetch_article_content(article)
        return {
            "status": "success" if content else "no_content",
            "content_length": len(content) if content else 0,
        }
    finally:
        await scraper.close()


# ============================================
# SCRAPING
# ============================================

@router.post("/scrape", response_model=ScrapeResponse)
async def scrape_news(
    request: ScrapeRequest,
    session: AsyncSession = Depends(get_db),
):
    """
    Trigger a news scrape with specific context.
    
    Context types:
    - race-weekend: Focus on session results, driver quotes, track conditions
    - off-week: Broader news, transfers, technical developments, gossip
    """
    scrape_context = {
        "type": request.context_type,
        "focus": request.focus_areas,
    }
    
    if request.date_range_hours:
        scrape_context["date_range_hours"] = request.date_range_hours
    elif request.date_range_days:
        scrape_context["date_range_days"] = request.date_range_days
    else:
        # Default based on context type
        if request.context_type == "off-week":
            scrape_context["date_range_days"] = 7
        else:
            scrape_context["date_range_hours"] = 24
    
    scraper = NewsScraperService(session)
    errors = []
    
    try:
        articles = await scraper.scrape_for_context(
            scrape_context,
            max_articles=request.max_articles
        )
        
        # Count sources
        sources = await session.execute(
            select(NewsSource).where(NewsSource.is_active == True)
        )
        source_count = len(sources.scalars().all())
        
        return ScrapeResponse(
            articles_scraped=len(articles),
            sources_checked=source_count,
            errors=errors,
        )
    except Exception as e:
        errors.append(str(e))
        return ScrapeResponse(
            articles_scraped=0,
            sources_checked=0,
            errors=errors,
        )
    finally:
        await scraper.close()


@router.get("/for-episode", response_model=List[NewsArticleResponse])
async def get_articles_for_episode(
    trigger_type: JobTriggerType,
    race_id: Optional[int] = None,
    limit: int = Query(default=10, le=50),
    session: AsyncSession = Depends(get_db),
):
    """Get relevant articles for generating a specific episode type."""
    scraper = NewsScraperService(session)
    try:
        articles = await scraper.get_articles_for_episode(
            trigger_type=trigger_type,
            race_id=race_id,
            limit=limit,
        )
        return articles
    finally:
        await scraper.close()
