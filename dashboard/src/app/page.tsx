"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, Episode, DashboardStats } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import { Header } from "@/components/layout/Header";
import { Button, StatsWidget, LoadingPage } from "@/components/ui";
import { EpisodeCard } from "@/components/episodes/EpisodeCard";

// Mock stats if API doesn't provide them
const defaultStats: DashboardStats = {
  total_episodes: 0,
  episodes_generating: 0,
  episodes_published: 0,
  episodes_failed: 0,
  total_characters: 0,
  upcoming_races: 0,
  total_cost_usd: 0,
};

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats>(defaultStats);
  const [recentEpisodes, setRecentEpisodes] = useState<Episode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      try {
        // Fetch episodes - the stats will be calculated from this
        const episodes = await api.episodes.list({ limit: 6 });
        setRecentEpisodes(episodes);

        // Calculate stats from episodes
        const generating = episodes.filter(e => 
          ["generating", "stitching", "uploading"].includes(e.status)
        ).length;
        const published = episodes.filter(e => e.status === "published").length;
        const failed = episodes.filter(e => e.status === "failed").length;
        const totalCost = episodes.reduce((sum, e) => sum + Number(e.total_cost_usd), 0);

        setStats({
          total_episodes: episodes.length,
          episodes_generating: generating,
          episodes_published: published,
          episodes_failed: failed,
          total_characters: 0, // We'd need to fetch this separately
          upcoming_races: 0,
          total_cost_usd: totalCost,
        });
      } catch (err) {
        console.error("Failed to fetch dashboard data:", err);
        setError(err instanceof Error ? err.message : "Failed to load dashboard");
      } finally {
        setLoading(false);
      }
    }

    fetchData();
  }, []);

  if (loading) {
    return <LoadingPage text="Loading dashboard..." />;
  }

  return (
    <div className="space-y-8">
      <Header
        title="Dashboard"
        subtitle="Monitor your F1 video generation pipeline"
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

      {error && (
        <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-4">
          <p className="text-racing-red">{error}</p>
          <p className="mt-1 text-sm text-white/60">Make sure the backend is running at {process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001"}</p>
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatsWidget
          title="Total Episodes"
          value={stats.total_episodes}
          subtitle="All time"
          color="cyan"
          icon={
            <svg className="h-6 w-6 text-neon-cyan" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 4v16M17 4v16M3 8h4m10 0h4M3 12h18M3 16h4m10 0h4M4 20h16a1 1 0 001-1V5a1 1 0 00-1-1H4a1 1 0 00-1 1v14a1 1 0 001 1z" />
            </svg>
          }
        />
        <StatsWidget
          title="Generating"
          value={stats.episodes_generating}
          subtitle="In progress"
          color="blue"
          icon={
            <svg className="h-6 w-6 text-electric-blue" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          }
        />
        <StatsWidget
          title="Published"
          value={stats.episodes_published}
          subtitle="On YouTube"
          color="green"
          icon={
            <svg className="h-6 w-6 text-success-green" fill="currentColor" viewBox="0 0 24 24">
              <path d="M19.615 3.184c-3.604-.246-11.631-.245-15.23 0-3.897.266-4.356 2.62-4.385 8.816.029 6.185.484 8.549 4.385 8.816 3.6.245 11.626.246 15.23 0 3.897-.266 4.356-2.62 4.385-8.816-.029-6.185-.484-8.549-4.385-8.816zm-10.615 12.816v-8l8 3.993-8 4.007z"/>
            </svg>
          }
        />
        <StatsWidget
          title="Total Cost"
          value={formatCurrency(stats.total_cost_usd)}
          subtitle="API usage"
          color="purple"
          icon={
            <svg className="h-6 w-6 text-cyber-purple" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          }
        />
      </div>

      {/* Recent Episodes */}
      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-semibold text-white">Recent Episodes</h2>
          <Link href="/episodes" className="text-sm text-neon-cyan hover:underline">
            View all →
          </Link>
        </div>
        
        {recentEpisodes.length === 0 ? (
          <div className="rounded-xl border border-white/10 bg-midnight/50 p-12 text-center">
            <svg className="mx-auto h-12 w-12 text-white/20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 4v16M17 4v16M3 8h4m10 0h4M3 12h18M3 16h4m10 0h4M4 20h16a1 1 0 001-1V5a1 1 0 00-1-1H4a1 1 0 00-1 1v14a1 1 0 001 1z" />
            </svg>
            <h3 className="mt-4 text-lg font-medium text-white">No episodes yet</h3>
            <p className="mt-2 text-white/60">Create your first episode to get started</p>
            <Link href="/episodes/new" className="mt-4 inline-block">
              <Button>Create Episode</Button>
            </Link>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {recentEpisodes.map((episode) => (
              <EpisodeCard key={episode.id} episode={episode} />
            ))}
          </div>
        )}
      </section>

      {/* Quick Actions */}
      <section>
        <h2 className="mb-4 text-xl font-semibold text-white">Quick Actions</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Link href="/episodes/new">
            <div className="group flex items-center gap-4 rounded-xl border border-white/10 bg-midnight/50 p-4 transition-all hover:border-neon-cyan/30 hover:bg-midnight/70">
              <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-neon-cyan/10 text-neon-cyan">
                <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
              </div>
              <div>
                <h3 className="font-medium text-white group-hover:text-neon-cyan">New Episode</h3>
                <p className="text-sm text-white/60">Generate a new video</p>
              </div>
            </div>
          </Link>
          
          <Link href="/characters">
            <div className="group flex items-center gap-4 rounded-xl border border-white/10 bg-midnight/50 p-4 transition-all hover:border-neon-cyan/30 hover:bg-midnight/70">
              <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-cyber-purple/10 text-cyber-purple">
                <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
                </svg>
              </div>
              <div>
                <h3 className="font-medium text-white group-hover:text-neon-cyan">Characters</h3>
                <p className="text-sm text-white/60">Manage F1 personalities</p>
              </div>
            </div>
          </Link>
          
          <Link href="/races">
            <div className="group flex items-center gap-4 rounded-xl border border-white/10 bg-midnight/50 p-4 transition-all hover:border-neon-cyan/30 hover:bg-midnight/70">
              <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-racing-red/10 text-racing-red">
                <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 21v-4m0 0V5a2 2 0 012-2h6.5l1 1H21l-3 6 3 6h-8.5l-1-1H5a2 2 0 00-2 2zm9-13.5V9" />
                </svg>
              </div>
              <div>
                <h3 className="font-medium text-white group-hover:text-neon-cyan">Race Calendar</h3>
                <p className="text-sm text-white/60">2026 F1 schedule</p>
              </div>
            </div>
          </Link>
          
          <Link href="/settings">
            <div className="group flex items-center gap-4 rounded-xl border border-white/10 bg-midnight/50 p-4 transition-all hover:border-neon-cyan/30 hover:bg-midnight/70">
              <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-electric-blue/10 text-electric-blue">
                <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
              </div>
              <div>
                <h3 className="font-medium text-white group-hover:text-neon-cyan">Settings</h3>
                <p className="text-sm text-white/60">Configure APIs</p>
              </div>
            </div>
          </Link>
        </div>
      </section>
    </div>
  );
}
