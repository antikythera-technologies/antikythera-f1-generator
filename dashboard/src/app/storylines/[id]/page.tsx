"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  api,
  type Storyline,
  type Character,
  type StorylineType,
  type StorylineStatus,
  type PlotPoint,
} from "@/lib/api";
import { formatRelativeTime, formatDateTime, cn } from "@/lib/utils";
import { Header } from "@/components/layout/Header";
import { Button, Card, CardContent, LoadingPage } from "@/components/ui";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TYPES: { value: StorylineType; label: string }[] = [
  { value: "rivalry", label: "Rivalry" },
  { value: "character_arc", label: "Character Arc" },
  { value: "running_joke", label: "Running Joke" },
  { value: "season_plot", label: "Season Plot" },
  { value: "event_reaction", label: "Event Reaction" },
];

const STATUSES: { value: StorylineStatus; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "paused", label: "Paused" },
  { value: "completed", label: "Completed" },
  { value: "archived", label: "Archived" },
];

const typeColors: Record<StorylineType, string> = {
  rivalry: "bg-racing-red/20 text-racing-red",
  character_arc: "bg-cyber-purple/20 text-cyber-purple",
  running_joke: "bg-neon-cyan/20 text-neon-cyan",
  season_plot: "bg-electric-blue/20 text-electric-blue",
  event_reaction: "bg-warning-orange/20 text-warning-orange",
};

const typeLabel = (t: StorylineType): string =>
  TYPES.find((x) => x.value === t)?.label ?? t;

const statusColors: Record<StorylineStatus, string> = {
  active: "bg-success-green/20 text-success-green",
  paused: "bg-yellow-500/20 text-yellow-400",
  completed: "bg-white/10 text-white/40",
  archived: "bg-racing-red/20 text-racing-red",
};

const statusLabel = (s: StorylineStatus): string =>
  STATUSES.find((x) => x.value === s)?.label ?? s;

// ---------------------------------------------------------------------------
// Slide-over panel (reused from list page)
// ---------------------------------------------------------------------------

function SlideOver({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) {
  useEffect(() => {
    if (open) document.body.style.overflow = "hidden";
    else document.body.style.overflow = "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="absolute inset-0 bg-deep-space/70 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative z-10 flex h-full w-full max-w-2xl flex-col border-l border-white/10 bg-midnight/95 backdrop-blur-xl shadow-2xl">
        <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
          <h2 className="text-xl font-bold text-white">{title}</h2>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-white/40 hover:bg-white/10 hover:text-white transition-colors"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-6">{children}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function StorylineDetailPage() {
  const params = useParams();
  const router = useRouter();
  const storylineId = Number(params.id);

  const [storyline, setStoryline] = useState<Storyline | null>(null);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [advancing, setAdvancing] = useState(false);

  // Edit panel
  const [editOpen, setEditOpen] = useState(false);
  const [editForm, setEditForm] = useState({
    title: "",
    description: "",
    storyline_type: "rivalry" as StorylineType,
    status: "active" as StorylineStatus,
    priority: 5,
    comedy_notes: "",
    tags: "",
    character_ids: [] as number[],
    plot_points: [] as PlotPoint[],
  });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const [s, chars] = await Promise.all([
        api.storylines.get(storylineId),
        api.characters.list(),
      ]);
      setStoryline(s);
      setCharacters(chars);
      setError(null);
    } catch (err) {
      console.error("Failed to fetch storyline:", err);
      setError(err instanceof Error ? err.message : "Failed to load storyline");
    } finally {
      setLoading(false);
    }
  }, [storylineId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Advance plot
  async function handleAdvance() {
    if (!storyline) return;
    try {
      setAdvancing(true);
      const updated = await api.storylines.advance(storylineId);
      setStoryline(updated);
    } catch (err) {
      console.error("Failed to advance:", err);
      setError(err instanceof Error ? err.message : "Failed to advance storyline");
    } finally {
      setAdvancing(false);
    }
  }

  // Open edit panel
  function openEdit() {
    if (!storyline) return;
    setEditForm({
      title: storyline.title,
      description: storyline.description,
      storyline_type: storyline.storyline_type,
      status: storyline.status,
      priority: storyline.priority,
      comedy_notes: storyline.comedy_notes ?? "",
      tags: storyline.tags?.join(", ") ?? "",
      character_ids: storyline.characters.map((c) => c.id),
      plot_points: (storyline.plot_points ?? []).map((p) => ({
        title: p.title || "",
        description: p.description || "",
        completed: p.completed ?? false,
      })),
    });
    setFormError(null);
    setEditOpen(true);
  }

  // Save edit
  async function handleSave() {
    if (!editForm.title.trim() || !editForm.description.trim()) {
      setFormError("Title and description are required");
      return;
    }

    try {
      setSaving(true);
      setFormError(null);

      const payload = {
        title: editForm.title,
        description: editForm.description,
        storyline_type: editForm.storyline_type,
        status: editForm.status,
        priority: editForm.priority,
        comedy_notes: editForm.comedy_notes || null,
        tags: editForm.tags
          ? editForm.tags.split(",").map((t) => t.trim()).filter(Boolean)
          : null,
        character_ids: editForm.character_ids,
        plot_points: editForm.plot_points.length > 0 ? editForm.plot_points : null,
      };

      const updated = await api.storylines.update(storylineId, payload);
      setStoryline(updated);
      setEditOpen(false);
    } catch (err) {
      console.error("Failed to save:", err);
      setFormError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  // Archive
  async function handleArchive() {
    try {
      await api.storylines.delete(storylineId);
      router.push("/storylines");
    } catch (err) {
      console.error("Failed to archive:", err);
      setError(err instanceof Error ? err.message : "Failed to archive");
    }
  }

  // Form helpers
  function toggleCharacter(charId: number) {
    setEditForm((prev) => ({
      ...prev,
      character_ids: prev.character_ids.includes(charId)
        ? prev.character_ids.filter((id) => id !== charId)
        : [...prev.character_ids, charId],
    }));
  }

  function addPlotPoint() {
    setEditForm((prev) => ({
      ...prev,
      plot_points: [...prev.plot_points, { title: "", description: "", completed: false }],
    }));
  }

  function updatePlotPoint(index: number, field: keyof PlotPoint, value: string | boolean) {
    setEditForm((prev) => {
      const updated = [...prev.plot_points];
      updated[index] = { ...updated[index], [field]: value };
      return { ...prev, plot_points: updated };
    });
  }

  function removePlotPoint(index: number) {
    setEditForm((prev) => ({
      ...prev,
      plot_points: prev.plot_points.filter((_, i) => i !== index),
    }));
  }

  const inputClass =
    "w-full rounded-lg border border-white/10 bg-twilight/50 px-3 py-2 text-sm text-white placeholder-white/30 focus:border-neon-cyan/50 focus:outline-none focus:ring-1 focus:ring-neon-cyan/50 transition-colors";
  const textareaClass = inputClass + " resize-none";
  const selectClass = inputClass;
  const labelClass = "block text-sm font-medium text-white/70 mb-1";

  if (loading) {
    return <LoadingPage text="Loading storyline..." />;
  }

  if (error || !storyline) {
    return (
      <div className="space-y-4">
        <Header title="Storyline Not Found" />
        <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-6 text-center">
          <p className="text-racing-red">{error || "Storyline not found"}</p>
          <Link href="/storylines" className="mt-4 inline-block">
            <Button variant="secondary">Back to Storylines</Button>
          </Link>
        </div>
      </div>
    );
  }

  const plotPoints = storyline.plot_points ?? [];
  const totalBeats = plotPoints.length;

  return (
    <div className="space-y-8">
      {/* Header */}
      <Header
        title={storyline.title}
        subtitle={`${typeLabel(storyline.storyline_type)} storyline`}
        actions={
          <div className="flex items-center gap-3">
            {storyline.status === "active" && totalBeats > 0 && (
              <Button
                variant="secondary"
                loading={advancing}
                onClick={handleAdvance}
              >
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
                </svg>
                Advance Plot
              </Button>
            )}
            <Button variant="secondary" onClick={openEdit}>
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
              </svg>
              Edit
            </Button>
            {storyline.status !== "archived" && (
              <Button variant="danger" onClick={handleArchive}>
                Archive
              </Button>
            )}
          </div>
        }
      />

      {/* Error banner */}
      {error && (
        <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-4">
          <p className="text-racing-red">{error}</p>
        </div>
      )}

      {/* Overview card */}
      <Card>
        <CardContent className="space-y-6">
          {/* Status row */}
          <div className="flex items-center gap-3">
            <span className={cn("rounded px-2.5 py-1 text-xs font-medium", typeColors[storyline.storyline_type])}>
              {typeLabel(storyline.storyline_type)}
            </span>
            <span className={cn("rounded px-2.5 py-1 text-xs font-medium", statusColors[storyline.status])}>
              {statusLabel(storyline.status)}
            </span>
          </div>

          {/* Description */}
          <p className="text-sm text-white/70 leading-relaxed">{storyline.description}</p>

          {/* Stats grid */}
          <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
            <div>
              <p className="text-xs text-white/50 uppercase tracking-wider">Priority</p>
              <p className="mt-1 text-lg font-semibold text-neon-cyan">{storyline.priority}/10</p>
            </div>
            <div>
              <p className="text-xs text-white/50 uppercase tracking-wider">Episodes</p>
              <p className="mt-1 text-lg font-semibold text-white">{storyline.episode_count ?? 0}</p>
            </div>
            <div>
              <p className="text-xs text-white/50 uppercase tracking-wider">Characters</p>
              <p className="mt-1 text-lg font-semibold text-cyber-purple">{storyline.characters.length}</p>
            </div>
            <div>
              <p className="text-xs text-white/50 uppercase tracking-wider">Plot Beats</p>
              <p className="mt-1 text-lg font-semibold text-electric-blue">
                {storyline.current_beat + 1}/{totalBeats || "0"}
              </p>
            </div>
          </div>

          {/* Timestamps */}
          <div className="grid grid-cols-2 gap-4 border-t border-white/10 pt-6 sm:grid-cols-3">
            <div>
              <p className="text-xs text-white/50">Created</p>
              <p className="mt-1 text-sm text-white/70">{formatDateTime(storyline.created_at)}</p>
            </div>
            <div>
              <p className="text-xs text-white/50">Last Updated</p>
              <p className="mt-1 text-sm text-white/70">{formatRelativeTime(storyline.updated_at)}</p>
            </div>
          </div>

          {/* Tags */}
          {storyline.tags && storyline.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {storyline.tags.map((tag) => (
                <span
                  key={tag}
                  className="rounded bg-white/5 px-2.5 py-1 text-xs font-medium text-white/50 border border-white/5"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Characters */}
      {storyline.characters.length > 0 && (
        <section>
          <h2 className="mb-4 text-xl font-semibold text-white">Characters</h2>
          <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
            {storyline.characters.map((char) => (
              <Card key={char.id} className="p-4" hover>
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full bg-cyber-purple/20">
                    <svg className="h-5 w-5 text-cyber-purple" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                    </svg>
                  </div>
                  <div>
                    <p className="font-medium text-white">{char.display_name}</p>
                    {char.team && <p className="text-xs text-white/40">{char.team}</p>}
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </section>
      )}

      {/* Comedy Notes */}
      {storyline.comedy_notes && (
        <section>
          <h2 className="mb-4 text-xl font-semibold text-white">Comedy Notes</h2>
          <Card>
            <CardContent>
              <p className="text-sm text-white/70 leading-relaxed whitespace-pre-wrap">{storyline.comedy_notes}</p>
            </CardContent>
          </Card>
        </section>
      )}

      {/* Plot Points Timeline */}
      {totalBeats > 0 && (
        <section>
          <h2 className="mb-4 text-xl font-semibold text-white">Plot Points</h2>

          {/* Progress bar */}
          <div className="mb-6">
            <div className="flex items-center justify-between text-xs text-white/40 mb-2">
              <span>Arc Progress</span>
              <span className="font-mono">
                Beat {storyline.current_beat + 1} of {totalBeats}
              </span>
            </div>
            <div className="h-2 w-full rounded-full bg-white/10 overflow-hidden">
              <div
                className="h-full rounded-full bg-gradient-to-r from-neon-cyan to-electric-blue transition-all"
                style={{ width: `${((storyline.current_beat + 1) / totalBeats) * 100}%` }}
              />
            </div>
          </div>

          {/* Timeline */}
          <div className="space-y-0">
            {plotPoints.map((point, index) => {
              const isCurrent = index === storyline.current_beat;
              const isCompleted = point.completed || index < storyline.current_beat;
              const isFuture = index > storyline.current_beat;

              return (
                <div key={index} className="flex gap-4">
                  {/* Timeline connector */}
                  <div className="flex flex-col items-center">
                    <div
                      className={cn(
                        "flex h-8 w-8 items-center justify-center rounded-full border-2 flex-shrink-0 transition-colors",
                        isCurrent
                          ? "border-neon-cyan bg-neon-cyan/20"
                          : isCompleted
                            ? "border-success-green bg-success-green/20"
                            : "border-white/20 bg-white/5"
                      )}
                    >
                      {isCompleted && !isCurrent ? (
                        <svg className="h-4 w-4 text-success-green" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                        </svg>
                      ) : (
                        <span
                          className={cn(
                            "text-xs font-bold",
                            isCurrent ? "text-neon-cyan" : "text-white/30"
                          )}
                        >
                          {index + 1}
                        </span>
                      )}
                    </div>
                    {index < totalBeats - 1 && (
                      <div
                        className={cn(
                          "w-0.5 flex-1 min-h-[24px]",
                          isCompleted ? "bg-success-green/30" : "bg-white/10"
                        )}
                      />
                    )}
                  </div>

                  {/* Content */}
                  <div
                    className={cn(
                      "flex-1 rounded-lg border p-4 mb-3 transition-colors",
                      isCurrent
                        ? "border-neon-cyan/30 bg-neon-cyan/5"
                        : isCompleted
                          ? "border-success-green/20 bg-success-green/5"
                          : "border-white/10 bg-white/[0.02]"
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <h4
                        className={cn(
                          "font-medium",
                          isCurrent
                            ? "text-neon-cyan"
                            : isCompleted
                              ? "text-success-green"
                              : "text-white/50"
                        )}
                      >
                        {point.title || `Beat ${index + 1}`}
                      </h4>
                      {isCurrent && (
                        <span className="rounded bg-neon-cyan/20 px-2 py-0.5 text-[10px] font-bold text-neon-cyan uppercase tracking-wider">
                          Current
                        </span>
                      )}
                    </div>
                    {point.description && (
                      <p
                        className={cn(
                          "mt-1 text-sm",
                          isFuture ? "text-white/30" : "text-white/60"
                        )}
                      >
                        {point.description}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Episode appearances */}
      <section>
        <h2 className="mb-4 text-xl font-semibold text-white">
          Episode Appearances ({storyline.episode_links.length})
        </h2>

        {storyline.episode_links.length > 0 ? (
          <div className="space-y-3">
            {storyline.episode_links.map((link) => (
              <Card key={link.id} className="p-4" hover>
                <div className="flex items-center justify-between">
                  <div>
                    <Link
                      href={`/episodes/${link.episode_id}`}
                      className="font-medium text-white hover:text-neon-cyan transition-colors"
                    >
                      Episode #{link.episode_id}
                    </Link>
                    <div className="mt-1 flex items-center gap-3 text-xs text-white/40">
                      {link.beat_used != null && (
                        <span className="font-mono">Beat {link.beat_used + 1}</span>
                      )}
                      {link.scene_numbers && link.scene_numbers.length > 0 && (
                        <span>
                          Scenes: {link.scene_numbers.join(", ")}
                        </span>
                      )}
                      <span>{formatRelativeTime(link.created_at)}</span>
                    </div>
                    {link.usage_notes && (
                      <p className="mt-1 text-sm text-white/50 italic">{link.usage_notes}</p>
                    )}
                  </div>
                  <Link href={`/episodes/${link.episode_id}`}>
                    <svg className="h-5 w-5 text-white/30 hover:text-neon-cyan transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </Link>
                </div>
              </Card>
            ))}
          </div>
        ) : (
          <Card className="p-8 text-center">
            <svg className="mx-auto h-10 w-10 text-white/20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 4v16M17 4v16M3 8h4m10 0h4M3 12h18M3 16h4m10 0h4" />
            </svg>
            <p className="mt-3 text-sm text-white/40">
              This storyline hasn&apos;t appeared in any episodes yet.
            </p>
          </Card>
        )}
      </section>

      {/* Edit slide-over */}
      <SlideOver
        open={editOpen}
        onClose={() => setEditOpen(false)}
        title={`Edit: ${storyline.title}`}
      >
        <div className="space-y-6">
          {formError && (
            <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-3">
              <p className="text-sm text-racing-red">{formError}</p>
            </div>
          )}

          {/* Basic info */}
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold text-neon-cyan uppercase tracking-wider mb-2">Basic Information</legend>

            <div>
              <label className={labelClass}>Title *</label>
              <input
                type="text"
                value={editForm.title}
                onChange={(e) => setEditForm((prev) => ({ ...prev, title: e.target.value }))}
                className={inputClass}
              />
            </div>

            <div>
              <label className={labelClass}>Description *</label>
              <textarea
                value={editForm.description}
                onChange={(e) => setEditForm((prev) => ({ ...prev, description: e.target.value }))}
                rows={3}
                className={textareaClass}
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelClass}>Type</label>
                <select
                  value={editForm.storyline_type}
                  onChange={(e) => setEditForm((prev) => ({ ...prev, storyline_type: e.target.value as StorylineType }))}
                  className={selectClass}
                >
                  {TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelClass}>Status</label>
                <select
                  value={editForm.status}
                  onChange={(e) => setEditForm((prev) => ({ ...prev, status: e.target.value as StorylineStatus }))}
                  className={selectClass}
                >
                  {STATUSES.map((s) => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </div>
            </div>
          </fieldset>

          {/* Characters */}
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold text-neon-cyan uppercase tracking-wider mb-2">Characters</legend>
            <div className="grid grid-cols-2 gap-2 max-h-48 overflow-y-auto">
              {characters
                .filter((c) => c.is_active)
                .map((c) => (
                  <label
                    key={c.id}
                    className={cn(
                      "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm cursor-pointer transition-colors",
                      editForm.character_ids.includes(c.id)
                        ? "border-neon-cyan/50 bg-neon-cyan/10 text-white"
                        : "border-white/10 bg-twilight/30 text-white/60 hover:bg-twilight/50"
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={editForm.character_ids.includes(c.id)}
                      onChange={() => toggleCharacter(c.id)}
                      className="sr-only"
                    />
                    <div
                      className={cn(
                        "h-4 w-4 rounded border flex items-center justify-center flex-shrink-0",
                        editForm.character_ids.includes(c.id)
                          ? "border-neon-cyan bg-neon-cyan"
                          : "border-white/30"
                      )}
                    >
                      {editForm.character_ids.includes(c.id) && (
                        <svg className="h-3 w-3 text-deep-space" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                        </svg>
                      )}
                    </div>
                    <span className="truncate">{c.display_name || c.name}</span>
                  </label>
                ))}
            </div>
          </fieldset>

          {/* Plot points */}
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold text-neon-cyan uppercase tracking-wider mb-2">Plot Points</legend>

            {editForm.plot_points.map((point, index) => (
              <div key={index} className="rounded-lg border border-white/10 bg-twilight/30 p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-white/50">Beat {index + 1}</span>
                  <button
                    onClick={() => removePlotPoint(index)}
                    className="text-racing-red/60 hover:text-racing-red text-xs transition-colors"
                  >
                    Remove
                  </button>
                </div>
                <input
                  type="text"
                  value={point.title}
                  onChange={(e) => updatePlotPoint(index, "title", e.target.value)}
                  placeholder="Beat title..."
                  className={inputClass}
                />
                <textarea
                  value={point.description}
                  onChange={(e) => updatePlotPoint(index, "description", e.target.value)}
                  placeholder="What happens..."
                  rows={2}
                  className={textareaClass}
                />
              </div>
            ))}

            <button
              onClick={addPlotPoint}
              className="flex items-center gap-2 rounded-lg border border-dashed border-white/20 px-4 py-2.5 text-sm text-white/50 hover:border-neon-cyan/50 hover:text-neon-cyan transition-colors w-full justify-center"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              Add Plot Point
            </button>
          </fieldset>

          {/* Comedy & tuning */}
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold text-neon-cyan uppercase tracking-wider mb-2">Comedy & Tuning</legend>

            <div>
              <label className={labelClass}>Comedy Notes</label>
              <textarea
                value={editForm.comedy_notes}
                onChange={(e) => setEditForm((prev) => ({ ...prev, comedy_notes: e.target.value }))}
                rows={3}
                className={textareaClass}
              />
            </div>

            <div>
              <label className={labelClass}>
                Priority: <span className="font-mono text-neon-cyan">{editForm.priority}/10</span>
              </label>
              <input
                type="range"
                min={1}
                max={10}
                step={1}
                value={editForm.priority}
                onChange={(e) => setEditForm((prev) => ({ ...prev, priority: Number(e.target.value) }))}
                className="w-full accent-neon-cyan"
              />
            </div>

            <div>
              <label className={labelClass}>Tags</label>
              <input
                type="text"
                value={editForm.tags}
                onChange={(e) => setEditForm((prev) => ({ ...prev, tags: e.target.value }))}
                placeholder="Comma-separated"
                className={inputClass}
              />
            </div>
          </fieldset>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 border-t border-white/10 pt-6">
            <Button variant="secondary" onClick={() => setEditOpen(false)} disabled={saving}>
              Cancel
            </Button>
            <Button onClick={handleSave} loading={saving}>
              Save Changes
            </Button>
          </div>
        </div>
      </SlideOver>
    </div>
  );
}
