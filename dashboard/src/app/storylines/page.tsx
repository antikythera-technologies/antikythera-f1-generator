"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, Episode } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";
import { Header } from "@/components/layout/Header";
import { Button, Card, LoadingPage, StatusBadge } from "@/components/ui";

const episodeTypeLabels: Record<string, string> = {
  "pre-race": "Pre-Race",
  "post-race": "Post Race",
  "post-fp2": "Post FP2",
  "post-sprint": "Post Sprint",
  "weekly-recap": "Weekly Recap",
};

export default function StorylinesPage() {
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  useEffect(() => {
    fetchData();
  }, []);

  async function fetchData() {
    try {
      setLoading(true);
      const data = await api.episodes.list({ limit: 50 });
      setEpisodes(data);
      setError(null);
    } catch (err) {
      console.error("Failed to fetch episodes:", err);
      setError(err instanceof Error ? err.message : "Failed to load storylines");
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return <LoadingPage text="Loading storylines..." />;
  }

  return (
    <div className="space-y-8">
      <Header
        title="Storylines & Prompts"
        subtitle="Review generated narratives and scene prompts"
      />

      {error && (
        <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-4">
          <p className="text-racing-red">{error}</p>
        </div>
      )}

      <div className="space-y-4">
        {episodes.map((episode) => (
          <Card key={episode.id} className="overflow-hidden">
            {/* Episode Header */}
            <button
              onClick={() => setExpandedId(expandedId === episode.id ? null : episode.id)}
              className="w-full p-4 text-left hover:bg-white/5"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${
                      episode.episode_type === "weekly-recap" ? "bg-cyber-purple/20 text-cyber-purple" :
                      episode.episode_type === "post-fp2" ? "bg-neon-cyan/20 text-neon-cyan" :
                      episode.episode_type === "post-sprint" ? "bg-electric-blue/20 text-electric-blue" :
                      "bg-racing-red/20 text-racing-red"
                    }`}>
                      {episodeTypeLabels[episode.episode_type] || episode.episode_type}
                    </span>
                    <StatusBadge status={episode.status} />
                  </div>
                  
                  <h3 className="mt-2 font-semibold text-white">{episode.title}</h3>
                  
                  {episode.race_name && (
                    <p className="mt-1 text-sm text-white/60">{episode.race_name}</p>
                  )}
                  
                  <p className="mt-1 text-xs text-white/40">
                    Created: {formatDateTime(episode.triggered_at)} • {episode.scene_count} scenes
                  </p>
                </div>
                
                <div className="flex items-center gap-4">
                  {episode.youtube_url && (
                    <a
                      href={episode.youtube_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="rounded bg-racing-red/20 px-3 py-1 text-xs font-medium text-racing-red hover:bg-racing-red/30"
                      onClick={(e) => e.stopPropagation()}
                    >
                      Watch on YouTube
                    </a>
                  )}
                  
                  <svg
                    className={`h-5 w-5 text-white/40 transition-transform ${expandedId === episode.id ? "rotate-180" : ""}`}
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </div>
              </div>
            </button>

            {/* Expanded Content */}
            {expandedId === episode.id && (
              <div className="border-t border-white/10 p-4">
                {/* Description */}
                {episode.description && (
                  <div className="mb-6">
                    <h4 className="text-sm font-medium text-white/80">Episode Description</h4>
                    <p className="mt-2 text-sm text-white/60">{episode.description}</p>
                  </div>
                )}

                {/* Storyline Section - Placeholder for future enhancement */}
                <div className="mb-6 rounded-lg bg-midnight/50 p-4">
                  <h4 className="text-sm font-medium text-neon-cyan">Main Storyline</h4>
                  <p className="mt-2 text-sm text-white/60 italic">
                    Storyline data will be available once the storyline tracking is implemented.
                    This will show the main narrative thread, comedic angles, and source news articles.
                  </p>
                </div>

                {/* Scenes */}
                {episode.scenes && episode.scenes.length > 0 ? (
                  <div>
                    <h4 className="mb-3 text-sm font-medium text-white/80">Scene Breakdown</h4>
                    <div className="space-y-3">
                      {episode.scenes.map((scene) => (
                        <div 
                          key={scene.id} 
                          className="rounded-lg border border-white/10 bg-midnight/30 p-3"
                        >
                          <div className="flex items-start justify-between gap-4">
                            <div className="flex-1">
                              <div className="flex items-center gap-2">
                                <span className="rounded bg-white/10 px-2 py-0.5 text-xs font-mono text-white/60">
                                  Scene {scene.scene_number}
                                </span>
                                <StatusBadge status={scene.status} size="sm" />
                                {scene.character_name && (
                                  <span className="text-xs text-cyber-purple">{scene.character_name}</span>
                                )}
                              </div>
                              
                              {scene.dialogue && (
                                <div className="mt-2">
                                  <p className="text-xs font-medium text-white/40">Dialogue:</p>
                                  <p className="mt-1 text-sm text-white/80 italic">"{scene.dialogue}"</p>
                                </div>
                              )}
                              
                              {scene.action_description && (
                                <div className="mt-2">
                                  <p className="text-xs font-medium text-white/40">Action:</p>
                                  <p className="mt-1 text-sm text-white/60">{scene.action_description}</p>
                                </div>
                              )}
                              
                              {scene.ovi_prompt && (
                                <details className="mt-2">
                                  <summary className="cursor-pointer text-xs text-neon-cyan hover:underline">
                                    View Ovi Prompt
                                  </summary>
                                  <pre className="mt-2 overflow-x-auto rounded bg-black/30 p-2 text-xs text-white/60">
                                    {scene.ovi_prompt}
                                  </pre>
                                </details>
                              )}
                              
                              {scene.last_error && (
                                <p className="mt-2 text-xs text-racing-red">{scene.last_error}</p>
                              )}
                            </div>
                            
                            <div className="text-right text-xs text-white/40">
                              {scene.duration_seconds}s
                              {scene.generation_time_ms && (
                                <p>Gen: {(scene.generation_time_ms / 1000).toFixed(1)}s</p>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="text-center text-sm text-white/40">
                    <Link href={`/episodes/${episode.id}`}>
                      <Button variant="secondary" size="sm">View Full Episode Details</Button>
                    </Link>
                  </div>
                )}
              </div>
            )}
          </Card>
        ))}

        {episodes.length === 0 && (
          <Card className="p-8 text-center">
            <svg className="mx-auto h-12 w-12 text-white/20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <h3 className="mt-4 text-lg font-medium text-white">No episodes yet</h3>
            <p className="mt-2 text-white/60">Generate episodes to see their storylines here</p>
          </Card>
        )}
      </div>
    </div>
  );
}
