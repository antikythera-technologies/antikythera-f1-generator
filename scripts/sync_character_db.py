#!/usr/bin/env python3
"""
Sync character database with personality JSONs and new MinIO caricature paths.

Runs inside the production Docker container to update PostgreSQL.
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Production DB (matches .env on server)
DATABASE_URL = "postgresql+asyncpg://pgadmin_user:Pg%40dm1nUs3r@postgres.antikythera.co.za:5432/AntikytheraF1Series"

# MinIO image path format (relative — dashboard prepends NEXT_PUBLIC_MINIO_URL)
MINIO_IMAGE_PATH = "f1-characters/{char_id}/caricature.png"

# Team slug → display name
TEAM_DISPLAY = {
    "red_bull_racing": "Red Bull Racing",
    "racing_bulls": "Racing Bulls",
    "mclaren": "McLaren",
    "ferrari": "Ferrari",
    "mercedes": "Mercedes",
    "williams": "Williams",
    "haas": "Haas",
    "alpine": "Alpine",
    "aston_martin": "Aston Martin",
    "audi": "Audi",
    "cadillac": "Cadillac",
}

# Category → character_type_id
TYPE_IDS = {
    "drivers": 1,
    "principals": 2,
    "pundits": 3,
}

# The 42 characters for 2026 season (from personality JSONs)
CHARACTERS = [
    # Drivers (22)
    {"id": "alex_albon", "name": "Alex Albon", "team": "williams", "cat": "drivers"},
    {"id": "arvid_lindblad", "name": "Arvid Lindblad", "team": "racing_bulls", "cat": "drivers"},
    {"id": "carlos_sainz", "name": "Carlos Sainz", "team": "williams", "cat": "drivers"},
    {"id": "charles_leclerc", "name": "Charles Leclerc", "team": "ferrari", "cat": "drivers"},
    {"id": "esteban_ocon", "name": "Esteban Ocon", "team": "haas", "cat": "drivers"},
    {"id": "fernando_alonso", "name": "Fernando Alonso", "team": "aston_martin", "cat": "drivers"},
    {"id": "franco_colapinto", "name": "Franco Colapinto", "team": "alpine", "cat": "drivers"},
    {"id": "gabriel_bortoleto", "name": "Gabriel Bortoleto", "team": "audi", "cat": "drivers"},
    {"id": "george_russell", "name": "George Russell", "team": "mercedes", "cat": "drivers"},
    {"id": "isack_hadjar", "name": "Isack Hadjar", "team": "red_bull_racing", "cat": "drivers"},
    {"id": "kimi_antonelli", "name": "Kimi Antonelli", "team": "mercedes", "cat": "drivers"},
    {"id": "lance_stroll", "name": "Lance Stroll", "team": "aston_martin", "cat": "drivers"},
    {"id": "lando_norris", "name": "Lando Norris", "team": "mclaren", "cat": "drivers"},
    {"id": "lewis_hamilton", "name": "Lewis Hamilton", "team": "ferrari", "cat": "drivers"},
    {"id": "liam_lawson", "name": "Liam Lawson", "team": "racing_bulls", "cat": "drivers"},
    {"id": "max_verstappen", "name": "Max Verstappen", "team": "red_bull_racing", "cat": "drivers"},
    {"id": "nico_hulkenberg", "name": "Nico Hülkenberg", "team": "audi", "cat": "drivers"},
    {"id": "oliver_bearman", "name": "Oliver Bearman", "team": "haas", "cat": "drivers"},
    {"id": "oscar_piastri", "name": "Oscar Piastri", "team": "mclaren", "cat": "drivers"},
    {"id": "pierre_gasly", "name": "Pierre Gasly", "team": "alpine", "cat": "drivers"},
    {"id": "sergio_perez", "name": "Sergio Pérez", "team": "cadillac", "cat": "drivers"},
    {"id": "valtteri_bottas", "name": "Valtteri Bottas", "team": "cadillac", "cat": "drivers"},
    # Principals (11)
    {"id": "andrea_stella", "name": "Andrea Stella", "team": "mclaren", "cat": "principals"},
    {"id": "andy_cowell", "name": "Andy Cowell", "team": "aston_martin", "cat": "principals"},
    {"id": "ayao_komatsu", "name": "Ayao Komatsu", "team": "haas", "cat": "principals"},
    {"id": "christian_horner", "name": "Christian Horner", "team": "red_bull_racing", "cat": "principals"},
    {"id": "fred_vasseur", "name": "Fred Vasseur", "team": "ferrari", "cat": "principals"},
    {"id": "graeme_lowdon", "name": "Graeme Lowdon", "team": "cadillac", "cat": "principals"},
    {"id": "james_vowles", "name": "James Vowles", "team": "williams", "cat": "principals"},
    {"id": "jonathan_wheatley", "name": "Jonathan Wheatley", "team": "audi", "cat": "principals"},
    {"id": "laurent_mekies", "name": "Laurent Mekies", "team": "racing_bulls", "cat": "principals"},
    {"id": "oliver_oakes", "name": "Oliver Oakes", "team": "alpine", "cat": "principals"},
    {"id": "toto_wolff", "name": "Toto Wolff", "team": "mercedes", "cat": "principals"},
    # Pundits (9)
    {"id": "david_croft", "name": "David Croft", "team": None, "cat": "pundits"},
    {"id": "jenson_button", "name": "Jenson Button", "team": None, "cat": "pundits"},
    {"id": "karun_chandhok", "name": "Karun Chandhok", "team": None, "cat": "pundits"},
    {"id": "martin_brundle", "name": "Martin Brundle", "team": None, "cat": "pundits"},
    {"id": "natalie_pinkham", "name": "Natalie Pinkham", "team": None, "cat": "pundits"},
    {"id": "nico_rosberg", "name": "Nico Rosberg", "team": None, "cat": "pundits"},
    {"id": "simon_lazenby", "name": "Simon Lazenby", "team": None, "cat": "pundits"},
    {"id": "stefano_domenicali", "name": "Stefano Domenicali", "team": None, "cat": "pundits"},
    {"id": "ted_kravitz", "name": "Ted Kravitz", "team": None, "cat": "pundits"},
]

# DB name → our character id (for characters with different DB names)
DB_NAME_MAP = {
    "andrea_kimi_antonelli": "kimi_antonelli",
    "nico_hulkenberg": "nico_hulkenberg",  # DB has umlaut in display but same slug
}

# Characters that should be deactivated (no longer in 2026 grid)
DEACTIVATE = [
    "jack_doohan",
    "yuki_tsunoda",
    "mike_krack",
    "mattia_binotto",
    "michael_andretti",
    "alessandro_alunni_bravi",
    "adrian_newey",
    "alan_permane",
    "flavio_briatore",
]


async def sync():
    engine = create_async_engine(DATABASE_URL)
    our_ids = {c["id"] for c in CHARACTERS}

    async with engine.begin() as conn:
        # --- 1. Deactivate old characters ---
        for name in DEACTIVATE:
            await conn.execute(
                text("UPDATE characters SET is_active = false WHERE name = :name AND is_active = true"),
                {"name": name},
            )
            print(f"  Deactivated: {name}")

        # --- 2. Handle andrea_kimi_antonelli → kimi_antonelli rename ---
        result = await conn.execute(
            text("SELECT id FROM characters WHERE name = 'andrea_kimi_antonelli'")
        )
        old_kimi = result.scalar_one_or_none()
        if old_kimi:
            await conn.execute(
                text("""
                    UPDATE characters
                    SET name = 'kimi_antonelli', display_name = 'Kimi Antonelli'
                    WHERE id = :id
                """),
                {"id": old_kimi},
            )
            print(f"  Renamed: andrea_kimi_antonelli → kimi_antonelli (id={old_kimi})")

        # --- 3. Upsert all 42 characters ---
        for char in CHARACTERS:
            char_id = char["id"]
            display = char["name"]
            team_display = TEAM_DISPLAY.get(char["team"]) if char["team"] else None
            type_id = TYPE_IDS[char["cat"]]
            image_path = MINIO_IMAGE_PATH.format(char_id=char_id)

            # Check if exists
            result = await conn.execute(
                text("SELECT id FROM characters WHERE name = :name"),
                {"name": char_id},
            )
            existing_id = result.scalar_one_or_none()

            if existing_id:
                # Update existing
                await conn.execute(
                    text("""
                        UPDATE characters SET
                            display_name = :display,
                            team = :team,
                            character_type_id = :type_id,
                            primary_image_path = :image_path,
                            is_active = true
                        WHERE id = :id
                    """),
                    {
                        "display": display,
                        "team": team_display,
                        "type_id": type_id,
                        "image_path": image_path,
                        "id": existing_id,
                    },
                )
                print(f"  Updated: {char_id} (id={existing_id}) team={team_display} img={image_path}")
            else:
                # Insert new
                await conn.execute(
                    text("""
                        INSERT INTO characters (name, display_name, team, character_type_id, primary_image_path, is_active)
                        VALUES (:name, :display, :team, :type_id, :image_path, true)
                    """),
                    {
                        "name": char_id,
                        "display": display,
                        "team": team_display,
                        "type_id": type_id,
                        "image_path": image_path,
                    },
                )
                print(f"  CREATED: {char_id} team={team_display} img={image_path}")

        # --- 4. Verify final state ---
        result = await conn.execute(
            text("SELECT name, display_name, team, is_active, primary_image_path FROM characters WHERE is_active = true ORDER BY name")
        )
        active = result.fetchall()
        print(f"\n{'='*60}")
        print(f"ACTIVE CHARACTERS: {len(active)}")
        print(f"{'='*60}")
        for r in active:
            print(f"  {r[0]:30s} {r[1]:25s} team={str(r[2] or ''):20s} img={'✓' if r[4] else '✗'}")

    await engine.dispose()
    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(sync())
