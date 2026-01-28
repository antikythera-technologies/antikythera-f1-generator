"use client";

import { Scene } from "@/lib/api";
import { cn, formatMs, truncate, getMinioUrl } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/Card";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Button } from "@/components/ui/Button";

interface SceneCardProps {
  scene: Scene;
  onRegenerate?: (sceneId: number) => void;
  onView?: (scene: Scene) => void;
}

export function SceneCard({ scene, onRegenerate, onView }: SceneCardProps) {
  const isActive = scene.status === "generating";
  const isFailed = scene.status === "failed";
  const isComplete = scene.status === "completed";

  const thumbnailUrl = getMinioUrl(scene.source_image_path);

  return (
    <Card
      hover
      glow={isActive ? "cyan" : isFailed ? "red" : null}
      className={cn(
        "relative overflow-hidden",
        isActive && "ring-1 ring-neon-cyan/50"
      )}
    >
      {/* Thumbnail or placeholder */}
      <div className="relative aspect-video bg-twilight">
        {thumbnailUrl ? (
          <img
            src={thumbnailUrl}
            alt={`Scene ${scene.scene_number}`}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center">
            <span className="text-4xl font-bold text-white/10">
              {scene.scene_number.toString().padStart(2, "0")}
            </span>
          </div>
        )}
        
        {/* Scene number badge */}
        <div className="absolute left-2 top-2 rounded-lg bg-black/60 px-2 py-1 font-mono text-xs text-white">
          #{scene.scene_number.toString().padStart(2, "0")}
        </div>

        {/* Status overlay for active scenes */}
        {isActive && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/50">
            <div className="flex flex-col items-center gap-2">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-neon-cyan border-t-transparent" />
              <span className="text-xs text-neon-cyan">Generating...</span>
            </div>
          </div>
        )}

        {/* Play button for completed scenes */}
        {isComplete && scene.video_clip_path && (
          <button
            onClick={() => onView?.(scene)}
            className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors hover:bg-black/50 group"
          >
            <div className="rounded-full bg-white/20 p-3 opacity-0 transition-opacity group-hover:opacity-100">
              <svg className="h-8 w-8 text-white" fill="currentColor" viewBox="0 0 24 24">
                <path d="M8 5v14l11-7z" />
              </svg>
            </div>
          </button>
        )}
      </div>

      <CardContent className="space-y-3 p-4">
        {/* Status and duration */}
        <div className="flex items-center justify-between">
          <StatusBadge status={scene.status} size="sm" pulse={isActive} />
          {scene.generation_time_ms && (
            <span className="font-mono text-xs text-white/50">
              {formatMs(scene.generation_time_ms)}
            </span>
          )}
        </div>

        {/* Dialogue preview */}
        {scene.dialogue && (
          <p className="text-sm text-white/70 italic line-clamp-2">
            "{truncate(scene.dialogue, 80)}"
          </p>
        )}

        {/* Action preview */}
        {scene.action_description && !scene.dialogue && (
          <p className="text-sm text-white/60 line-clamp-2">
            {truncate(scene.action_description, 80)}
          </p>
        )}

        {/* Error message */}
        {isFailed && scene.last_error && (
          <div className="rounded-lg bg-racing-red/10 p-2">
            <p className="text-xs text-racing-red line-clamp-2">
              {truncate(scene.last_error, 100)}
            </p>
          </div>
        )}

        {/* Actions */}
        {(isFailed || isComplete) && onRegenerate && (
          <Button
            variant={isFailed ? "danger" : "ghost"}
            size="sm"
            className="w-full"
            onClick={(e) => {
              e.preventDefault();
              onRegenerate(scene.id);
            }}
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            {isFailed ? "Retry" : "Regenerate"}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
