"use client";

import { useEffect, useState } from "react";
import { api, Team } from "@/lib/api";
import { Header } from "@/components/layout/Header";
import { LoadingPage } from "@/components/ui";
import { TeamCard } from "@/components/teams/TeamCard";

export default function TeamsPage() {
  const [teams, setTeams] = useState<Team[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchTeams() {
      try {
        setLoading(true);
        const data = await api.teams.list({ active_only: true });
        setTeams(data);
      } catch (err) {
        console.error("Failed to fetch teams:", err);
        setError(err instanceof Error ? err.message : "Failed to load teams");
      } finally {
        setLoading(false);
      }
    }

    fetchTeams();
  }, []);

  return (
    <div className="space-y-8">
      <Header
        title="Teams"
        subtitle="F1 constructor teams and livery configurations"
      />

      {error && (
        <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-4">
          <p className="text-racing-red">{error}</p>
        </div>
      )}

      {loading ? (
        <LoadingPage text="Loading teams..." />
      ) : teams.length === 0 ? (
        <div className="rounded-xl border border-white/10 bg-midnight/50 p-12 text-center">
          <svg className="mx-auto h-12 w-12 text-white/20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
          </svg>
          <h3 className="mt-4 text-lg font-medium text-white">No teams found</h3>
          <p className="mt-2 text-white/60">
            Teams will appear here once seeded into the database
          </p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {teams.map((team) => (
            <TeamCard key={team.id} team={team} />
          ))}
        </div>
      )}
    </div>
  );
}
