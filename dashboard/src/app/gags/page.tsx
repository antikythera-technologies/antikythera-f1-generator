"use client";

import { useEffect, useState, useCallback } from "react";
import { api, type RunningGag, type Character, type GagCategory, type GagStatus } from "@/lib/api";
import { formatRelativeTime, cn } from "@/lib/utils";
import { Header } from "@/components/layout/Header";
import { Button, Card, LoadingPage } from "@/components/ui";

// ---------------------------------------------------------------------------
// Constants & helpers
// ---------------------------------------------------------------------------

const CATEGORIES: { value: GagCategory; label: string }[] = [
  { value: "personality_trait", label: "Personality Trait" },
  { value: "incident", label: "Incident" },
  { value: "rivalry", label: "Rivalry" },
  { value: "catchphrase", label: "Catchphrase" },
  { value: "running_joke", label: "Running Joke" },
  { value: "relationship", label: "Relationship" },
  { value: "legacy", label: "Legacy" },
];

const STATUSES: { value: GagStatus; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "cooling_down", label: "Cooling Down" },
  { value: "exhausted", label: "Exhausted" },
  { value: "retired", label: "Retired" },
];

const categoryColors: Record<GagCategory, string> = {
  personality_trait: "bg-cyber-purple/20 text-cyber-purple",
  incident: "bg-warning-orange/20 text-warning-orange",
  rivalry: "bg-racing-red/20 text-racing-red",
  catchphrase: "bg-neon-cyan/20 text-neon-cyan",
  running_joke: "bg-electric-blue/20 text-electric-blue",
  relationship: "bg-success-green/20 text-success-green",
  legacy: "bg-yellow-500/20 text-yellow-400",
};

const categoryLabel = (cat: GagCategory): string =>
  CATEGORIES.find((c) => c.value === cat)?.label ?? cat;

const statusColors: Record<GagStatus, string> = {
  active: "bg-success-green/20 text-success-green",
  cooling_down: "bg-yellow-500/20 text-yellow-400",
  exhausted: "bg-white/10 text-white/40",
  retired: "bg-racing-red/20 text-racing-red",
};

const statusLabel = (s: GagStatus): string =>
  STATUSES.find((st) => st.value === s)?.label ?? s;

// ---------------------------------------------------------------------------
// Form data shape
// ---------------------------------------------------------------------------

interface GagFormData {
  title: string;
  description: string;
  category: GagCategory;
  primary_character_id: number | null;
  secondary_character_id: number | null;
  setup: string;
  punchline: string;
  variations: string;
  context_needed: string;
  origin_race: string;
  origin_date: string;
  origin_description: string;
  status: GagStatus;
  humor_rating: number;
  cooldown_races: number;
  max_uses: string; // kept as string for easy empty-state handling
  tags: string; // comma-separated
}

const emptyForm: GagFormData = {
  title: "",
  description: "",
  category: "running_joke",
  primary_character_id: null,
  secondary_character_id: null,
  setup: "",
  punchline: "",
  variations: "",
  context_needed: "",
  origin_race: "",
  origin_date: "",
  origin_description: "",
  status: "active",
  humor_rating: 5,
  cooldown_races: 3,
  max_uses: "",
  tags: "",
};

function gagToForm(gag: RunningGag): GagFormData {
  return {
    title: gag.title,
    description: gag.description,
    category: gag.category,
    primary_character_id: gag.primary_character_id,
    secondary_character_id: gag.secondary_character_id,
    setup: gag.setup ?? "",
    punchline: gag.punchline ?? "",
    variations: gag.variations ?? "",
    context_needed: gag.context_needed ?? "",
    origin_race: gag.origin_race ?? "",
    origin_date: gag.origin_date ?? "",
    origin_description: gag.origin_description ?? "",
    status: gag.status,
    humor_rating: gag.humor_rating,
    cooldown_races: gag.cooldown_races,
    max_uses: gag.max_uses != null ? String(gag.max_uses) : "",
    tags: gag.tags?.join(", ") ?? "",
  };
}

function formToPayload(form: GagFormData): Partial<RunningGag> {
  return {
    title: form.title,
    description: form.description,
    category: form.category,
    primary_character_id: form.primary_character_id || null,
    secondary_character_id: form.secondary_character_id || null,
    setup: form.setup || null,
    punchline: form.punchline || null,
    variations: form.variations || null,
    context_needed: form.context_needed || null,
    origin_race: form.origin_race || null,
    origin_date: form.origin_date || null,
    origin_description: form.origin_description || null,
    status: form.status,
    humor_rating: form.humor_rating,
    cooldown_races: form.cooldown_races,
    max_uses: form.max_uses ? Number(form.max_uses) : null,
    tags: form.tags
      ? form.tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean)
      : null,
  };
}

// ---------------------------------------------------------------------------
// Humor rating bar component
// ---------------------------------------------------------------------------

function HumorBar({ rating }: { rating: number }) {
  return (
    <div className="flex items-center gap-1.5">
      <div className="flex gap-px">
        {Array.from({ length: 10 }).map((_, i) => (
          <div
            key={i}
            className={cn(
              "h-3 w-1.5 rounded-sm transition-colors",
              i < rating
                ? rating >= 8
                  ? "bg-success-green"
                  : rating >= 5
                    ? "bg-neon-cyan"
                    : "bg-yellow-400"
                : "bg-white/10"
            )}
          />
        ))}
      </div>
      <span className="ml-1 font-mono text-xs text-white/50">{rating}/10</span>
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
  // Prevent body scroll when open
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
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-deep-space/70 backdrop-blur-sm"
        onClick={onClose}
      />
      {/* Panel */}
      <div className="relative z-10 flex h-full w-full max-w-2xl flex-col border-l border-white/10 bg-midnight/95 backdrop-blur-xl shadow-2xl">
        {/* Header */}
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
        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-6">
          {children}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Delete confirmation dialog
// ---------------------------------------------------------------------------

function DeleteDialog({
  open,
  gagTitle,
  onConfirm,
  onCancel,
  deleting,
}: {
  open: boolean;
  gagTitle: string;
  onConfirm: () => void;
  onCancel: () => void;
  deleting: boolean;
}) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-deep-space/70 backdrop-blur-sm"
        onClick={onCancel}
      />
      <div className="relative z-10 w-full max-w-md rounded-xl border border-white/10 bg-midnight/95 p-6 shadow-2xl backdrop-blur-xl">
        <div className="flex items-start gap-4">
          <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-racing-red/20">
            <svg className="h-5 w-5 text-racing-red" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white">Delete Running Gag</h3>
            <p className="mt-2 text-sm text-white/60">
              Are you sure you want to delete <span className="font-medium text-white">&quot;{gagTitle}&quot;</span>?
              This action cannot be undone. All usage history will be permanently removed.
            </p>
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={deleting}>
            Cancel
          </Button>
          <Button variant="danger" size="sm" onClick={onConfirm} loading={deleting}>
            Delete Gag
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function GagsPage() {
  // Data
  const [gags, setGags] = useState<RunningGag[]>([]);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [filterCategory, setFilterCategory] = useState<GagCategory | "all">("all");
  const [filterStatus, setFilterStatus] = useState<GagStatus | "all">("all");
  const [filterCharacter, setFilterCharacter] = useState<number | "all">("all");

  // Form panel
  const [panelOpen, setPanelOpen] = useState(false);
  const [editingGag, setEditingGag] = useState<RunningGag | null>(null);
  const [form, setForm] = useState<GagFormData>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Delete dialog
  const [deleteTarget, setDeleteTarget] = useState<RunningGag | null>(null);
  const [deleting, setDeleting] = useState(false);

  // ---- Data fetching --------------------------------------------------

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const params: Parameters<typeof api.gags.list>[0] = {};
      if (filterCategory !== "all") params.category = filterCategory;
      if (filterStatus !== "all") params.status = filterStatus;
      if (filterCharacter !== "all") params.character_id = filterCharacter;

      const [gagsData, charsData] = await Promise.all([
        api.gags.list(params),
        api.characters.list(),
      ]);

      setGags(gagsData);
      setCharacters(charsData);
      setError(null);
    } catch (err) {
      console.error("Failed to fetch gags:", err);
      setError(err instanceof Error ? err.message : "Failed to load running gags");
    } finally {
      setLoading(false);
    }
  }, [filterCategory, filterStatus, filterCharacter]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // ---- Helpers --------------------------------------------------------

  const charName = (id: number | null): string | null => {
    if (id == null) return null;
    const c = characters.find((ch) => ch.id === id);
    return c ? c.display_name || c.name : `#${id}`;
  };

  // ---- Panel open/close -----------------------------------------------

  function openCreatePanel() {
    setEditingGag(null);
    setForm(emptyForm);
    setFormError(null);
    setPanelOpen(true);
  }

  function openEditPanel(gag: RunningGag) {
    setEditingGag(gag);
    setForm(gagToForm(gag));
    setFormError(null);
    setPanelOpen(true);
  }

  function closePanel() {
    setPanelOpen(false);
    setEditingGag(null);
    setFormError(null);
  }

  // ---- Save -----------------------------------------------------------

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
      const payload = formToPayload(form);

      if (editingGag) {
        await api.gags.update(editingGag.id, payload);
      } else {
        await api.gags.create(payload);
      }

      closePanel();
      await fetchData();
    } catch (err) {
      console.error("Failed to save gag:", err);
      setFormError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  // ---- Delete ---------------------------------------------------------

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      setDeleting(true);
      await api.gags.delete(deleteTarget.id);
      setDeleteTarget(null);
      await fetchData();
    } catch (err) {
      console.error("Failed to delete gag:", err);
      setError(err instanceof Error ? err.message : "Failed to delete gag");
    } finally {
      setDeleting(false);
    }
  }

  // ---- Form field updater ---------------------------------------------

  function updateField<K extends keyof GagFormData>(key: K, value: GagFormData[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  // ---- Select styles --------------------------------------------------

  const selectClass =
    "w-full rounded-lg border border-white/10 bg-twilight/50 px-3 py-2 text-sm text-white placeholder-white/30 focus:border-neon-cyan/50 focus:outline-none focus:ring-1 focus:ring-neon-cyan/50 transition-colors";

  const inputClass = selectClass;

  const textareaClass =
    "w-full rounded-lg border border-white/10 bg-twilight/50 px-3 py-2 text-sm text-white placeholder-white/30 focus:border-neon-cyan/50 focus:outline-none focus:ring-1 focus:ring-neon-cyan/50 transition-colors resize-none";

  const labelClass = "block text-sm font-medium text-white/70 mb-1";

  // ---- Render ---------------------------------------------------------

  if (loading && gags.length === 0) {
    return <LoadingPage text="Loading running gags..." />;
  }

  return (
    <div className="space-y-8">
      {/* ---- Header --------------------------------------------------- */}
      <Header
        title="Running Gags & Character History"
        subtitle="Manage recurring jokes, catchphrases, and character dynamics"
        actions={
          <Button onClick={openCreatePanel}>
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Add Gag
          </Button>
        }
      />

      {/* ---- Error banner --------------------------------------------- */}
      {error && (
        <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-4">
          <p className="text-racing-red">{error}</p>
        </div>
      )}

      {/* ---- Filters -------------------------------------------------- */}
      <div className="flex flex-wrap items-center gap-4">
        {/* Category */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-white/40 uppercase tracking-wider">Category</label>
          <select
            value={filterCategory}
            onChange={(e) => setFilterCategory(e.target.value as GagCategory | "all")}
            className="rounded-lg border border-white/10 bg-twilight/50 px-3 py-2 text-sm text-white focus:border-neon-cyan/50 focus:outline-none focus:ring-1 focus:ring-neon-cyan/50 transition-colors"
          >
            <option value="all">All Categories</option>
            {CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
        </div>

        {/* Status */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-white/40 uppercase tracking-wider">Status</label>
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value as GagStatus | "all")}
            className="rounded-lg border border-white/10 bg-twilight/50 px-3 py-2 text-sm text-white focus:border-neon-cyan/50 focus:outline-none focus:ring-1 focus:ring-neon-cyan/50 transition-colors"
          >
            <option value="all">All Statuses</option>
            {STATUSES.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>

        {/* Character */}
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

        {/* Result count */}
        <div className="ml-auto">
          <span className="font-mono text-sm text-white/40">
            {gags.length} gag{gags.length !== 1 ? "s" : ""}
          </span>
        </div>
      </div>

      {/* ---- Gag cards ------------------------------------------------ */}
      {gags.length === 0 ? (
        <Card className="p-12 text-center">
          <svg className="mx-auto h-12 w-12 text-white/20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <h3 className="mt-4 text-lg font-medium text-white">No running gags found</h3>
          <p className="mt-2 text-white/60">
            {filterCategory !== "all" || filterStatus !== "all" || filterCharacter !== "all"
              ? "Try adjusting your filters or add a new gag."
              : "Create your first running gag to get started."}
          </p>
          <Button className="mt-6" onClick={openCreatePanel}>
            Add Gag
          </Button>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
          {gags.map((gag) => {
            const primary = charName(gag.primary_character_id);
            const secondary = charName(gag.secondary_character_id);

            return (
              <Card key={gag.id} className="flex flex-col p-0 overflow-hidden" hover>
                {/* Card top section */}
                <div className="flex-1 p-5">
                  {/* Badges row */}
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={cn("rounded px-2 py-0.5 text-xs font-medium", categoryColors[gag.category])}>
                      {categoryLabel(gag.category)}
                    </span>
                    <span className={cn("rounded px-2 py-0.5 text-xs font-medium", statusColors[gag.status])}>
                      {statusLabel(gag.status)}
                    </span>
                  </div>

                  {/* Title */}
                  <h3 className="mt-3 text-lg font-semibold text-white leading-snug">{gag.title}</h3>

                  {/* Description */}
                  <p className="mt-2 text-sm text-white/60 line-clamp-2">{gag.description}</p>

                  {/* Characters */}
                  {(primary || secondary) && (
                    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                      {primary && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-cyber-purple/15 px-2.5 py-1 text-cyber-purple">
                          <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                          </svg>
                          {primary}
                        </span>
                      )}
                      {secondary && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-electric-blue/15 px-2.5 py-1 text-electric-blue">
                          <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                          </svg>
                          {secondary}
                        </span>
                      )}
                    </div>
                  )}

                  {/* Humor rating */}
                  <div className="mt-3">
                    <HumorBar rating={gag.humor_rating} />
                  </div>

                  {/* Stats row */}
                  <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-white/40">
                    <span className="font-mono">
                      Used: {gag.times_used}{gag.max_uses != null ? `/${gag.max_uses}` : ""}
                    </span>
                    <span className="font-mono">
                      Cooldown: {gag.cooldown_races} race{gag.cooldown_races !== 1 ? "s" : ""}
                    </span>
                    {gag.last_used_at && (
                      <span>
                        Last: {formatRelativeTime(gag.last_used_at)}
                      </span>
                    )}
                    {gag.last_used_in_race && (
                      <span>
                        @ {gag.last_used_in_race}
                      </span>
                    )}
                  </div>

                  {/* Tags */}
                  {gag.tags && gag.tags.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {gag.tags.map((tag) => (
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

                {/* Card footer with actions */}
                <div className="flex items-center justify-between border-t border-white/5 bg-twilight/20 px-5 py-3">
                  <span className="text-xs text-white/30 font-mono">
                    #{gag.id}
                    {gag.usages.length > 0 && (
                      <span className="ml-2">{gag.usages.length} usage{gag.usages.length !== 1 ? "s" : ""}</span>
                    )}
                  </span>
                  <div className="flex gap-2">
                    <button
                      onClick={() => openEditPanel(gag)}
                      className="rounded-lg px-3 py-1.5 text-xs font-medium text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => setDeleteTarget(gag)}
                      className="rounded-lg px-3 py-1.5 text-xs font-medium text-racing-red hover:bg-racing-red/10 transition-colors"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {/* ---- Slide-over form ------------------------------------------ */}
      <SlideOver
        open={panelOpen}
        onClose={closePanel}
        title={editingGag ? `Edit: ${editingGag.title}` : "Create Running Gag"}
      >
        <div className="space-y-6">
          {/* Form error */}
          {formError && (
            <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-3">
              <p className="text-sm text-racing-red">{formError}</p>
            </div>
          )}

          {/* ---- Basic info ---- */}
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold text-neon-cyan uppercase tracking-wider mb-2">Basic Information</legend>

            <div>
              <label className={labelClass}>Title *</label>
              <input
                type="text"
                value={form.title}
                onChange={(e) => updateField("title", e.target.value)}
                placeholder="e.g., Kimi's Radio Silence"
                className={inputClass}
              />
            </div>

            <div>
              <label className={labelClass}>Description *</label>
              <textarea
                value={form.description}
                onChange={(e) => updateField("description", e.target.value)}
                placeholder="Brief description of this running gag..."
                rows={3}
                className={textareaClass}
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelClass}>Category</label>
                <select
                  value={form.category}
                  onChange={(e) => updateField("category", e.target.value as GagCategory)}
                  className={selectClass}
                >
                  {CATEGORIES.map((c) => (
                    <option key={c.value} value={c.value}>{c.label}</option>
                  ))}
                </select>
              </div>
              {editingGag && (
                <div>
                  <label className={labelClass}>Status</label>
                  <select
                    value={form.status}
                    onChange={(e) => updateField("status", e.target.value as GagStatus)}
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

          {/* ---- Characters ---- */}
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold text-neon-cyan uppercase tracking-wider mb-2">Characters</legend>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelClass}>Primary Character</label>
                <select
                  value={form.primary_character_id ?? ""}
                  onChange={(e) =>
                    updateField("primary_character_id", e.target.value ? Number(e.target.value) : null)
                  }
                  className={selectClass}
                >
                  <option value="">None</option>
                  {characters.map((c) => (
                    <option key={c.id} value={c.id}>{c.display_name || c.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelClass}>Secondary Character</label>
                <select
                  value={form.secondary_character_id ?? ""}
                  onChange={(e) =>
                    updateField("secondary_character_id", e.target.value ? Number(e.target.value) : null)
                  }
                  className={selectClass}
                >
                  <option value="">None</option>
                  {characters.map((c) => (
                    <option key={c.id} value={c.id}>{c.display_name || c.name}</option>
                  ))}
                </select>
              </div>
            </div>
          </fieldset>

          {/* ---- Comedy structure ---- */}
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold text-neon-cyan uppercase tracking-wider mb-2">Comedy Structure</legend>

            <div>
              <label className={labelClass}>Setup</label>
              <textarea
                value={form.setup}
                onChange={(e) => updateField("setup", e.target.value)}
                placeholder="The setup or premise of the joke..."
                rows={2}
                className={textareaClass}
              />
            </div>

            <div>
              <label className={labelClass}>Punchline</label>
              <textarea
                value={form.punchline}
                onChange={(e) => updateField("punchline", e.target.value)}
                placeholder="The punchline or payoff..."
                rows={2}
                className={textareaClass}
              />
            </div>

            <div>
              <label className={labelClass}>Variations</label>
              <textarea
                value={form.variations}
                onChange={(e) => updateField("variations", e.target.value)}
                placeholder="Different ways this gag can be delivered..."
                rows={3}
                className={textareaClass}
              />
            </div>

            <div>
              <label className={labelClass}>Context Needed</label>
              <textarea
                value={form.context_needed}
                onChange={(e) => updateField("context_needed", e.target.value)}
                placeholder="What context does the audience need to understand this gag?"
                rows={2}
                className={textareaClass}
              />
            </div>
          </fieldset>

          {/* ---- Origin ---- */}
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold text-neon-cyan uppercase tracking-wider mb-2">Origin</legend>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelClass}>Origin Race</label>
                <input
                  type="text"
                  value={form.origin_race}
                  onChange={(e) => updateField("origin_race", e.target.value)}
                  placeholder="e.g., Monaco GP 2025"
                  className={inputClass}
                />
              </div>
              <div>
                <label className={labelClass}>Origin Date</label>
                <input
                  type="date"
                  value={form.origin_date}
                  onChange={(e) => updateField("origin_date", e.target.value)}
                  className={inputClass}
                />
              </div>
            </div>

            <div>
              <label className={labelClass}>Origin Description</label>
              <textarea
                value={form.origin_description}
                onChange={(e) => updateField("origin_description", e.target.value)}
                placeholder="How this gag originated..."
                rows={2}
                className={textareaClass}
              />
            </div>
          </fieldset>

          {/* ---- Tuning ---- */}
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold text-neon-cyan uppercase tracking-wider mb-2">Tuning</legend>

            {/* Humor rating slider */}
            <div>
              <label className={labelClass}>
                Humor Rating: <span className="font-mono text-neon-cyan">{form.humor_rating}/10</span>
              </label>
              <input
                type="range"
                min={1}
                max={10}
                step={1}
                value={form.humor_rating}
                onChange={(e) => updateField("humor_rating", Number(e.target.value))}
                className="w-full accent-neon-cyan"
              />
              <div className="flex justify-between text-[10px] text-white/30 mt-0.5">
                <span>Mild</span>
                <span>Medium</span>
                <span>Hilarious</span>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelClass}>Cooldown Races</label>
                <input
                  type="number"
                  min={0}
                  value={form.cooldown_races}
                  onChange={(e) => updateField("cooldown_races", Number(e.target.value) || 0)}
                  className={inputClass}
                />
                <p className="mt-1 text-[11px] text-white/30">Minimum races between uses</p>
              </div>
              <div>
                <label className={labelClass}>Max Uses</label>
                <input
                  type="number"
                  min={1}
                  value={form.max_uses}
                  onChange={(e) => updateField("max_uses", e.target.value)}
                  placeholder="Unlimited"
                  className={inputClass}
                />
                <p className="mt-1 text-[11px] text-white/30">Leave empty for unlimited</p>
              </div>
            </div>

            <div>
              <label className={labelClass}>Tags</label>
              <input
                type="text"
                value={form.tags}
                onChange={(e) => updateField("tags", e.target.value)}
                placeholder="e.g., radio, team-orders, pit-strategy"
                className={inputClass}
              />
              <p className="mt-1 text-[11px] text-white/30">Comma-separated</p>
            </div>
          </fieldset>

          {/* ---- Actions ---- */}
          <div className="flex items-center justify-end gap-3 border-t border-white/10 pt-6">
            <Button variant="secondary" onClick={closePanel} disabled={saving}>
              Cancel
            </Button>
            <Button onClick={handleSave} loading={saving}>
              {editingGag ? "Save Changes" : "Create Gag"}
            </Button>
          </div>
        </div>
      </SlideOver>

      {/* ---- Delete dialog -------------------------------------------- */}
      <DeleteDialog
        open={deleteTarget !== null}
        gagTitle={deleteTarget?.title ?? ""}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
        deleting={deleting}
      />
    </div>
  );
}
