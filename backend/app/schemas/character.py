"""Character schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CharacterBase(BaseModel):
    """Base character schema."""
    name: str
    display_name: str
    description: Optional[str] = None
    voice_description: Optional[str] = None
    personality: Optional[str] = None


class CharacterCreate(CharacterBase):
    """Schema for creating a character."""
    pass


class CharacterUpdate(BaseModel):
    """Schema for updating a character."""
    name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    voice_description: Optional[str] = None
    personality: Optional[str] = None
    is_active: Optional[bool] = None


class CharacterImageCreate(BaseModel):
    """Schema for creating a character image."""
    image_type: str = "reference"
    pose_description: Optional[str] = None
    is_primary: bool = False


class CharacterImageResponse(BaseModel):
    """Schema for character image response."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    character_id: int
    image_path: str
    image_type: str
    pose_description: Optional[str]
    is_primary: bool
    created_at: datetime


class CharacterResponse(CharacterBase):
    """Schema for character response."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    primary_image_path: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    images: list[CharacterImageResponse] = []
