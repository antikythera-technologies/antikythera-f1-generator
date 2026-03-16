"""Race results scraper using OpenF1 API.

Fetches real race results and stores them in the database for accurate
script generation. Supports race, sprint, and qualifying sessions.
"""

import logging
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.race import Race
from app.models.race_result import (
    RaceResult, RaceIncident, RaceSessionSummary, SessionType,
)

logger = logging.getLogger(__name__)

OPENF1_BASE = "https://api.openf1.org/v1"


class RaceResultsScraper:
    """Fetch and store race results from OpenF1 API."""

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30)

    async def close(self):
        await self.client.aclose()

    async def fetch_and_store_results(
        self,
        db: AsyncSession,
        race: Race,
        session_type: str = "race",
    ) -> int:
        """Fetch results for a race session and store in DB.

        Args:
            db: Database session
            race: Race model instance
            session_type: "race", "sprint", or "qualifying"

        Returns:
            Number of results stored
        """
        # Map our session type to OpenF1 session type
        openf1_session_map = {
            "race": "Race",
            "sprint": "Sprint",
            "qualifying": "Qualifying",
            "sprint_qualifying": "Sprint Qualifying",
        }
        openf1_type = openf1_session_map.get(session_type, "Race")

        # Find the session on OpenF1
        session_key = await self._find_session(race, openf1_type)
        if not session_key:
            logger.warning(
                f"No OpenF1 session found for {race.race_name} {session_type}"
            )
            return 0

        logger.info(
            f"Fetching {session_type} results for {race.race_name} "
            f"(session_key={session_key})"
        )

        # Fetch drivers and positions
        drivers = await self._fetch_drivers(session_key)
        positions = await self._fetch_final_positions(session_key)

        if not positions:
            logger.warning(f"No position data for session {session_key}")
            return 0

        # Map SessionType enum
        st_enum = SessionType(session_type)

        # Clear existing results for this race+session
        await db.execute(
            delete(RaceResult).where(
                RaceResult.race_id == race.id,
                RaceResult.session_type == st_enum,
            )
        )

        # Store results
        count = 0
        for pos_data in positions:
            driver_num = pos_data["driver_number"]
            driver = drivers.get(driver_num, {})

            # Slugify driver name for matching with our characters DB
            full_name = driver.get("full_name", f"Driver #{driver_num}")
            slug = full_name.lower().replace(" ", "_")

            result = RaceResult(
                race_id=race.id,
                session_type=st_enum,
                position=pos_data["position"],
                driver_name=slug,
                driver_display_name=full_name,
                driver_number=driver_num,
                team=driver.get("team_name"),
                status="Finished",  # OpenF1 position endpoint only shows finishers
                is_dnf=False,
            )
            db.add(result)
            count += 1

        # Store session summary
        await db.execute(
            delete(RaceSessionSummary).where(
                RaceSessionSummary.race_id == race.id,
                RaceSessionSummary.session_type == st_enum,
            )
        )

        if count >= 3:
            def _driver_name(pos_idx):
                if pos_idx >= len(positions):
                    return None
                dn = positions[pos_idx]["driver_number"]
                d = drivers.get(dn, {})
                return d.get("full_name", f"Driver #{dn}")

            summary = RaceSessionSummary(
                race_id=race.id,
                session_type=st_enum,
                winner=_driver_name(0),
                second=_driver_name(1),
                third=_driver_name(2),
            )
            db.add(summary)

        await db.flush()
        logger.info(
            f"Stored {count} results for {race.race_name} {session_type}"
        )
        return count

    async def fetch_all_sessions(
        self, db: AsyncSession, race: Race
    ) -> dict[str, int]:
        """Fetch results for all sessions of a race weekend."""
        results = {}

        # Always fetch race results
        results["race"] = await self.fetch_and_store_results(
            db, race, "race"
        )

        # Fetch qualifying
        results["qualifying"] = await self.fetch_and_store_results(
            db, race, "qualifying"
        )

        # Fetch sprint if it's a sprint weekend
        if race.is_sprint_weekend:
            results["sprint"] = await self.fetch_and_store_results(
                db, race, "sprint"
            )

        return results

    async def _find_session(
        self, race: Race, session_type: str
    ) -> Optional[int]:
        """Find OpenF1 session key for a race."""
        params = {
            "year": race.season,
            "session_type": session_type,
        }

        # Match by location from circuit name
        circuit_keywords = {
            "Albert Park": "Melbourne",
            "Shanghai": "Shanghai",
            "Suzuka": "Suzuka",
            "Bahrain": "Sakhir",
            "Jeddah": "Jeddah",
            "Miami": "Miami",
            "Imola": "Imola",
            "Monaco": "Monaco",
            "Barcelona": "Barcelona",
            "Montreal": "Montréal",
            "Silverstone": "Silverstone",
            "Spielberg": "Spielberg",
            "Hungaroring": "Budapest",
            "Spa": "Spa-Francorchamps",
            "Zandvoort": "Zandvoort",
            "Monza": "Monza",
            "Baku": "Baku",
            "Marina Bay": "Singapore",
            "Suzuka": "Suzuka",
            "Lusail": "Lusail",
            "Austin": "Austin",
            "Mexico": "Mexico City",
            "Interlagos": "São Paulo",
            "Las Vegas": "Las Vegas",
            "Yas Marina": "Yas Island",
        }

        # Try to match circuit
        location = None
        for keyword, openf1_loc in circuit_keywords.items():
            if keyword.lower() in (race.circuit_name or "").lower():
                location = openf1_loc
                break

        if not location:
            # Fallback: use country
            location = race.country

        try:
            resp = await self.client.get(
                f"{OPENF1_BASE}/sessions",
                params={**params, "location": location},
            )
            resp.raise_for_status()
            sessions = resp.json()

            if sessions:
                return sessions[0]["session_key"]

            # Fallback: try without location filter
            resp = await self.client.get(
                f"{OPENF1_BASE}/sessions",
                params=params,
            )
            resp.raise_for_status()
            all_sessions = resp.json()

            # Match by round number (meeting_key order)
            for s in all_sessions:
                if s.get("circuit_short_name", "").lower() in (
                    race.circuit_name or ""
                ).lower():
                    return s["session_key"]

        except Exception as e:
            logger.error(f"OpenF1 session lookup failed: {e}")

        return None

    async def _fetch_drivers(self, session_key: int) -> dict[int, dict]:
        """Fetch driver info for a session. Returns {driver_number: info}."""
        try:
            resp = await self.client.get(
                f"{OPENF1_BASE}/drivers",
                params={"session_key": session_key},
            )
            resp.raise_for_status()
            drivers = resp.json()

            result = {}
            for d in drivers:
                dn = d["driver_number"]
                if dn not in result:
                    result[dn] = d
            return result

        except Exception as e:
            logger.error(f"OpenF1 drivers fetch failed: {e}")
            return {}

    async def _fetch_final_positions(
        self, session_key: int
    ) -> list[dict]:
        """Fetch final race positions. Returns sorted list."""
        try:
            resp = await self.client.get(
                f"{OPENF1_BASE}/position",
                params={"session_key": session_key},
            )
            resp.raise_for_status()
            data = resp.json()

            if not data:
                return []

            # Get the latest position entry for each driver
            latest: dict[int, dict] = {}
            for d in data:
                dn = d["driver_number"]
                if dn not in latest or d["date"] > latest[dn]["date"]:
                    latest[dn] = d

            # Sort by position
            return sorted(latest.values(), key=lambda x: x["position"])

        except Exception as e:
            logger.error(f"OpenF1 positions fetch failed: {e}")
            return []
