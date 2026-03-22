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

  // Cache-bust using generation_time_ms — changes on every regen, stable between renders
  const cacheKey = String(scene.generation_time_ms || scene.created_at || "");
  const thumbnailUrl = getMinioUrl(scene.source_image_path, cacheKey);

  return (
    <Card
      hover
      glow={isActive ? "cyan" : isFailed ? "red" : null}
      onClick={() => onView?.(scene)}
      className={cn(
        "group relative overflow-hidden",
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

        {/* Validation badge */}
        {scene.validation_status && (
          <div className={cn(
            "absolute right-2 top-2 rounded-full p-1",
            scene.validation_status === "passed" ? "bg-success-green/80" : "bg-racing-red/80"
          )}>
            {scene.validation_status === "passed" ? (
              <svg className="h-3 w-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
              </svg>
            ) : (
              <svg className="h-3 w-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M6 18L18 6M6 6l12 12" />
              </svg>
            )}
          </div>
        )}

        {/* Status overlay for active scenes */}
        {isActive && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/50">
            <div className="flex flex-col items-center gap-2">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-neon-cyan border-t-transparent" />
              <span className="text-xs text-neon-cyan">Generating...</span>
            </div>
          </div>
        )}

        {/* Play icon overlay for completed scenes */}
        {isComplete && scene.video_clip_path && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/30 pointer-events-none">
            <div className="rounded-full bg-white/20 p-3 opacity-0 transition-opacity group-hover:opacity-100">
              <svg className="h-8 w-8 text-white" fill="currentColor" viewBox="0 0 24 24">
                <path d="M8 5v14l11-7z" />
              </svg>
            </div>
          </div>
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

        {/* Scene type */}
        {scene.scene_type && (
          <span className={cn(
            "self-start rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider",
            scene.scene_type === "TALKING_HEAD" ? "bg-electric-blue/15 text-electric-blue" :
            scene.scene_type === "ACTION_REPLAY" ? "bg-racing-red/15 text-racing-red" :
            scene.scene_type === "ESTABLISHING" ? "bg-success-green/15 text-success-green" :
            scene.scene_type === "TITLE_CARD" ? "bg-amber-500/15 text-amber-400" :
            scene.scene_type === "REACTION" ? "bg-cyber-purple/15 text-cyber-purple" :
            scene.scene_type === "PODIUM" ? "bg-amber-500/15 text-amber-400" :
            "bg-white/10 text-white/50"
          )}>
            {scene.scene_type.replace(/_/g, " ")}
          </span>
        )}

        {/* Pipeline & Cost info */}
        <div className="flex flex-wrap items-center gap-1.5">
          {scene.image_backend && (
            <span className="rounded-full bg-neon-cyan/10 px-2 py-0.5 text-[10px] font-medium text-neon-cyan uppercase tracking-wider">
              {scene.image_backend}
            </span>
          )}
          {scene.video_generator && (
            <span className="rounded-full bg-cyber-purple/10 px-2 py-0.5 text-[10px] font-medium text-cyber-purple uppercase tracking-wider">
              {scene.video_generator}
            </span>
          )}
          {(scene.image_cost_usd || scene.video_cost_usd) && (
            <span className="ml-auto font-mono text-[10px] text-success-green">
              ${(Number(scene.image_cost_usd || 0) + Number(scene.video_cost_usd || 0)).toFixed(3)}
            </span>
          )}
        </div>

        {/* Generation metadata (LoRA, IC, face ref, regen count) */}
        {(scene.lora_used || scene.instant_character_used || scene.face_reference_url || (scene.regeneration_count && scene.regeneration_count > 1)) && (
          <div className="flex flex-wrap items-center gap-1.5">
            {scene.lora_used && (
              <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-400">
                LoRA
              </span>
            )}
            {scene.instant_character_used && (
              <span className="rounded-full bg-electric-blue/10 px-2 py-0.5 text-[10px] font-medium text-electric-blue">
                IC
              </span>
            )}
            {scene.face_reference_url && (
              <span className="rounded-full bg-cyber-purple/10 px-1.5 py-0.5 text-[10px] text-cyber-purple" title={scene.face_reference_url}>
                Face
              </span>
            )}
            {scene.regeneration_count > 1 && (
              <span className="ml-auto rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-400" title={`Regenerated ${scene.regeneration_count} times`}>
                ×{scene.regeneration_count}
              </span>
            )}
          </div>
        )}

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


      </CardContent>
    </Card>
  );
}
