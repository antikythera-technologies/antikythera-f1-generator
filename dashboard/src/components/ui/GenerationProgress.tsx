"use client";

import { cn } from "@/lib/utils";

interface GenerationProgressProps {
  current: number;
  total: number;
  status?: string;
  showLabel?: boolean;
  className?: string;
}

export function GenerationProgress({
  current,
  total,
  status = "generating",
  showLabel = true,
  className,
}: GenerationProgressProps) {
  const percentage = total > 0 ? Math.round((current / total) * 100) : 0;
  
  const statusColors = {
    generating: "from-neon-cyan to-electric-blue",
    stitching: "from-cyber-purple to-electric-blue",
    uploading: "from-electric-blue to-success-green",
    complete: "from-success-green to-success-green",
    failed: "from-racing-red to-warning-orange",
  };

  const color = statusColors[status as keyof typeof statusColors] || statusColors.generating;

  return (
    <div className={cn("w-full", className)}>
      {showLabel && (
        <div className="mb-2 flex items-center justify-between text-sm">
          <span className="text-white/70">
            Scene {current} of {total}
          </span>
          <span className="font-mono text-neon-cyan">{percentage}%</span>
        </div>
      )}
      <div className="relative h-2 overflow-hidden rounded-full bg-white/10">
        <div
          className={cn(
            "h-full rounded-full bg-gradient-to-r transition-all duration-500",
            color
          )}
          style={{ width: `${percentage}%` }}
        />
        {status === "generating" && (
          <div className="absolute inset-0 overflow-hidden">
            <div
              className={cn(
                "absolute h-full w-1/3 bg-gradient-to-r from-transparent via-white/30 to-transparent",
                "animate-scan"
              )}
            />
          </div>
        )}
      </div>
    </div>
  );
}
