"""Race results scraper using OpenF1 API.

Fetches real race results and stores them in the database for accurate
script generation. Supports race, sprint, and qualifying sessions.
"""

import logging
from datetime import datetime
from typing import Optional

import asyncio
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
    # OpenF1 free tier: 3 req/sec, 30 req/min
    _REQUEST_DELAY = 1.0  # seconds between requests
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
        # Find the session on OpenF1 (uses session_name matching internally)
        session_key = await self._find_session(race, session_type)
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
        """Fetch results for all sessions of a race weekend.

        Includes rate-limiting delays between API calls to respect
        OpenF1's free tier (3 req/sec, 30 req/min).
        """
        results = {}

        # Cache the meeting key to avoid redundant lookups
        self._cached_meeting_key = await self._find_meeting(race)
        await asyncio.sleep(self._REQUEST_DELAY)

        # Always fetch race + qualifying
        results["race"] = await self.fetch_and_store_results(db, race, "race")
        await asyncio.sleep(self._REQUEST_DELAY * 2)

        results["qualifying"] = await self.fetch_and_store_results(db, race, "qualifying")
        await asyncio.sleep(self._REQUEST_DELAY * 2)

        # Fetch sprint sessions if sprint weekend
        if race.is_sprint_weekend:
            results["sprint"] = await self.fetch_and_store_results(db, race, "sprint")
            await asyncio.sleep(self._REQUEST_DELAY * 2)

            results["sprint_qualifying"] = await self.fetch_and_store_results(db, race, "sprint_qualifying")

        self._cached_meeting_key = None
        return results

    async def _find_session(
        self, race: Race, session_type: str
    ) -> Optional[int]:
        """Find OpenF1 session key for a race.

        OpenF1 uses different naming than expected:
        - Sprint is session_type=Race, session_name=Sprint
        - Sprint Qualifying is session_type=Qualifying, session_name=Sprint Qualifying
        So we first find all sessions for the meeting, then match by name.
        """
        try:
            # Step 1: Find the meeting (use cache if available)
            meeting_key = getattr(self, '_cached_meeting_key', None) or await self._find_meeting(race)
            if not meeting_key:
                logger.warning(f"No OpenF1 meeting found for {race.race_name}")
                return None

            # Step 2: Get all sessions for this meeting
            resp = await self.client.get(
                f"{OPENF1_BASE}/sessions",
                params={"meeting_key": meeting_key},
            )
            resp.raise_for_status()
            sessions = resp.json()

            # Step 3: Match by session name
            session_name_map = {
                "race": "Race",
                "qualifying": "Qualifying",
                "sprint": "Sprint",
                "sprint_qualifying": "Sprint Qualifying",
                "fp1": "Practice 1",
                "fp2": "Practice 2",
                "fp3": "Practice 3",
            }
            target_name = session_name_map.get(session_type, session_type)

            for s in sessions:
                if s.get("session_name") == target_name:
                    logger.info(
                        f"Found session: {s['session_name']} "
                        f"(key={s['session_key']}) for {race.race_name}"
                    )
                    return s["session_key"]

            logger.warning(
                f"No '{target_name}' session in meeting {meeting_key} "
                f"for {race.race_name}. Available: "
                f"{[s['session_name'] for s in sessions]}"
            )
            return None

        except Exception as e:
            logger.error(f"OpenF1 session lookup failed: {e}")
            return None

    async def _find_meeting(self, race: Race) -> Optional[int]:
        """Find the OpenF1 meeting_key for a race."""
        try:
            resp = await self.client.get(
                f"{OPENF1_BASE}/meetings",
                params={"year": race.season},
            )
            resp.raise_for_status()
            meetings = resp.json()

            # Match by country or circuit name
            race_country = (race.country or "").lower()
            race_circuit = (race.circuit_name or "").lower()

            for m in meetings:
                loc = (m.get("location") or "").lower()
                country = (m.get("country_name") or "").lower()
                circuit = (m.get("circuit_short_name") or "").lower()
                name = (m.get("meeting_name") or "").lower()

                if (
                    race_country in country
                    or race_country in loc
                    or circuit in race_circuit
                    or race_circuit in circuit
                    or race_country in name
                ):
                    logger.info(
                        f"Matched meeting: {m['meeting_name']} "
                        f"(key={m['meeting_key']}) for {race.race_name}"
                    )
                    return m["meeting_key"]

            logger.warning(
                f"No meeting match for {race.race_name} ({race.country})"
            )
            return None

        except Exception as e:
            logger.error(f"OpenF1 meeting lookup failed: {e}")
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
