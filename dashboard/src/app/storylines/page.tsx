"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  api,
  type StorylineListItem,
  type Character,
  type StorylineType,
  type StorylineStatus,
  type PlotPoint,
} from "@/lib/api";
import { formatRelativeTime, cn } from "@/lib/utils";
import { Header } from "@/components/layout/Header";
import { Button, Card, LoadingPage } from "@/components/ui";

// ---------------------------------------------------------------------------
// Constants & helpers
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
// Priority bar component
// ---------------------------------------------------------------------------

function PriorityBar({ priority }: { priority: number }) {
  return (
    <div className="flex items-center gap-1.5">
      <div className="flex gap-px">
        {Array.from({ length: 10 }).map((_, i) => (
          <div
            key={i}
            className={cn(
              "h-3 w-1.5 rounded-sm transition-colors",
              i < priority
                ? priority >= 8
                  ? "bg-racing-red"
                  : priority >= 5
                    ? "bg-neon-cyan"
                    : "bg-yellow-400"
                : "bg-white/10"
            )}
          />
        ))}
      </div>
      <span className="ml-1 font-mono text-xs text-white/50">{priority}/10</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Slide-over panel
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
        <div className="flex-1 overflow-y-auto px-6 py-6">
          {children}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Form data
// ---------------------------------------------------------------------------

interface StorylineFormData {
  title: string;
  description: string;
  storyline_type: StorylineType;
  status: StorylineStatus;
  priority: number;
  comedy_notes: string;
  tags: string;
  character_ids: number[];
  plot_points: PlotPoint[];
}

const emptyForm: StorylineFormData = {
  title: "",
  description: "",
  storyline_type: "rivalry",
  status: "active",
  priority: 5,
  comedy_notes: "",
  tags: "",
  character_ids: [],
  plot_points: [],
};

function storylineToForm(s: StorylineListItem): StorylineFormData {
  return {
    title: s.title,
    description: s.description,
    storyline_type: s.storyline_type,
    status: s.status,
    priority: s.priority,
    comedy_notes: s.comedy_notes ?? "",
    tags: s.tags?.join(", ") ?? "",
    character_ids: s.characters.map((c) => c.id),
    plot_points: (s.plot_points ?? []).map((p) => ({
      title: p.title || "",
      description: p.description || "",
      completed: p.completed ?? false,
    })),
  };
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function StorylinesPage() {
  const [storylines, setStorylines] = useState<StorylineListItem[]>([]);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [filterType, setFilterType] = useState<StorylineType | "all">("all");
  const [filterStatus, setFilterStatus] = useState<StorylineStatus | "all">("all");
  const [filterCharacter, setFilterCharacter] = useState<number | "all">("all");

  // Form panel
  const [panelOpen, setPanelOpen] = useState(false);
  const [editingStoryline, setEditingStoryline] = useState<StorylineListItem | null>(null);
  const [form, setForm] = useState<StorylineFormData>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Data fetching
  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const params: Parameters<typeof api.storylines.list>[0] = {};
      if (filterType !== "all") params.storyline_type = filterType;
      if (filterStatus !== "all") params.status = filterStatus;
      if (filterCharacter !== "all") params.character_id = filterCharacter;

      const [storylinesData, charsData] = await Promise.all([
        api.storylines.list(params),
        api.characters.list(),
      ]);

      setStorylines(storylinesData);
      setCharacters(charsData);
      setError(null);
    } catch (err) {
      console.error("Failed to fetch storylines:", err);
      setError(err instanceof Error ? err.message : "Failed to load storylines");
    } finally {
      setLoading(false);
    }
  }, [filterType, filterStatus, filterCharacter]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Panel open/close
  function openCreatePanel() {
    setEditingStoryline(null);
    setForm(emptyForm);
    setFormError(null);
    setPanelOpen(true);
  }

  function openEditPanel(s: StorylineListItem) {
    setEditingStoryline(s);
    setForm(storylineToForm(s));
    setFormError(null);
    setPanelOpen(true);
  }

  function closePanel() {
    setPanelOpen(false);
    setEditingStoryline(null);
    setFormError(null);
  }

  // Save
  async function handleSave() {
    if (!form.title.trim()) {
      setFormError("Title is required");
      return;
    }
    if (!form.description.trim()) {
      setFormError("Description is required");
      return;
    }

    try {
      setSaving(true);
      setFormError(null);

      const payload = {
        title: form.title,
        description: form.description,
        storyline_type: form.storyline_type,
        status: form.status,
        priority: form.priority,
        comedy_notes: form.comedy_notes || null,
        tags: form.tags
          ? form.tags.split(",").map((t) => t.trim()).filter(Boolean)
          : null,
        character_ids: form.character_ids,
        plot_points: form.plot_points.length > 0 ? form.plot_points : null,
      };

      if (editingStoryline) {
        await api.storylines.update(editingStoryline.id, payload);
      } else {
        await api.storylines.create(payload);
      }

      closePanel();
      await fetchData();
    } catch (err) {
      console.error("Failed to save storyline:", err);
      setFormError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  // Archive
  async function handleArchive(storyline: StorylineListItem) {
    try {
      await api.storylines.delete(storyline.id);
      await fetchData();
    } catch (err) {
      console.error("Failed to archive storyline:", err);
      setError(err instanceof Error ? err.message : "Failed to archive storyline");
    }
  }

  // Form field updater
  function updateField<K extends keyof StorylineFormData>(key: K, value: StorylineFormData[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  // Plot points management
  function addPlotPoint() {
    setForm((prev) => ({
      ...prev,
      plot_points: [...prev.plot_points, { title: "", description: "", completed: false }],
    }));
  }

  function updatePlotPoint(index: number, field: keyof PlotPoint, value: string | boolean) {
    setForm((prev) => {
      const updated = [...prev.plot_points];
      updated[index] = { ...updated[index], [field]: value };
      return { ...prev, plot_points: updated };
    });
  }

  function removePlotPoint(index: number) {
    setForm((prev) => ({
      ...prev,
      plot_points: prev.plot_points.filter((_, i) => i !== index),
    }));
  }

  // Character multi-select toggle
  function toggleCharacter(charId: number) {
    setForm((prev) => ({
      ...prev,
      character_ids: prev.character_ids.includes(charId)
        ? prev.character_ids.filter((id) => id !== charId)
        : [...prev.character_ids, charId],
    }));
  }

  // Styles
  const selectClass =
    "w-full rounded-lg border border-white/10 bg-twilight/50 px-3 py-2 text-sm text-white placeholder-white/30 focus:border-neon-cyan/50 focus:outline-none focus:ring-1 focus:ring-neon-cyan/50 transition-colors";
  const inputClass = selectClass;
  const textareaClass =
    "w-full rounded-lg border border-white/10 bg-twilight/50 px-3 py-2 text-sm text-white placeholder-white/30 focus:border-neon-cyan/50 focus:outline-none focus:ring-1 focus:ring-neon-cyan/50 transition-colors resize-none";
  const labelClass = "block text-sm font-medium text-white/70 mb-1";

  if (loading && storylines.length === 0) {
    return <LoadingPage text="Loading storylines..." />;
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <Header
        title="Storylines"
        subtitle="Manage narrative arcs, rivalries, and season-long plots"
        actions={
          <Button onClick={openCreatePanel}>
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            New Storyline
          </Button>
        }
      />

      {/* Error banner */}
      {error && (
        <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-4">
          <p className="text-racing-red">{error}</p>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-white/40 uppercase tracking-wider">Type</label>
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value as StorylineType | "all")}
            className="rounded-lg border border-white/10 bg-twilight/50 px-3 py-2 text-sm text-white focus:border-neon-cyan/50 focus:outline-none focus:ring-1 focus:ring-neon-cyan/50 transition-colors"
          >
            <option value="all">All Types</option>
            {TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-white/40 uppercase tracking-wider">Status</label>
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value as StorylineStatus | "all")}
            className="rounded-lg border border-white/10 bg-twilight/50 px-3 py-2 text-sm text-white focus:border-neon-cyan/50 focus:outline-none focus:ring-1 focus:ring-neon-cyan/50 transition-colors"
          >
            <option value="all">All Statuses</option>
            {STATUSES.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-white/40 uppercase tracking-wider">Character</label>
          <select
            value={filterCharacter}
            onChange={(e) => {
              const v = e.target.value;
              setFilterCharacter(v === "all" ? "all" : Number(v));
            }}
            className="rounded-lg border border-white/10 bg-twilight/50 px-3 py-2 text-sm text-white focus:border-neon-cyan/50 focus:outline-none focus:ring-1 focus:ring-neon-cyan/50 transition-colors"
          >
            <option value="all">All Characters</option>
            {characters
              .filter((c) => c.is_active)
              .map((c) => (
                <option key={c.id} value={c.id}>{c.display_name || c.name}</option>
              ))}
          </select>
        </div>

        <div className="ml-auto">
          <span className="font-mono text-sm text-white/40">
            {storylines.length} storyline{storylines.length !== 1 ? "s" : ""}
          </span>
        </div>
      </div>

      {/* Storyline cards */}
      {storylines.length === 0 ? (
        <Card className="p-12 text-center">
          <svg className="mx-auto h-12 w-12 text-white/20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          <h3 className="mt-4 text-lg font-medium text-white">No storylines found</h3>
          <p className="mt-2 text-white/60">
            {filterType !== "all" || filterStatus !== "all" || filterCharacter !== "all"
              ? "Try adjusting your filters or create a new storyline."
              : "Create your first storyline to start building narrative arcs."}
          </p>
          <Button className="mt-6" onClick={openCreatePanel}>
            New Storyline
          </Button>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
          {storylines.map((storyline) => {
            const plotPoints = storyline.plot_points ?? [];
            const totalBeats = plotPoints.length;
            const completedBeats = plotPoints.filter((p) => p.completed).length;

            return (
              <Card key={storyline.id} className="flex flex-col p-0 overflow-hidden" hover>
                <div className="flex-1 p-5">
                  {/* Badges */}
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={cn("rounded px-2 py-0.5 text-xs font-medium", typeColors[storyline.storyline_type])}>
                      {typeLabel(storyline.storyline_type)}
                    </span>
                    <span className={cn("rounded px-2 py-0.5 text-xs font-medium", statusColors[storyline.status])}>
                      {statusLabel(storyline.status)}
                    </span>
                  </div>

                  {/* Title */}
                  <Link href={`/storylines/${storyline.id}`}>
                    <h3 className="mt-3 text-lg font-semibold text-white leading-snug hover:text-neon-cyan transition-colors">
                      {storyline.title}
                    </h3>
                  </Link>

                  {/* Description */}
                  <p className="mt-2 text-sm text-white/60 line-clamp-2">{storyline.description}</p>

                  {/* Characters */}
                  {storyline.characters.length > 0 && (
                    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                      {storyline.characters.map((char) => (
                        <span
                          key={char.id}
                          className="inline-flex items-center gap-1 rounded-full bg-cyber-purple/15 px-2.5 py-1 text-cyber-purple"
                        >
                          <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                          </svg>
                          {char.display_name}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Priority */}
                  <div className="mt-3">
                    <PriorityBar priority={storyline.priority} />
                  </div>

                  {/* Plot progress */}
                  {totalBeats > 0 && (
                    <div className="mt-3">
                      <div className="flex items-center justify-between text-xs text-white/40 mb-1">
                        <span>Plot Progress</span>
                        <span className="font-mono">
                          Beat {storyline.current_beat + 1}/{totalBeats}
                        </span>
                      </div>
                      <div className="h-1.5 w-full rounded-full bg-white/10 overflow-hidden">
                        <div
                          className="h-full rounded-full bg-neon-cyan transition-all"
                          style={{ width: `${totalBeats > 0 ? ((storyline.current_beat + 1) / totalBeats) * 100 : 0}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {/* Stats */}
                  <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-white/40">
                    <span className="font-mono">
                      {storyline.episode_count ?? 0} episode{(storyline.episode_count ?? 0) !== 1 ? "s" : ""}
                    </span>
                    {totalBeats > 0 && (
                      <span className="font-mono">
                        {completedBeats}/{totalBeats} beats done
                      </span>
                    )}
                    <span>Updated {formatRelativeTime(storyline.updated_at)}</span>
                  </div>

                  {/* Tags */}
                  {storyline.tags && storyline.tags.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {storyline.tags.map((tag) => (
                        <span
                          key={tag}
                          className="rounded bg-white/5 px-2 py-0.5 text-[11px] font-medium text-white/50 border border-white/5"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Card footer */}
                <div className="flex items-center justify-between border-t border-white/5 bg-twilight/20 px-5 py-3">
                  <span className="text-xs text-white/30 font-mono">#{storyline.id}</span>
                  <div className="flex gap-2">
                    <Link
                      href={`/storylines/${storyline.id}`}
                      className="rounded-lg px-3 py-1.5 text-xs font-medium text-electric-blue hover:bg-electric-blue/10 transition-colors"
                    >
                      View
                    </Link>
                    <button
                      onClick={() => openEditPanel(storyline)}
                      className="rounded-lg px-3 py-1.5 text-xs font-medium text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
                    >
                      Edit
                    </button>
                    {storyline.status !== "archived" && (
                      <button
                        onClick={() => handleArchive(storyline)}
                        className="rounded-lg px-3 py-1.5 text-xs font-medium text-racing-red hover:bg-racing-red/10 transition-colors"
                      >
                        Archive
                      </button>
                    )}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {/* Slide-over form */}
      <SlideOver
        open={panelOpen}
        onClose={closePanel}
        title={editingStoryline ? `Edit: ${editingStoryline.title}` : "Create Storyline"}
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
                value={form.title}
                onChange={(e) => updateField("title", e.target.value)}
                placeholder="e.g., Verstappen vs. Norris Championship Battle"
                className={inputClass}
              />
            </div>

            <div>
              <label className={labelClass}>Description *</label>
              <textarea
                value={form.description}
                onChange={(e) => updateField("description", e.target.value)}
                placeholder="Describe the narrative arc..."
                rows={3}
                className={textareaClass}
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelClass}>Type</label>
                <select
                  value={form.storyline_type}
                  onChange={(e) => updateField("storyline_type", e.target.value as StorylineType)}
                  className={selectClass}
                >
                  {TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>
              {editingStoryline && (
                <div>
                  <label className={labelClass}>Status</label>
                  <select
                    value={form.status}
                    onChange={(e) => updateField("status", e.target.value as StorylineStatus)}
                    className={selectClass}
                  >
                    {STATUSES.map((s) => (
                      <option key={s.value} value={s.value}>{s.label}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          </fieldset>

          {/* Characters */}
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold text-neon-cyan uppercase tracking-wider mb-2">Characters</legend>
            <p className="text-xs text-white/40">Select characters involved in this storyline</p>
            <div className="grid grid-cols-2 gap-2 max-h-48 overflow-y-auto">
              {characters
                .filter((c) => c.is_active)
                .map((c) => (
                  <label
                    key={c.id}
                    className={cn(
                      "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm cursor-pointer transition-colors",
                      form.character_ids.includes(c.id)
                        ? "border-neon-cyan/50 bg-neon-cyan/10 text-white"
                        : "border-white/10 bg-twilight/30 text-white/60 hover:bg-twilight/50"
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={form.character_ids.includes(c.id)}
                      onChange={() => toggleCharacter(c.id)}
                      className="sr-only"
                    />
                    <div
                      className={cn(
                        "h-4 w-4 rounded border flex items-center justify-center flex-shrink-0",
                        form.character_ids.includes(c.id)
                          ? "border-neon-cyan bg-neon-cyan"
                          : "border-white/30"
                      )}
                    >
                      {form.character_ids.includes(c.id) && (
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
            <p className="text-xs text-white/40">Define the beats of this narrative arc in order</p>

            {form.plot_points.map((point, index) => (
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
                  placeholder="What happens in this beat..."
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
                value={form.comedy_notes}
                onChange={(e) => updateField("comedy_notes", e.target.value)}
                placeholder="Comedy direction, tone, satirical angle..."
                rows={3}
                className={textareaClass}
              />
            </div>

            <div>
              <label className={labelClass}>
                Priority: <span className="font-mono text-neon-cyan">{form.priority}/10</span>
              </label>
              <input
                type="range"
                min={1}
                max={10}
                step={1}
                value={form.priority}
                onChange={(e) => updateField("priority", Number(e.target.value))}
                className="w-full accent-neon-cyan"
              />
              <div className="flex justify-between text-[10px] text-white/30 mt-0.5">
                <span>Low</span>
                <span>Medium</span>
                <span>Must Include</span>
              </div>
            </div>

            <div>
              <label className={labelClass}>Tags</label>
              <input
                type="text"
                value={form.tags}
                onChange={(e) => updateField("tags", e.target.value)}
                placeholder="e.g., championship, drama, team-orders"
                className={inputClass}
              />
              <p className="mt-1 text-[11px] text-white/30">Comma-separated</p>
            </div>
          </fieldset>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 border-t border-white/10 pt-6">
            <Button variant="secondary" onClick={closePanel} disabled={saving}>
              Cancel
            </Button>
            <Button onClick={handleSave} loading={saving}>
              {editingStoryline ? "Save Changes" : "Create Storyline"}
            </Button>
          </div>
        </div>
      </SlideOver>
    </div>
  );
}
