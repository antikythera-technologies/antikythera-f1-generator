"""Character API endpoints."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models.character import Character, CharacterImage
from app.schemas.character import (
    CharacterCreate,
    CharacterImageResponse,
    CharacterResponse,
    CharacterUpdate,
)
# Personality data loaded from DB (characters.personality column)
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
    if image_type == "caricature":
        # Caricature images always use a fixed name for consistent URLs
        ext = image.filename.rsplit(".", 1)[-1] if "." in (image.filename or "") else "png"
        object_name = f"{character.name}/caricature.{ext}"
    else:
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


@router.get("/{character_id}/personality")
async def get_character_personality(
    character_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Return the full personality JSON for a character.

    Reads from the database personality column (JSON stored as text).
    """
    character = await db.get(Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    if not character.personality:
        raise HTTPException(
            status_code=404,
            detail=f"No personality data for {character.display_name or character.name}",
        )

    return json.loads(character.personality)


@router.post("/{character_id}/generate-image")
async def generate_character_image(
    character_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Generate a new caricature image for a character using ComfyUI.

    Uses Flux Dev + ANTKF1STYLE LoRA + PuLID on RunPod.
    Enriches the prompt with personality traits from the database
    (characters.personality column).  If no personality data exists,
    falls back to the minimal DB fields (display_name + team).
    """
    from app.services.image_generator import ImageGenerator

    character = await db.get(Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # ----- Load rich traits from database personality column -----
    personality_loaded = False

    if character.personality:
        try:
            from app.services.personality import load_personality_traits_from_db
            traits = load_personality_traits_from_db(character.personality)
            personality_loaded = True
            logger.info(
                f"Loaded personality traits for {character.name} from DB"
            )
        except Exception as e:
            logger.warning(
                f"Failed to parse personality for {character.name}: {e}. "
                "Falling back to DB-only traits."
            )
            traits = {
                "display_name": character.display_name,
                "team": character.team,
            }
    else:
        logger.info(
            f"No personality JSON found for {character.name}. "
            "Using DB-only traits."
        )
        traits = {
            "display_name": character.display_name,
            "team": character.team,
        }

    # Ensure face reference is in ComfyUI (downloads from MinIO if needed)
    generator = ImageGenerator()
    face_image = await generator.ensure_face_reference(character.name)

    logger.info(
        f"Generating caricature for {character.display_name} "
        f"(face={'yes' if face_image else 'no'})"
        f"{' (personality-enriched)' if personality_loaded else ''}"
    )

    result = await generator.generate_character_reference(
        character_name=character.name,
        character_traits=traits,
        face_image=face_image,
    )

    await db.flush()

    return {
        "character_id": character_id,
        "character_name": character.display_name,
        "image_path": result.image_path,
        "generation_time_ms": result.generation_time_ms,
        "prompt_length": len(result.prompt_used),
        "personality_loaded": personality_loaded,
        "face_reference_used": face_image is not None,
    }


@router.get("/{character_id}/face-reference")
async def get_face_reference(
    character_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get the face reference image URL for a character."""
    character = await db.get(Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    storage = StorageService()
    face_path = await storage.get_face_reference_path(character.name)

    return {
        "character_id": character_id,
        "character_name": character.name,
        "face_reference_path": face_path,
        "has_face_reference": face_path is not None,
    }


@router.post("/{character_id}/face-reference")
async def upload_face_reference(
    character_id: int,
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload or replace the face reference image for a character.

    This is the close-up headshot used by PuLID for face conditioning
    during caricature generation.  Replaces any existing face reference.
    """
    character = await db.get(Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    content = await image.read()
    content_type = image.content_type or "image/jpeg"

    storage = StorageService()
    face_path = await storage.upload_face_reference(
        character.name, content, content_type
    )

    logger.info(f"Uploaded face reference for {character.name}: {face_path}")

    return {
        "character_id": character_id,
        "character_name": character.name,
        "face_reference_path": face_path,
    }
