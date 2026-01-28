"use client";

import { cn, statusColors } from "@/lib/utils";

interface StatusBadgeProps {
  status: string;
  size?: "sm" | "md" | "lg";
  pulse?: boolean;
}

export function StatusBadge({ status, size = "md", pulse = false }: StatusBadgeProps) {
  const colors = statusColors[status.toLowerCase()] || statusColors.pending;
  
  const sizeClasses = {
    sm: "px-2 py-0.5 text-xs",
    md: "px-3 py-1 text-sm",
    lg: "px-4 py-1.5 text-base",
  };

  const isActive = ["generating", "stitching", "uploading"].includes(status.toLowerCase());

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full font-medium uppercase tracking-wider",
        colors.bg,
        colors.text,
        sizeClasses[size],
        pulse && isActive && "animate-pulse-slow"
      )}
    >
      {isActive && (
        <span className="relative flex h-2 w-2">
          <span className={cn(
            "absolute inline-flex h-full w-full animate-ping rounded-full opacity-75",
            colors.text.replace("text-", "bg-")
          )} />
          <span className={cn(
            "relative inline-flex h-2 w-2 rounded-full",
            colors.text.replace("text-", "bg-")
          )} />
        </span>
      )}
      {status.replace("-", " ")}
    </span>
  );
}
