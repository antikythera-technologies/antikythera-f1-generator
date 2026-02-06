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
    role: Optional[str] = None
    team: Optional[str] = None
    nationality: Optional[str] = None
    physical_features: Optional[str] = None
    comedy_angle: Optional[str] = None
    signature_expression: Optional[str] = None
    signature_pose: Optional[str] = None
    props: Optional[str] = None
    background_type: Optional[str] = "orange_gradient"
    background_detail: Optional[str] = None
    clothing_description: Optional[str] = None


class CharacterUpdate(BaseModel):
    """Schema for updating a character."""
    name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    voice_description: Optional[str] = None
    personality: Optional[str] = None
    is_active: Optional[bool] = None
    role: Optional[str] = None
    team: Optional[str] = None
    nationality: Optional[str] = None
    physical_features: Optional[str] = None
    comedy_angle: Optional[str] = None
    signature_expression: Optional[str] = None
    signature_pose: Optional[str] = None
    props: Optional[str] = None
    background_type: Optional[str] = None
    background_detail: Optional[str] = None
    clothing_description: Optional[str] = None


class CharacterImageCreate(BaseModel):
    """Schema for creating a character image."""
    image_type: str = "reference"
    pose_description: Optional[str] = None
    is_primary: bool = False
    is_style_reference: bool = False


class CharacterImageResponse(BaseModel):
    """Schema for character image response."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    character_id: int
    image_path: str
    image_type: str
    pose_description: Optional[str]
    is_primary: bool
    is_style_reference: bool
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
    role: Optional[str] = None
    team: Optional[str] = None
    nationality: Optional[str] = None
    physical_features: Optional[str] = None
    comedy_angle: Optional[str] = None
    signature_expression: Optional[str] = None
    signature_pose: Optional[str] = None
    props: Optional[str] = None
    background_type: Optional[str] = None
    background_detail: Optional[str] = None
    clothing_description: Optional[str] = None
    caricature_prompt: Optional[str] = None
