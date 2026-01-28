"""Character API endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.character import Character, CharacterImage
from app.schemas.character import (
    CharacterCreate,
    CharacterImageResponse,
    CharacterResponse,
    CharacterUpdate,
)
from app.services.storage import StorageService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=list[CharacterResponse])
async def list_characters(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """List all characters."""
    stmt = select(Character).options(selectinload(Character.images))
    
    if active_only:
        stmt = stmt.where(Character.is_active == True)
    
    stmt = stmt.order_by(Character.name)
    
    result = await db.execute(stmt)
    characters = result.scalars().all()
    
    return characters


@router.get("/{character_id}", response_model=CharacterResponse)
async def get_character(
    character_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get character by ID."""
    stmt = (
        select(Character)
        .options(selectinload(Character.images))
        .where(Character.id == character_id)
    )
    result = await db.execute(stmt)
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    return character


@router.post("", response_model=CharacterResponse)
async def create_character(
    character: CharacterCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new character."""
    # Check for duplicate name
    stmt = select(Character).where(Character.name == character.name)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Character with this name already exists")
    
    db_character = Character(**character.model_dump())
    db.add(db_character)
    await db.flush()
    
    logger.info(f"Created character: {db_character.name}")
    
    return db_character


@router.put("/{character_id}", response_model=CharacterResponse)
async def update_character(
    character_id: int,
    character: CharacterUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a character."""
    db_character = await db.get(Character, character_id)
    
    if not db_character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    update_data = character.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_character, key, value)
    
    logger.info(f"Updated character: {db_character.name}")
    
    return db_character


@router.post("/{character_id}/images", response_model=CharacterImageResponse)
async def upload_character_image(
    character_id: int,
    image: UploadFile = File(...),
    image_type: str = Form(default="reference"),
    pose_description: Optional[str] = Form(default=None),
    is_primary: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
):
    """Upload a character image."""
    character = await db.get(Character, character_id)
    
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    # Upload to MinIO
    storage = StorageService()
    object_name = f"{character.name}/{image.filename}"
    
    content = await image.read()
    image_path = await storage.upload_character_image(object_name, content)
    
    # Create database record
    db_image = CharacterImage(
        character_id=character_id,
        image_path=image_path,
        image_type=image_type,
        pose_description=pose_description,
        is_primary=is_primary,
    )
    db.add(db_image)
    
    # Update primary image if needed
    if is_primary:
        character.primary_image_path = image_path
        # Unset other primary images
        stmt = select(CharacterImage).where(
            CharacterImage.character_id == character_id,
            CharacterImage.is_primary == True,
            CharacterImage.id != db_image.id,
        )
        result = await db.execute(stmt)
        for other_image in result.scalars():
            other_image.is_primary = False
    
    await db.flush()
    
    logger.info(f"Uploaded image for character {character.name}: {image_path}")
    
    return db_image
