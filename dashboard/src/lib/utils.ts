/**
 * Utility functions
 */

// Format currency
export function formatCurrency(amount: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(amount);
}

// Format date
export function formatDate(date: string | Date, options?: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    ...options,
  }).format(new Date(date));
}

// Format date time
export function formatDateTime(date: string | Date): string {
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(date));
}

// Format duration in seconds to human readable
export function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

// Format milliseconds to seconds
export function formatMs(ms: number): string {
  return `${(ms / 1000).toFixed(2)}s`;
}

// Relative time
export function formatRelativeTime(date: string | Date): string {
  const now = new Date();
  const then = new Date(date);
  const diffMs = now.getTime() - then.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSecs < 60) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return formatDate(date);
}

// Class name utility
export function cn(...classes: (string | undefined | null | false)[]): string {
  return classes.filter(Boolean).join(" ");
}

// Status colors
export const statusColors: Record<string, { bg: string; text: string; glow?: string }> = {
  pending: { bg: "bg-yellow-500/20", text: "text-yellow-400", glow: "shadow-yellow-500/20" },
  queued: { bg: "bg-yellow-500/20", text: "text-yellow-400", glow: "shadow-yellow-500/20" },
  generating: { bg: "bg-neon-cyan/20", text: "text-neon-cyan", glow: "shadow-glow-cyan" },
  stitching: { bg: "bg-cyber-purple/20", text: "text-cyber-purple" },
  uploading: { bg: "bg-electric-blue/20", text: "text-electric-blue" },
  complete: { bg: "bg-success-green/20", text: "text-success-green" },
  completed: { bg: "bg-success-green/20", text: "text-success-green" },
  published: { bg: "bg-success-green/20", text: "text-success-green" },
  failed: { bg: "bg-racing-red/20", text: "text-racing-red", glow: "shadow-glow-red" },
  error: { bg: "bg-racing-red/20", text: "text-racing-red", glow: "shadow-glow-red" },
};

// Get MinIO URL
export function getMinioUrl(path: string | null): string | null {
  if (!path) return null;
  const minioBase = process.env.NEXT_PUBLIC_MINIO_URL || "https://minio.antikythera.co.za";
  // Path already includes bucket/key
  return `${minioBase}/${path}`;
}

// Truncate text
export function truncate(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength - 3) + "...";
}
