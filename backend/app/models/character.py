"""Character models."""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Character(Base):
    """F1 character definitions with voice/personality and caricature traits for consistent generation."""

    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    voice_description: Mapped[Optional[str]] = mapped_column(String(255))
    personality: Mapped[Optional[str]] = mapped_column(Text)
    primary_image_path: Mapped[Optional[str]] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Caricature traits for satirical image generation
    role: Mapped[Optional[str]] = mapped_column(String(50))
    team: Mapped[Optional[str]] = mapped_column(String(100))
    nationality: Mapped[Optional[str]] = mapped_column(String(100))
    physical_features: Mapped[Optional[str]] = mapped_column(Text)
    comedy_angle: Mapped[Optional[str]] = mapped_column(Text)
    signature_expression: Mapped[Optional[str]] = mapped_column(Text)
    signature_pose: Mapped[Optional[str]] = mapped_column(Text)
    props: Mapped[Optional[str]] = mapped_column(Text)
    background_type: Mapped[Optional[str]] = mapped_column(String(50), default="orange_gradient")
    background_detail: Mapped[Optional[str]] = mapped_column(Text)
    clothing_description: Mapped[Optional[str]] = mapped_column(Text)
    caricature_prompt: Mapped[Optional[str]] = mapped_column(Text)

    # Relationships
    images: Mapped[List["CharacterImage"]] = relationship("CharacterImage", back_populates="character", cascade="all, delete-orphan")
    scenes: Mapped[List["Scene"]] = relationship("Scene", back_populates="character")

    def __repr__(self) -> str:
        return f"<Character {self.name}>"


class CharacterImage(Base):
    """Multiple reference images per character for variety."""
    
    __tablename__ = "character_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), nullable=False)
    image_path: Mapped[str] = mapped_column(String(500), nullable=False)
    image_type: Mapped[str] = mapped_column(String(50), default="reference")  # reference, action, emotion
    pose_description: Mapped[Optional[str]] = mapped_column(String(255))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    is_style_reference: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    character: Mapped["Character"] = relationship("Character", back_populates="images")
    scenes: Mapped[List["Scene"]] = relationship("Scene", back_populates="character_image")

    def __repr__(self) -> str:
        return f"<CharacterImage {self.id} for Character {self.character_id}>"


# Import Scene here to avoid circular imports
from app.models.scene import Scene
