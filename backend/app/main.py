"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import episodes, characters, races, analytics, scheduler, news
from app.config import settings
from app.database import engine
from app.models import Base

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log") if settings.APP_ENV == "production" else logging.NullHandler(),
    ],
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting Antikythera F1 Video Generator")
    logger.info(f"Environment: {settings.APP_ENV}")
    logger.info(f"Debug mode: {settings.DEBUG}")
    
    # Startup
    logger.info("Initializing database connection...")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    await engine.dispose()


app = FastAPI(
    title="Antikythera F1 Video Generator",
    description="Automated video generation system for satirical F1 commentary videos",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(episodes.router, prefix="/api/v1/episodes", tags=["Episodes"])
app.include_router(characters.router, prefix="/api/v1/characters", tags=["Characters"])
app.include_router(races.router, prefix="/api/v1/races", tags=["Races"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["Analytics"])
app.include_router(scheduler.router, prefix="/api/v1", tags=["Scheduler"])
app.include_router(news.router, prefix="/api/v1", tags=["News"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Antikythera F1 Video Generator",
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "environment": settings.APP_ENV,
    }
