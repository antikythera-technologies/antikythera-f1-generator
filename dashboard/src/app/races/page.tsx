"use client";

import { useEffect, useState } from "react";
import { api, Race } from "@/lib/api";
import { formatDate, cn } from "@/lib/utils";
import { Header } from "@/components/layout/Header";
import { Button, LoadingPage, Card, CardContent } from "@/components/ui";

export default function RacesPage() {
  const [races, setRaces] = useState<Race[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchRaces = async () => {
    try {
      const data = await api.races.list({ season: 2026 });
      setRaces(data);
    } catch (err) {
      console.error("Failed to fetch races:", err);
      setError(err instanceof Error ? err.message : "Failed to load races");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRaces();
  }, []);

  const handleSync = async () => {
    setSyncing(true);
    try {
      await api.races.sync();
      await fetchRaces();
    } catch (err) {
      console.error("Sync failed:", err);
      setError(err instanceof Error ? err.message : "Failed to sync races");
    } finally {
      setSyncing(false);
    }
  };

  const today = new Date();
  const upcomingRaces = races.filter((r) => new Date(r.race_date) >= today);
  const pastRaces = races.filter((r) => new Date(r.race_date) < today);

  return (
    <div className="space-y-8">
      <Header
        title="Race Calendar"
        subtitle="2026 Formula 1 World Championship"
        actions={
          <Button variant="secondary" loading={syncing} onClick={handleSync}>
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Sync Calendar
          </Button>
        }
      />

      {error && (
        <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-4">
          <p className="text-racing-red">{error}</p>
        </div>
      )}

      {loading ? (
        <LoadingPage text="Loading races..." />
      ) : races.length === 0 ? (
        <div className="rounded-xl border border-white/10 bg-midnight/50 p-12 text-center">
          <svg className="mx-auto h-12 w-12 text-white/20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 21v-4m0 0V5a2 2 0 012-2h6.5l1 1H21l-3 6 3 6h-8.5l-1-1H5a2 2 0 00-2 2zm9-13.5V9" />
          </svg>
          <h3 className="mt-4 text-lg font-medium text-white">No races in calendar</h3>
          <p className="mt-2 text-white/60">Sync the F1 calendar to get started</p>
          <Button className="mt-4" onClick={handleSync} loading={syncing}>
            Sync Calendar
          </Button>
        </div>
      ) : (
        <div className="space-y-8">
          {/* Upcoming Races */}
          {upcomingRaces.length > 0 && (
            <section>
              <h2 className="mb-4 flex items-center gap-2 text-xl font-semibold text-white">
                <span className="h-2 w-2 rounded-full bg-success-green animate-pulse" />
                Upcoming Races ({upcomingRaces.length})
              </h2>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {upcomingRaces.map((race) => (
                  <RaceCard key={race.id} race={race} isUpcoming />
                ))}
              </div>
            </section>
          )}

          {/* Past Races */}
          {pastRaces.length > 0 && (
            <section>
              <h2 className="mb-4 text-xl font-semibold text-white">
                Past Races ({pastRaces.length})
              </h2>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {pastRaces.map((race) => (
                  <RaceCard key={race.id} race={race} />
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

interface RaceCardProps {
  race: Race;
  isUpcoming?: boolean;
}

function RaceCard({ race, isUpcoming = false }: RaceCardProps) {
  const raceDate = new Date(race.race_date);
  const daysUntil = Math.ceil((raceDate.getTime() - Date.now()) / (1000 * 60 * 60 * 24));

  return (
    <Card hover glow={isUpcoming ? "cyan" : null}>
      <CardContent className="space-y-4">
        <div className="flex items-start justify-between">
          <div>
            <div className={cn(
              "mb-2 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
              isUpcoming ? "bg-success-green/20 text-success-green" : "bg-white/10 text-white/50"
            )}>
              Round {race.round_number}
            </div>
            <h3 className="text-lg font-semibold text-white">{race.race_name}</h3>
            <p className="text-sm text-white/60">{race.circuit_name}</p>
          </div>
          {isUpcoming && daysUntil <= 7 && (
            <div className="rounded-lg bg-racing-red/20 px-2 py-1 text-xs font-medium text-racing-red">
              {daysUntil === 0 ? "Today!" : daysUntil === 1 ? "Tomorrow" : `${daysUntil} days`}
            </div>
          )}
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-sm">
            <svg className="h-4 w-4 text-white/40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            <span className="text-white/70">{race.country}</span>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <svg className="h-4 w-4 text-white/40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            <span className={isUpcoming ? "text-neon-cyan" : "text-white/70"}>
              {formatDate(race.race_date)}
            </span>
          </div>
        </div>

        {/* Session times */}
        {isUpcoming && (race.qualifying_datetime || race.race_datetime) && (
          <div className="border-t border-white/10 pt-4">
            <div className="grid grid-cols-2 gap-2 text-xs">
              {race.qualifying_datetime && (
                <div>
                  <p className="text-white/40">Qualifying</p>
                  <p className="text-white/70">{formatDate(race.qualifying_datetime, { dateStyle: undefined, timeStyle: "short" })}</p>
                </div>
              )}
              {race.race_datetime && (
                <div>
                  <p className="text-white/40">Race</p>
                  <p className="text-white/70">{formatDate(race.race_datetime, { dateStyle: undefined, timeStyle: "short" })}</p>
                </div>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
