"use client";

import Link from "next/link";
import { Episode } from "@/lib/api";
import { cn, formatDuration, formatCurrency, formatRelativeTime, getMinioUrl } from "@/lib/utils";
import { Card, CardContent, CardFooter } from "@/components/ui/Card";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { GenerationProgress } from "@/components/ui/GenerationProgress";

interface EpisodeCardProps {
  episode: Episode;
}

export function EpisodeCard({ episode }: EpisodeCardProps) {
  const isGenerating = ["generating", "stitching", "uploading"].includes(episode.status);
  const completedScenes = episode.scenes
    ? episode.scenes.filter(s => s.status === "completed").length
    : (["stitching", "uploading", "published"].includes(episode.status) || episode.final_video_path)
      ? episode.scene_count
      : 0;

  return (
    <Link href={`/episodes/${episode.id}`}>
      <Card hover glow={isGenerating ? "cyan" : episode.status === "failed" ? "red" : null}>
        <CardContent className="space-y-4">
          {/* Header */}
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              <h3 className="truncate text-lg font-semibold text-white">{episode.title}</h3>
              <p className="text-sm text-white/60">{episode.race_name || "Unknown Race"}</p>
            </div>
            <StatusBadge status={episode.status} pulse={isGenerating} />
          </div>

          {/* Progress for generating episodes */}
          {isGenerating && !episode.final_video_path && (
            <GenerationProgress
              current={completedScenes}
              total={episode.scene_count}
              status={episode.status}
            />
          )}

          {/* Video Ready Indicator */}
          {!!episode.final_video_path && (
            <div className="flex items-center gap-3 rounded-lg bg-white/5 px-3 py-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-success-green/20">
                <svg className="h-4 w-4 text-success-green" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M8 5v14l11-7z" />
                </svg>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white">
                  Video Ready
                  {episode.duration_seconds ? ` · ${formatDuration(episode.duration_seconds)}` : ""}
                </p>
              </div>
              {episode.youtube_url && (
                <span className="rounded-full bg-neon-cyan/20 px-2 py-0.5 text-xs font-medium text-neon-cyan">
                  Published
                </span>
              )}
            </div>
          )}

          {/* Stats */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-xs text-white/50 uppercase tracking-wider">Type</p>
              <p className={cn(
                "text-sm font-medium",
                episode.episode_type === "pre-race" ? "text-electric-blue" : "text-cyber-purple"
              )}>
                {episode.episode_type.replace(/-/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase())}
              </p>
            </div>
            <div>
              <p className="text-xs text-white/50 uppercase tracking-wider">Scenes</p>
              <p className="text-sm font-medium text-white">
                {completedScenes}/{episode.scene_count}
              </p>
            </div>
            <div>
              <p className="text-xs text-white/50 uppercase tracking-wider">Cost</p>
              <p className="text-sm font-medium text-success-green">
                {formatCurrency(episode.total_cost_usd)}
              </p>
            </div>
            <div>
              <p className="text-xs text-white/50 uppercase tracking-wider">Created</p>
              <p className="text-sm font-medium text-white/70">
                {formatRelativeTime(episode.created_at)}
              </p>
            </div>
          </div>
        </CardContent>

        {/* Footer */}
        {episode.youtube_url && (
          <CardFooter className="flex items-center gap-2 text-sm text-neon-cyan">
            <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
              <path d="M19.615 3.184c-3.604-.246-11.631-.245-15.23 0-3.897.266-4.356 2.62-4.385 8.816.029 6.185.484 8.549 4.385 8.816 3.6.245 11.626.246 15.23 0 3.897-.266 4.356-2.62 4.385-8.816-.029-6.185-.484-8.549-4.385-8.816zm-10.615 12.816v-8l8 3.993-8 4.007z"/>
            </svg>
            <span>Published on YouTube</span>
          </CardFooter>
        )}
      </Card>
    </Link>
  );
}
