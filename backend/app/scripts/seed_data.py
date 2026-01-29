"""
Seed database with F1 2026 calendar and characters.

Usage:
    python -m app.scripts.seed_data [--reset]

Options:
    --reset     Drop existing data before seeding
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_maker
from app.models import Race, Character


# Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CHARACTER_DIR = PROJECT_ROOT / "character-system" / "personalities"


async def load_calendar(session: AsyncSession, reset: bool = False) -> int:
    """Load F1 2026 calendar into races table."""
    calendar_path = DATA_DIR / "calendar-2026.json"
    
    if not calendar_path.exists():
        print(f"❌ Calendar file not found: {calendar_path}")
        return 0
    
    with open(calendar_path, "r") as f:
        calendar = json.load(f)
    
    if reset:
        await session.execute(delete(Race).where(Race.season == calendar["season"]))
        print(f"   Deleted existing {calendar['season']} races")
    
    races_created = 0
    
    for race_data in calendar["races"]:
        # Check if race already exists
        existing = await session.execute(
            select(Race).where(
                Race.season == calendar["season"],
                Race.round_number == race_data["round"]
            )
        )
        if existing.scalar_one_or_none():
            print(f"   ⏭️  Race {race_data['round']} already exists, skipping")
            continue
        
        sessions = race_data.get("sessions", {})
        
        race = Race(
            season=calendar["season"],
            round_number=race_data["round"],
            race_name=race_data["name"],
            circuit_name=race_data.get("circuit"),
            country=race_data.get("country"),
            race_date=datetime.strptime(race_data["date"], "%Y-%m-%d").date(),
            is_sprint_weekend=race_data.get("is_sprint", False),
            fp1_datetime=parse_datetime(sessions.get("fp1")),
            fp2_datetime=parse_datetime(sessions.get("fp2")),
            fp3_datetime=parse_datetime(sessions.get("fp3")),
            qualifying_datetime=parse_datetime(sessions.get("qualifying")),
            race_datetime=parse_datetime(sessions.get("race")),
            sprint_qualifying_datetime=parse_datetime(sessions.get("sprint_qualifying")),
            sprint_race_datetime=parse_datetime(sessions.get("sprint")),
        )
        session.add(race)
        races_created += 1
        print(f"   ✅ {race_data['name']}" + (" 🏎️ Sprint" if race_data.get("is_sprint") else ""))
    
    await session.commit()
    return races_created


async def load_characters(session: AsyncSession, reset: bool = False) -> int:
    """Load character profiles from JSON files."""
    if reset:
        await session.execute(delete(Character))
        print("   Deleted existing characters")
    
    characters_created = 0
    
    # Load drivers
    drivers_dir = CHARACTER_DIR / "drivers"
    if drivers_dir.exists():
        for json_file in drivers_dir.glob("*.json"):
            if await load_character_file(session, json_file, "driver"):
                characters_created += 1
    
    # Load team principals
    principals_dir = CHARACTER_DIR / "principals"
    if principals_dir.exists():
        for json_file in principals_dir.glob("*.json"):
            if await load_character_file(session, json_file, "principal"):
                characters_created += 1
    
    await session.commit()
    return characters_created


async def load_character_file(session: AsyncSession, json_path: Path, role: str) -> bool:
    """Load a single character from JSON file."""
    with open(json_path, "r") as f:
        data = json.load(f)
    
    char_id = data.get("id", json_path.stem)
    
    # Check if exists
    existing = await session.execute(
        select(Character).where(Character.character_id == char_id)
    )
    if existing.scalar_one_or_none():
        print(f"   ⏭️  Character {char_id} already exists, skipping")
        return False
    
    # Extract personality traits
    personality = data.get("personality_dimensions", {})
    
    character = Character(
        character_id=char_id,
        display_name=data.get("name", char_id.replace("_", " ").title()),
        role=role,
        team_id=data.get("team"),
        nationality=data.get("nationality"),
        personality_profile=personality,
        comedy_archetype=data.get("comedy_archetype"),
        satirical_angle=data.get("satirical_angle"),
        speaking_style=data.get("speaking_style"),
        catchphrases=data.get("catchphrases", []),
        visual_profile=data.get("visual_profile"),
        relationships=data.get("relationships_summary"),
        storyline_hooks=data.get("storyline_hooks", []),
        meme_status=data.get("meme_status"),
        is_active=True,
    )
    session.add(character)
    print(f"   ✅ {data.get('name', char_id)} ({role})")
    return True


def parse_datetime(dt_string: str | None) -> datetime | None:
    """Parse ISO datetime string."""
    if not dt_string:
        return None
    try:
        return datetime.fromisoformat(dt_string.replace("Z", "+00:00"))
    except ValueError:
        return None


async def main(reset: bool = False):
    """Main seed function."""
    print("\n" + "=" * 50)
    print("   Antikythera F1 Generator - Database Seed")
    print("=" * 50 + "\n")
    
    if reset:
        print("⚠️  RESET MODE: Existing data will be deleted\n")
    
    async with async_session_maker() as session:
        # Load calendar
        print("📅 Loading 2026 F1 Calendar...")
        races = await load_calendar(session, reset)
        print(f"   → {races} races loaded\n")
        
        # Load characters
        print("🎭 Loading character profiles...")
        chars = await load_characters(session, reset)
        print(f"   → {chars} characters loaded\n")
        
        # Verify counts
        race_count = (await session.execute(text("SELECT COUNT(*) FROM races"))).scalar()
        char_count = (await session.execute(text("SELECT COUNT(*) FROM characters"))).scalar()
        
        print("=" * 50)
        print("✅ Seeding complete!")
        print(f"   📅 Races in database: {race_count}")
        print(f"   🎭 Characters in database: {char_count}")
        print("=" * 50 + "\n")


if __name__ == "__main__":
    reset_flag = "--reset" in sys.argv
    asyncio.run(main(reset=reset_flag))
