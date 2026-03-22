#!/usr/bin/env python3
"""
Seed the teams table with all 11 F1 teams for the 2026 season,
then backfill characters.team_id from their existing team text field.

Usage:
    cd /path/to/antikythera-f1-generator
    python scripts/seed_teams_2026.py
"""

import asyncio
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path hack so we can import from backend/app
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import settings


# ---------------------------------------------------------------------------
# 2026 F1 Team data
# ---------------------------------------------------------------------------
SEASON = 2026

TEAMS = [
    # ── Red Bull Racing ──────────────────────────────────────────────────
    {
        "name": "Oracle Red Bull Racing",
        "short_name": "red_bull_racing",
        "livery_description": (
            "Gloss dark navy blue bodywork with bright Ford blue accents. "
            "White outlined Red Bull logos on engine cover and nose. "
            "Oracle branding on sidepods. Yellow trim on rear wing endplates. "
            "Brighter blue tone than previous seasons, reflecting the Ford partnership."
        ),
        "car_description": (
            "dark navy blue and yellow Red Bull RB26 with Oracle branding "
            "and Ford blue accents"
        ),
        "overalls_description": (
            "dark navy blue race suit with Oracle and Red Bull logos, "
            "white and yellow accents, Ford branding on sleeves"
        ),
        "primary_colour": "#1E2A5E",
        "secondary_colour": "#FFD700",
        "accent_colour": "#003DA5",
        "principal_name": "Laurent Mekies",
        "engine_supplier": "Red Bull Powertrains / Ford",
        "constructor_name": "Red Bull Racing",
        "headquarters": "Milton Keynes, UK",
    },
    # ── Ferrari ──────────────────────────────────────────────────────────
    {
        "name": "Scuderia Ferrari HP",
        "short_name": "ferrari",
        "livery_description": (
            "Iconic rosso corsa red with gloss finish. White accents around "
            "cockpit and airbox, inspired by Niki Lauda's 1975 312 T. "
            "HP branding on rear wing and sidepods. Shell and Ray-Ban sponsor "
            "logos. Clean, classic design paying homage to the 2000s dominance era."
        ),
        "car_description": (
            "glossy rosso corsa red Ferrari SF-26 with white cockpit accents "
            "and HP branding"
        ),
        "overalls_description": (
            "bright red race suit with Scuderia Ferrari shield, "
            "HP and Shell logos, white collar and sleeve trim"
        ),
        "primary_colour": "#DC0000",
        "secondary_colour": "#FFFFFF",
        "accent_colour": "#FFF200",
        "principal_name": "Fred Vasseur",
        "engine_supplier": "Ferrari",
        "constructor_name": "Scuderia Ferrari",
        "headquarters": "Maranello, Italy",
    },
    # ── McLaren ──────────────────────────────────────────────────────────
    {
        "name": "McLaren Formula 1 Team",
        "short_name": "mclaren",
        "livery_description": (
            "Bold papaya orange front and flanks transitioning to black rear. "
            "Chrome McLaren speedmark on engine cover. The MCL40 continues the "
            "iconic two-tone scheme from the Constructors' Championship-winning "
            "seasons. OKX and Google Chrome sponsor logos."
        ),
        "car_description": (
            "papaya orange and black McLaren MCL40 with chrome speedmark "
            "and OKX branding"
        ),
        "overalls_description": (
            "papaya orange race suit with black panels, McLaren speedmark "
            "on chest, OKX and Google Chrome logos"
        ),
        "primary_colour": "#FF8000",
        "secondary_colour": "#000000",
        "accent_colour": "#47C7FC",
        "principal_name": "Andrea Stella",
        "engine_supplier": "Mercedes",
        "constructor_name": "McLaren Racing",
        "headquarters": "Woking, UK",
    },
    # ── Mercedes ─────────────────────────────────────────────────────────
    {
        "name": "Mercedes-AMG PETRONAS F1 Team",
        "short_name": "mercedes",
        "livery_description": (
            "Silver-to-black gradient bodywork with the signature Petronas teal "
            "green streaks along sidepods and rear wing. White accents on "
            "the W17's flanks. Three-pointed star on the nose. Classic silver "
            "arrows heritage with modern PETRONAS colour integration."
        ),
        "car_description": (
            "silver and black gradient Mercedes W17 with Petronas teal green "
            "accents and three-pointed star"
        ),
        "overalls_description": (
            "black race suit with silver Mercedes and Petronas branding, "
            "teal green accents on shoulders and collar"
        ),
        "primary_colour": "#00D2BE",
        "secondary_colour": "#C0C0C0",
        "accent_colour": "#000000",
        "principal_name": "Toto Wolff",
        "engine_supplier": "Mercedes",
        "constructor_name": "Mercedes-AMG Petronas",
        "headquarters": "Brackley, UK",
    },
    # ── Aston Martin ─────────────────────────────────────────────────────
    {
        "name": "Aston Martin Aramco F1 Team",
        "short_name": "aston_martin",
        "livery_description": (
            "Matte British Racing Green covering the entire AMR26. "
            "Aramco branding along sidepods. Lime green accents on rear wing "
            "endplates and halo. First car designed under Adrian Newey at "
            "the team. Honda power unit branding on engine cover."
        ),
        "car_description": (
            "matte British Racing Green Aston Martin AMR26 with Aramco "
            "branding and lime green accents"
        ),
        "overalls_description": (
            "dark British Racing Green race suit with Aston Martin wings "
            "badge, Aramco and Cognizant logos, lime green piping"
        ),
        "primary_colour": "#006F62",
        "secondary_colour": "#CEDC00",
        "accent_colour": "#FFFFFF",
        "principal_name": "Adrian Newey",
        "engine_supplier": "Honda",
        "constructor_name": "Aston Martin Performance Technologies",
        "headquarters": "Silverstone, UK",
    },
    # ── Alpine ───────────────────────────────────────────────────────────
    {
        "name": "BWT Alpine F1 Team",
        "short_name": "alpine",
        "livery_description": (
            "Blue and pink colour scheme on the A526. BWT pink prominent on "
            "rear wing and sidepod tops. Alpine blue base colour across the "
            "chassis. Now Mercedes-powered after dropping Renault engines. "
            "Clean French tricolour accent on nose."
        ),
        "car_description": (
            "blue and pink Alpine A526 with BWT branding and Mercedes power"
        ),
        "overalls_description": (
            "blue race suit with BWT pink shoulder panels, Alpine logo "
            "on chest, French flag detail on collar"
        ),
        "primary_colour": "#0090FF",
        "secondary_colour": "#FF69B4",
        "accent_colour": "#FFFFFF",
        "principal_name": "Flavio Briatore",
        "engine_supplier": "Mercedes",
        "constructor_name": "Alpine Racing",
        "headquarters": "Enstone, UK",
    },
    # ── Williams ─────────────────────────────────────────────────────────
    {
        "name": "Williams Racing",
        "short_name": "williams",
        "livery_description": (
            "Predominantly dark navy blue bodywork with white engine cover "
            "and rear wing. Barclays lighter blue on the sidepods as new "
            "title sponsor. Duracell yellow accents. Heritage-inspired "
            "design echoing the classic Williams blue-and-white identity."
        ),
        "car_description": (
            "dark navy blue and white Williams FW48 with Barclays blue "
            "sidepods and Duracell yellow accents"
        ),
        "overalls_description": (
            "dark navy blue race suit with white panels, Williams logo "
            "on chest, Barclays and Duracell branding"
        ),
        "primary_colour": "#005AFF",
        "secondary_colour": "#FFFFFF",
        "accent_colour": "#00A3E0",
        "principal_name": "James Vowles",
        "engine_supplier": "Mercedes",
        "constructor_name": "Williams Grand Prix Engineering",
        "headquarters": "Grove, UK",
    },
    # ── Racing Bulls ─────────────────────────────────────────────────────
    {
        "name": "Visa Cash App Racing Bulls",
        "short_name": "racing_bulls",
        "livery_description": (
            "Predominantly white livery with black and blue accents. Blue "
            "streaks on engine cover and sidepod as a nod to the Ford power "
            "unit partnership. Visa and Cash App branding. Clean, modern "
            "design with the junior Red Bull team identity."
        ),
        "car_description": (
            "white Racing Bulls VCARB 02 with blue and black accents, "
            "Visa Cash App branding"
        ),
        "overalls_description": (
            "white race suit with dark blue shoulders and sleeves, "
            "Visa Cash App logos, blue racing bull motif on back"
        ),
        "primary_colour": "#FFFFFF",
        "secondary_colour": "#1E3A6D",
        "accent_colour": "#2B4EFF",
        "principal_name": "Alan Permane",
        "engine_supplier": "Red Bull Powertrains / Ford",
        "constructor_name": "Racing Bulls",
        "headquarters": "Faenza, Italy",
    },
    # ── Haas ─────────────────────────────────────────────────────────────
    {
        "name": "MoneyGram Haas F1 Team",
        "short_name": "haas",
        "livery_description": (
            "Black, white and red colour palette. Toyota Gazoo Racing "
            "branding reflects the new technical partnership. MoneyGram "
            "title sponsor in white on dark bodywork. Red accents on "
            "rear wing and halo. American team with Ferrari power."
        ),
        "car_description": (
            "black and white Haas VF-26 with red accents and Toyota "
            "Gazoo Racing branding"
        ),
        "overalls_description": (
            "black race suit with white chest panel, MoneyGram logo, "
            "red trim on collar and cuffs, Toyota Gazoo Racing badges"
        ),
        "primary_colour": "#FFFFFF",
        "secondary_colour": "#000000",
        "accent_colour": "#E10600",
        "principal_name": "Ayao Komatsu",
        "engine_supplier": "Ferrari",
        "constructor_name": "Haas F1 Team",
        "headquarters": "Kannapolis, USA",
    },
    # ── Audi (formerly Sauber) ───────────────────────────────────────────
    {
        "name": "Audi Revolut F1 Team",
        "short_name": "audi",
        "livery_description": (
            "Silver bodywork with orange accents at the rear. Prominent "
            "Audi four rings on the rear wing. Revolut title sponsor "
            "branding on sidepods. Clean, minimalist German design "
            "for the brand's debut as a works F1 team."
        ),
        "car_description": (
            "silver Audi F1 car with orange rear accents and prominent "
            "four rings on rear wing"
        ),
        "overalls_description": (
            "silver-grey race suit with Audi four rings on chest, "
            "orange accents on shoulders, Revolut branding"
        ),
        "primary_colour": "#C0C0C0",
        "secondary_colour": "#FF6600",
        "accent_colour": "#000000",
        "principal_name": "Jonathan Wheatley",
        "engine_supplier": "Audi",
        "constructor_name": "Sauber Motorsport",
        "headquarters": "Hinwil, Switzerland",
    },
    # ── Cadillac (new 11th team) ─────────────────────────────────────────
    {
        "name": "Cadillac Formula 1 Team",
        "short_name": "cadillac",
        "livery_description": (
            "Striking asymmetric dual-colour livery: black on the right "
            "side and white on the left. Cadillac crest on the nose. "
            "TWG AI branding on sidepods. The split design is a deliberate "
            "yin-and-yang philosophy — black for grit and performance, "
            "white for American racing heritage and aspiration."
        ),
        "car_description": (
            "split black-and-white Cadillac F1 car with Cadillac crest "
            "on nose and TWG AI branding"
        ),
        "overalls_description": (
            "black race suit with white side panels, Cadillac crest "
            "on chest, TWG AI and American flag details"
        ),
        "primary_colour": "#000000",
        "secondary_colour": "#FFFFFF",
        "accent_colour": "#C4A747",
        "principal_name": "Graeme Lowdon",
        "engine_supplier": "Ferrari",
        "constructor_name": "TWG Cadillac Formula 1 Team",
        "headquarters": "Silverstone, UK",
    },
]

# ---------------------------------------------------------------------------
# Mapping: characters.team display text → teams.short_name
#
# The sync_character_db.py script writes DISPLAY names into characters.team
# (e.g. "Red Bull Racing", "Ferrari"). This map lets us look up the
# corresponding teams.short_name for backfill.
# ---------------------------------------------------------------------------
TEAM_DISPLAY_TO_SHORT = {
    "Red Bull Racing": "red_bull_racing",
    "Racing Bulls": "racing_bulls",
    "McLaren": "mclaren",
    "Ferrari": "ferrari",
    "Mercedes": "mercedes",
    "Williams": "williams",
    "Haas": "haas",
    "Alpine": "alpine",
    "Aston Martin": "aston_martin",
    "Audi": "audi",
    "Cadillac": "cadillac",
    # Legacy values that might exist in the DB
    "Sauber": "audi",
    "Kick Sauber": "audi",
    "RB": "racing_bulls",
    "AlphaTauri": "racing_bulls",
}


async def main() -> None:
    print(f"{'='*60}")
    print(f"  F1 2026 Team Seeder")
    print(f"{'='*60}")
    print(f"  Database: {settings.database_url[:40]}...")
    print()

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession)

    async with session_factory() as session:
        async with session.begin():
            # ── Step 1: Seed teams ────────────────────────────────────
            print("Step 1: Seeding teams table...")
            print("-" * 60)

            inserted = 0
            skipped = 0

            for team_data in TEAMS:
                # Check if team already exists for this season
                result = await session.execute(
                    text(
                        "SELECT id FROM teams "
                        "WHERE short_name = :short_name AND season = :season"
                    ),
                    {"short_name": team_data["short_name"], "season": SEASON},
                )
                existing_id = result.scalar_one_or_none()

                if existing_id:
                    print(f"  SKIP  {team_data['short_name']:20s} (already exists, id={existing_id})")
                    skipped += 1
                    continue

                await session.execute(
                    text("""
                        INSERT INTO teams (
                            name, short_name, season,
                            livery_description, car_description, overalls_description,
                            primary_colour, secondary_colour, accent_colour,
                            principal_name, engine_supplier, constructor_name,
                            headquarters, is_active
                        ) VALUES (
                            :name, :short_name, :season,
                            :livery_description, :car_description, :overalls_description,
                            :primary_colour, :secondary_colour, :accent_colour,
                            :principal_name, :engine_supplier, :constructor_name,
                            :headquarters, true
                        )
                    """),
                    {**team_data, "season": SEASON},
                )
                print(f"  ADD   {team_data['short_name']:20s} - {team_data['name']}")
                inserted += 1

            print()
            print(f"  Inserted: {inserted}  |  Skipped: {skipped}")
            print()

            # ── Step 2: Backfill characters.team_id ──────────────────
            print("Step 2: Backfilling characters.team_id...")
            print("-" * 60)

            # Build lookup: short_name → team id
            result = await session.execute(
                text("SELECT id, short_name FROM teams WHERE season = :season"),
                {"season": SEASON},
            )
            short_name_to_id = {row[1]: row[0] for row in result.fetchall()}

            # Get all characters with a team text but no team_id
            result = await session.execute(
                text(
                    "SELECT id, name, team FROM characters "
                    "WHERE team IS NOT NULL AND team != '' AND team_id IS NULL"
                )
            )
            characters = result.fetchall()

            if not characters:
                print("  No characters need backfill (all already have team_id or no team).")
            else:
                updated = 0
                failed = 0
                for char_id, char_name, team_text in characters:
                    short_name = TEAM_DISPLAY_TO_SHORT.get(team_text)
                    if short_name and short_name in short_name_to_id:
                        team_id = short_name_to_id[short_name]
                        await session.execute(
                            text("UPDATE characters SET team_id = :team_id WHERE id = :id"),
                            {"team_id": team_id, "id": char_id},
                        )
                        print(f"  SET   {char_name:30s} team=\"{team_text}\" -> team_id={team_id}")
                        updated += 1
                    else:
                        print(f"  WARN  {char_name:30s} team=\"{team_text}\" - no matching team found")
                        failed += 1

                print()
                print(f"  Updated: {updated}  |  Unmatched: {failed}")

            print()

        # Commit happens automatically when the `begin()` context exits

    # ── Step 3: Verify ───────────────────────────────────────────────
    async with session_factory() as session:
        result = await session.execute(
            text(
                "SELECT t.short_name, t.name, t.primary_colour, "
                "       COUNT(c.id) AS char_count "
                "FROM teams t "
                "LEFT JOIN characters c ON c.team_id = t.id "
                "WHERE t.season = :season "
                "GROUP BY t.id "
                "ORDER BY t.short_name"
            ),
            {"season": SEASON},
        )
        rows = result.fetchall()

        print("Step 3: Verification")
        print("-" * 60)
        print(f"  {'Short Name':20s} {'Full Name':35s} {'Colour':8s} {'Chars':5s}")
        print(f"  {'-'*20} {'-'*35} {'-'*8} {'-'*5}")
        for short, full, colour, count in rows:
            print(f"  {short:20s} {full:35s} {colour or '':8s} {count:5d}")

        print()
        print(f"  Total teams: {len(rows)}")

    await engine.dispose()
    print()
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
