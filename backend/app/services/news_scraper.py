"""
F1 News Scraper Service

Context-aware news scraping for different episode types:
- Race Weekend: Session results, driver quotes, team drama
- Off-Week: Broader F1 news, transfers, technical developments, paddock gossip

Uses web scraping and RSS feeds to gather F1 news content.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NewsSource, NewsArticle, ArticleContext
from app.models.scheduler import JobTriggerType

logger = logging.getLogger(__name__)

SAST = ZoneInfo("Africa/Johannesburg")

# Known F1 drivers for extraction (2026 season)
F1_DRIVERS = [
    "Verstappen", "Norris", "Leclerc", "Sainz", "Hamilton", "Russell",
    "Piastri", "Alonso", "Stroll", "Ocon", "Gasly", "Tsunoda", "Lawson",
    "Albon", "Colapinto", "Bottas", "Zhou", "Hulkenberg", "Bortoleto",
    "Bearman", "Antonelli", "Doohan"
]

# Known F1 teams for extraction
F1_TEAMS = [
    "Red Bull", "McLaren", "Ferrari", "Mercedes", "Aston Martin",
    "Alpine", "Williams", "RB", "Sauber", "Haas"
]


class NewsScraperService:
    """Scrapes and processes F1 news from various sources."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.http_client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )

    async def close(self):
        """Close HTTP client."""
        await self.http_client.aclose()

    async def scrape_for_context(
        self,
        scrape_context: Dict[str, Any],
        max_articles: int = 20
    ) -> List[NewsArticle]:
        """
        Scrape news based on context configuration.
        
        Args:
            scrape_context: Configuration from scheduled job
            max_articles: Maximum articles to return
            
        Returns:
            List of relevant NewsArticle objects
        """
        context_type = scrape_context.get("type", "race-weekend")
        focus_areas = scrape_context.get("focus", [])
        
        # Determine time range
        if "date_range_hours" in scrape_context:
            since = datetime.now(SAST) - timedelta(hours=scrape_context["date_range_hours"])
        elif "date_range_days" in scrape_context:
            since = datetime.now(SAST) - timedelta(days=scrape_context["date_range_days"])
        else:
            since = datetime.now(SAST) - timedelta(days=1)

        # Get active news sources
        sources = await self._get_active_sources()
        
        all_articles = []
        for source in sources:
            try:
                articles = await self._scrape_source(source, since)
                all_articles.extend(articles)
            except Exception as e:
                logger.error(f"Failed to scrape {source.name}: {e}")
                continue

        # Process and categorize articles
        processed = await self._process_articles(
            all_articles, 
            context_type, 
            focus_areas
        )

        # Sort by relevance and recency
        processed.sort(
            key=lambda a: (a.source.priority if a.source else 0, a.published_at or datetime.min),
            reverse=True
        )

        return processed[:max_articles]

    async def _get_active_sources(self) -> List[NewsSource]:
        """Get active news sources ordered by priority."""
        result = await self.session.execute(
            select(NewsSource)
            .where(NewsSource.is_active == True)
            .order_by(desc(NewsSource.priority))
        )
        return result.scalars().all()

    async def _scrape_source(
        self,
        source: NewsSource,
        since: datetime
    ) -> List[NewsArticle]:
        """Scrape articles from a single source."""
        articles = []
        
        # Try RSS feed first
        if source.feed_url:
            try:
                articles = await self._scrape_rss(source, since)
                if articles:
                    return articles
            except Exception as e:
                logger.warning(f"RSS failed for {source.name}, trying HTML: {e}")
        
        # Fall back to HTML scraping
        articles = await self._scrape_html(source, since)
        return articles

    async def _scrape_rss(
        self,
        source: NewsSource,
        since: datetime
    ) -> List[NewsArticle]:
        """Scrape articles from RSS feed."""
        import feedparser
        
        response = await self.http_client.get(source.feed_url)
        feed = feedparser.parse(response.text)
        
        articles = []
        for entry in feed.entries[:20]:  # Limit per source
            # Parse published date
            published_at = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                published_at = datetime(*entry.published_parsed[:6], tzinfo=SAST)
            
            # Skip if too old
            if published_at and published_at < since:
                continue
            
            # Check if article already exists
            existing = await self._article_exists(entry.link)
            if existing:
                continue
            
            article = NewsArticle(
                source_id=source.id,
                title=entry.title,
                url=entry.link,
                summary=entry.get('summary', ''),
                published_at=published_at,
            )
            articles.append(article)
        
        return articles

    async def _scrape_html(
        self,
        source: NewsSource,
        since: datetime
    ) -> List[NewsArticle]:
        """Scrape articles from HTML page."""
        try:
            response = await self.http_client.get(source.url)
            soup = BeautifulSoup(response.text, 'html.parser')
        except Exception as e:
            logger.error(f"Failed to fetch {source.url}: {e}")
            return []
        
        articles = []
        
        # Generic article extraction - look for common patterns
        # Find article links with titles
        for link in soup.find_all('a', href=True)[:50]:
            href = link.get('href', '')
            text = link.get_text(strip=True)
            
            # Skip if not an article link
            if not self._is_article_link(href, text):
                continue
            
            # Construct full URL
            url = href
            if not href.startswith('http'):
                url = f"{source.url.rstrip('/')}/{href.lstrip('/')}"
            
            # Check if already exists
            existing = await self._article_exists(url)
            if existing:
                continue
            
            article = NewsArticle(
                source_id=source.id,
                title=text[:500] if text else "Untitled",
                url=url,
            )
            articles.append(article)
        
        return articles[:15]  # Limit per source

    def _is_article_link(self, href: str, text: str) -> bool:
        """Check if a link is likely an article."""
        if not text or len(text) < 20:
            return False
        
        # Skip common non-article links
        skip_patterns = [
            '/tag/', '/category/', '/author/', '/page/',
            'javascript:', '#', 'mailto:', 'tel:',
            '/login', '/register', '/subscribe',
        ]
        
        for pattern in skip_patterns:
            if pattern in href.lower():
                return False
        
        # Should contain article-like patterns
        article_patterns = ['/news/', '/article/', '/story/', '/20', '-']
        
        return any(p in href.lower() for p in article_patterns)

    async def _article_exists(self, url: str) -> bool:
        """Check if an article URL already exists in database."""
        result = await self.session.execute(
            select(NewsArticle).where(NewsArticle.url == url)
        )
        return result.scalar_one_or_none() is not None

    async def _process_articles(
        self,
        articles: List[NewsArticle],
        context_type: str,
        focus_areas: List[str]
    ) -> List[NewsArticle]:
        """Process and categorize articles."""
        processed = []
        
        for article in articles:
            # Set context based on type
            if context_type == "off-week":
                article.context = ArticleContext.OFF_WEEK
            else:
                article.context = ArticleContext.RACE_WEEKEND
            
            # Extract mentioned entities
            text = f"{article.title} {article.summary or ''}"
            article.mentioned_drivers = self._extract_drivers(text)
            article.mentioned_teams = self._extract_teams(text)
            article.keywords = self._extract_keywords(text, focus_areas)
            
            # Calculate relevance score based on focus areas
            relevance = self._calculate_relevance(article, focus_areas)
            
            if relevance > 0.3:  # Minimum relevance threshold
                processed.append(article)
                self.session.add(article)
        
        await self.session.commit()
        return processed

    def _extract_drivers(self, text: str) -> List[str]:
        """Extract mentioned F1 drivers from text."""
        mentioned = []
        text_upper = text.upper()
        
        for driver in F1_DRIVERS:
            if driver.upper() in text_upper:
                mentioned.append(driver)
        
        return mentioned

    def _extract_teams(self, text: str) -> List[str]:
        """Extract mentioned F1 teams from text."""
        mentioned = []
        text_upper = text.upper()
        
        for team in F1_TEAMS:
            if team.upper() in text_upper:
                mentioned.append(team)
        
        return mentioned

    def _extract_keywords(self, text: str, focus_areas: List[str]) -> List[str]:
        """Extract relevant keywords based on focus areas."""
        keywords = []
        text_lower = text.lower()
        
        # Keyword mappings for different focus areas
        keyword_map = {
            "fp1_results": ["fp1", "practice 1", "first practice"],
            "fp2_results": ["fp2", "practice 2", "second practice"],
            "sprint_results": ["sprint", "sprint race", "sprint qualifying"],
            "race_results": ["race result", "winner", "podium", "championship"],
            "driver_quotes": ["said", "told", "interview", "comments"],
            "driver_battles": ["battle", "duel", "rivalry", "fight"],
            "team_drama": ["drama", "controversy", "dispute", "conflict"],
            "penalties": ["penalty", "steward", "investigation", "grid penalty"],
            "championship_implications": ["championship", "points", "standings", "title"],
            "track_conditions": ["track", "weather", "grip", "conditions"],
            "post_race_interviews": ["post-race", "interview", "reaction"],
            "paddock_news": ["paddock", "news", "update", "revealed"],
            "transfers": ["transfer", "move", "sign", "contract", "leaving"],
            "technical_developments": ["technical", "upgrade", "development", "aerodynamic"],
            "paddock_gossip": ["rumour", "gossip", "speculation", "alleged"],
        }
        
        for focus in focus_areas:
            if focus in keyword_map:
                for keyword in keyword_map[focus]:
                    if keyword in text_lower:
                        keywords.append(focus)
                        break
        
        return list(set(keywords))

    def _calculate_relevance(
        self,
        article: NewsArticle,
        focus_areas: List[str]
    ) -> float:
        """Calculate relevance score for an article (0-1)."""
        score = 0.0
        
        # Base score for having any content
        if article.title:
            score += 0.3
        
        # Score for matching focus areas
        if article.keywords:
            match_ratio = len(set(article.keywords) & set(focus_areas)) / max(len(focus_areas), 1)
            score += 0.4 * match_ratio
        
        # Score for mentioning drivers/teams
        if article.mentioned_drivers:
            score += 0.15
        if article.mentioned_teams:
            score += 0.15
        
        return min(score, 1.0)

    async def fetch_article_content(self, article: NewsArticle) -> Optional[str]:
        """Fetch full article content for processing."""
        try:
            response = await self.http_client.get(article.url)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Try to find article body
            content_selectors = [
                'article', '.article-body', '.article-content',
                '.story-body', '.post-content', 'main article',
            ]
            
            for selector in content_selectors:
                content = soup.select_one(selector)
                if content:
                    # Extract text, clean up
                    text = content.get_text(separator=' ', strip=True)
                    # Remove excessive whitespace
                    text = re.sub(r'\s+', ' ', text)
                    article.full_content = text[:10000]  # Limit size
                    article.is_processed = True
                    await self.session.commit()
                    return text
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to fetch content for {article.url}: {e}")
            article.processing_error = str(e)
            await self.session.commit()
            return None

    async def get_articles_for_episode(
        self,
        trigger_type: JobTriggerType,
        race_id: Optional[int] = None,
        limit: int = 10
    ) -> List[NewsArticle]:
        """Get relevant articles for generating an episode."""
        # Determine context
        if trigger_type == JobTriggerType.WEEKLY_RECAP:
            context = ArticleContext.OFF_WEEK
            time_range = timedelta(days=7)
        else:
            context = ArticleContext.RACE_WEEKEND
            time_range = timedelta(hours=48)
        
        since = datetime.now(SAST) - time_range
        
        query = (
            select(NewsArticle)
            .where(
                and_(
                    NewsArticle.context == context,
                    NewsArticle.scraped_at >= since,
                    NewsArticle.used_in_episode_id.is_(None),  # Not used yet
                )
            )
            .order_by(desc(NewsArticle.published_at))
            .limit(limit)
        )
        
        result = await self.session.execute(query)
        return result.scalars().all()

    async def mark_articles_used(
        self,
        article_ids: List[int],
        episode_id: int
    ) -> None:
        """Mark articles as used in an episode."""
        for article_id in article_ids:
            result = await self.session.execute(
                select(NewsArticle).where(NewsArticle.id == article_id)
            )
            article = result.scalar_one_or_none()
            if article:
                article.used_in_episode_id = episode_id
                article.used_at = datetime.now(SAST)
        
        await self.session.commit()
