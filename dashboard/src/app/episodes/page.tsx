"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, Episode, EpisodeStatus } from "@/lib/api";
import { Header } from "@/components/layout/Header";
import { Button, LoadingPage } from "@/components/ui";
import { EpisodeCard } from "@/components/episodes/EpisodeCard";

const statusFilters: { label: string; value: EpisodeStatus | "all" }[] = [
  { label: "All", value: "all" },
  { label: "Generating", value: "generating" },
  { label: "Published", value: "published" },
  { label: "Failed", value: "failed" },
  { label: "Pending", value: "pending" },
];

export default function EpisodesPage() {
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<EpisodeStatus | "all">("all");

  useEffect(() => {
    async function fetchEpisodes() {
      try {
        setLoading(true);
        const data = await api.episodes.list({
          status: filter === "all" ? undefined : filter,
          limit: 50,
        });
        setEpisodes(data);
      } catch (err) {
        console.error("Failed to fetch episodes:", err);
        setError(err instanceof Error ? err.message : "Failed to load episodes");
      } finally {
        setLoading(false);
      }
    }

    fetchEpisodes();
  }, [filter]);

  return (
    <div className="space-y-8">
      <Header
        title="Episodes"
        subtitle="Manage your generated F1 commentary videos"
        actions={
          <Link href="/episodes/new">
            <Button>
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              New Episode
            </Button>
          </Link>
        }
      />

      {/* Filters */}
      <div className="flex flex-wrap gap-2">
        {statusFilters.map((status) => (
          <button
            key={status.value}
            onClick={() => setFilter(status.value)}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition-all ${
              filter === status.value
                ? "bg-neon-cyan text-deep-space"
                : "bg-midnight/50 text-white/70 hover:bg-midnight hover:text-white"
            }`}
          >
            {status.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-4">
          <p className="text-racing-red">{error}</p>
        </div>
      )}

      {loading ? (
        <LoadingPage text="Loading episodes..." />
      ) : episodes.length === 0 ? (
        <div className="rounded-xl border border-white/10 bg-midnight/50 p-12 text-center">
          <svg className="mx-auto h-12 w-12 text-white/20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 4v16M17 4v16M3 8h4m10 0h4M3 12h18M3 16h4m10 0h4M4 20h16a1 1 0 001-1V5a1 1 0 00-1-1H4a1 1 0 00-1 1v14a1 1 0 001 1z" />
          </svg>
          <h3 className="mt-4 text-lg font-medium text-white">
            {filter === "all" ? "No episodes yet" : `No ${filter} episodes`}
          </h3>
          <p className="mt-2 text-white/60">
            {filter === "all"
              ? "Create your first episode to get started"
              : "Try changing the filter"}
          </p>
          {filter === "all" && (
            <Link href="/episodes/new" className="mt-4 inline-block">
              <Button>Create Episode</Button>
            </Link>
          )}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {episodes.map((episode) => (
            <EpisodeCard key={episode.id} episode={episode} />
          ))}
        </div>
      )}
    </div>
  );
}
