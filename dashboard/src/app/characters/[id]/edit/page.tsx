"use client";

import { useEffect, useState, FormEvent } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api, Character } from "@/lib/api";
import { Header } from "@/components/layout/Header";
import { Button, LoadingPage, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";

const ROLE_OPTIONS = [
  { value: "", label: "Select a role..." },
  { value: "driver", label: "Driver" },
  { value: "team_principal", label: "Team Principal" },
  { value: "commentator", label: "Commentator" },
  { value: "presenter", label: "Presenter" },
  { value: "pundit", label: "Pundit" },
  { value: "executive", label: "Executive" },
];

const BACKGROUND_TYPE_OPTIONS = [
  { value: "", label: "Select background type..." },
  { value: "orange_gradient", label: "Orange Gradient" },
  { value: "team_logo", label: "Team Logo" },
  { value: "custom", label: "Custom" },
];

interface FormData {
  name: string;
  display_name: string;
  description: string;
  voice_description: string;
  personality: string;
  is_active: boolean;
  role: string;
  team: string;
  nationality: string;
  physical_features: string;
  comedy_angle: string;
  signature_expression: string;
  signature_pose: string;
  props: string;
  background_type: string;
  background_detail: string;
  clothing_description: string;
}

function characterToFormData(character: Character): FormData {
  return {
    name: character.name ?? "",
    display_name: character.display_name ?? "",
    description: character.description ?? "",
    voice_description: character.voice_description ?? "",
    personality: character.personality ?? "",
    is_active: character.is_active,
    role: character.role ?? "",
    team: character.team ?? "",
    nationality: character.nationality ?? "",
    physical_features: character.physical_features ?? "",
    comedy_angle: character.comedy_angle ?? "",
    signature_expression: character.signature_expression ?? "",
    signature_pose: character.signature_pose ?? "",
    props: character.props ?? "",
    background_type: character.background_type ?? "",
    background_detail: character.background_detail ?? "",
    clothing_description: character.clothing_description ?? "",
  };
}

function formDataToPayload(form: FormData): Partial<Character> {
  return {
    name: form.name,
    display_name: form.display_name,
    description: form.description || null,
    voice_description: form.voice_description || null,
    personality: form.personality || null,
    is_active: form.is_active,
    role: form.role || null,
    team: form.team || null,
    nationality: form.nationality || null,
    physical_features: form.physical_features || null,
    comedy_angle: form.comedy_angle || null,
    signature_expression: form.signature_expression || null,
    signature_pose: form.signature_pose || null,
    props: form.props || null,
    background_type: form.background_type || null,
    background_detail: form.background_detail || null,
    clothing_description: form.clothing_description || null,
  };
}

export default function CharacterEditPage() {
  const params = useParams();
  const router = useRouter();
  const characterId = Number(params.id);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const [form, setForm] = useState<FormData>({
    name: "",
    display_name: "",
    description: "",
    voice_description: "",
    personality: "",
    is_active: true,
    role: "",
    team: "",
    nationality: "",
    physical_features: "",
    comedy_angle: "",
    signature_expression: "",
    signature_pose: "",
    props: "",
    background_type: "",
    background_detail: "",
    clothing_description: "",
  });

  useEffect(() => {
    async function fetchCharacter() {
      try {
        const data = await api.characters.get(characterId);
        setForm(characterToFormData(data));
      } catch (err) {
        console.error("Failed to fetch character:", err);
        setError(err instanceof Error ? err.message : "Failed to load character");
      } finally {
        setLoading(false);
      }
    }

    fetchCharacter();
  }, [characterId]);

  // Auto-dismiss toast after 4 seconds
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 4000);
      return () => clearTimeout(timer);
    }
  }, [toast]);

  function updateField<K extends keyof FormData>(key: K, value: FormData[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();

    if (!form.name.trim()) {
      setToast({ type: "error", message: "Name is required." });
      return;
    }
    if (!form.display_name.trim()) {
      setToast({ type: "error", message: "Display name is required." });
      return;
    }

    setSaving(true);
    setToast(null);

    try {
      await api.characters.update(characterId, formDataToPayload(form));
      setToast({ type: "success", message: "Character updated successfully." });
    } catch (err) {
      console.error("Failed to update character:", err);
      setToast({
        type: "error",
        message: err instanceof Error ? err.message : "Failed to update character.",
      });
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <LoadingPage text="Loading character..." />;
  }

  if (error) {
    return (
      <div className="space-y-4">
        <Header title="Character Not Found" />
        <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-6 text-center">
          <p className="text-racing-red">{error}</p>
          <Link href="/characters" className="mt-4 inline-block">
            <Button variant="secondary">Back to Characters</Button>
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Toast notification */}
      {toast && (
        <div
          className={`fixed right-8 top-8 z-50 flex items-center gap-3 rounded-lg border px-5 py-3 shadow-lg backdrop-blur-md transition-all duration-300 ${
            toast.type === "success"
              ? "border-neon-cyan/50 bg-neon-cyan/10 text-neon-cyan"
              : "border-racing-red/50 bg-racing-red/10 text-racing-red"
          }`}
        >
          {toast.type === "success" ? (
            <svg className="h-5 w-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          ) : (
            <svg className="h-5 w-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          )}
          <span className="text-sm font-medium">{toast.message}</span>
          <button onClick={() => setToast(null)} className="ml-2 opacity-60 hover:opacity-100">
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}

      <Header
        title={`Edit Character: ${form.display_name || form.name}`}
        actions={
          <div className="flex items-center gap-3">
            <Link href={`/characters/${characterId}`}>
              <Button variant="ghost">
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                </svg>
                Back
              </Button>
            </Link>
          </div>
        }
      />

      <form onSubmit={handleSubmit}>
        <div className="grid gap-8 lg:grid-cols-2">
          {/* ========== LEFT COLUMN: Basic Info ========== */}
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Basic Info</CardTitle>
              </CardHeader>
              <CardContent className="space-y-5">
                {/* Name */}
                <div>
                  <label htmlFor="name" className="mb-1.5 block text-sm font-medium text-white/70">
                    Name <span className="text-racing-red">*</span>
                  </label>
                  <input
                    id="name"
                    type="text"
                    required
                    value={form.name}
                    onChange={(e) => updateField("name", e.target.value)}
                    placeholder="e.g. max_verstappen"
                    className="w-full rounded-lg border border-white/10 bg-twilight/50 px-4 py-2.5 text-sm text-white placeholder-white/30 transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-2 focus:ring-neon-cyan/20"
                  />
                </div>

                {/* Display Name */}
                <div>
                  <label htmlFor="display_name" className="mb-1.5 block text-sm font-medium text-white/70">
                    Display Name <span className="text-racing-red">*</span>
                  </label>
                  <input
                    id="display_name"
                    type="text"
                    required
                    value={form.display_name}
                    onChange={(e) => updateField("display_name", e.target.value)}
                    placeholder="e.g. Max Verstappen"
                    className="w-full rounded-lg border border-white/10 bg-twilight/50 px-4 py-2.5 text-sm text-white placeholder-white/30 transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-2 focus:ring-neon-cyan/20"
                  />
                </div>

                {/* Description */}
                <div>
                  <label htmlFor="description" className="mb-1.5 block text-sm font-medium text-white/70">
                    Description
                  </label>
                  <textarea
                    id="description"
                    rows={3}
                    value={form.description}
                    onChange={(e) => updateField("description", e.target.value)}
                    placeholder="Brief character description..."
                    className="w-full rounded-lg border border-white/10 bg-twilight/50 px-4 py-2.5 text-sm text-white placeholder-white/30 transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-2 focus:ring-neon-cyan/20"
                  />
                </div>

                {/* Voice Description */}
                <div>
                  <label htmlFor="voice_description" className="mb-1.5 block text-sm font-medium text-white/70">
                    Voice Description
                  </label>
                  <input
                    id="voice_description"
                    type="text"
                    value={form.voice_description}
                    onChange={(e) => updateField("voice_description", e.target.value)}
                    placeholder="e.g. Deep, confident Dutch accent with occasional dry humor"
                    className="w-full rounded-lg border border-white/10 bg-twilight/50 px-4 py-2.5 text-sm text-white placeholder-white/30 transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-2 focus:ring-neon-cyan/20"
                  />
                </div>

                {/* Personality */}
                <div>
                  <label htmlFor="personality" className="mb-1.5 block text-sm font-medium text-white/70">
                    Personality
                  </label>
                  <textarea
                    id="personality"
                    rows={3}
                    value={form.personality}
                    onChange={(e) => updateField("personality", e.target.value)}
                    placeholder="Character personality traits..."
                    className="w-full rounded-lg border border-white/10 bg-twilight/50 px-4 py-2.5 text-sm text-white placeholder-white/30 transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-2 focus:ring-neon-cyan/20"
                  />
                </div>

                {/* Is Active */}
                <div className="flex items-center gap-3 rounded-lg border border-white/10 bg-twilight/30 px-4 py-3">
                  <label className="relative inline-flex cursor-pointer items-center">
                    <input
                      type="checkbox"
                      checked={form.is_active}
                      onChange={(e) => updateField("is_active", e.target.checked)}
                      className="peer sr-only"
                    />
                    <div className="h-6 w-11 rounded-full bg-white/10 after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:bg-white/50 after:transition-all after:content-[''] peer-checked:bg-neon-cyan/30 peer-checked:after:translate-x-full peer-checked:after:bg-neon-cyan peer-focus:ring-2 peer-focus:ring-neon-cyan/20" />
                  </label>
                  <div>
                    <span className="text-sm font-medium text-white">Active</span>
                    <p className="text-xs text-white/50">Character is available for episode generation</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* ========== RIGHT COLUMN: Caricature Traits + Visual Style ========== */}
          <div className="space-y-6">
            {/* Caricature Traits */}
            <Card>
              <CardHeader>
                <CardTitle>Caricature Traits</CardTitle>
              </CardHeader>
              <CardContent className="space-y-5">
                {/* Role */}
                <div>
                  <label htmlFor="role" className="mb-1.5 block text-sm font-medium text-white/70">
                    Role
                  </label>
                  <select
                    id="role"
                    value={form.role}
                    onChange={(e) => updateField("role", e.target.value)}
                    className="w-full rounded-lg border border-white/10 bg-twilight/50 px-4 py-2.5 text-sm text-white transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-2 focus:ring-neon-cyan/20"
                  >
                    {ROLE_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value} className="bg-midnight text-white">
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Team */}
                <div>
                  <label htmlFor="team" className="mb-1.5 block text-sm font-medium text-white/70">
                    Team
                  </label>
                  <input
                    id="team"
                    type="text"
                    value={form.team}
                    onChange={(e) => updateField("team", e.target.value)}
                    placeholder="e.g. Red Bull Racing"
                    className="w-full rounded-lg border border-white/10 bg-twilight/50 px-4 py-2.5 text-sm text-white placeholder-white/30 transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-2 focus:ring-neon-cyan/20"
                  />
                </div>

                {/* Nationality */}
                <div>
                  <label htmlFor="nationality" className="mb-1.5 block text-sm font-medium text-white/70">
                    Nationality
                  </label>
                  <input
                    id="nationality"
                    type="text"
                    value={form.nationality}
                    onChange={(e) => updateField("nationality", e.target.value)}
                    placeholder="e.g. Dutch"
                    className="w-full rounded-lg border border-white/10 bg-twilight/50 px-4 py-2.5 text-sm text-white placeholder-white/30 transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-2 focus:ring-neon-cyan/20"
                  />
                </div>

                {/* Physical Features */}
                <div>
                  <label htmlFor="physical_features" className="mb-1.5 block text-sm font-medium text-white/70">
                    Physical Features
                  </label>
                  <textarea
                    id="physical_features"
                    rows={3}
                    value={form.physical_features}
                    onChange={(e) => updateField("physical_features", e.target.value)}
                    placeholder="Detailed physical description for caricature generation..."
                    className="w-full rounded-lg border border-white/10 bg-twilight/50 px-4 py-2.5 text-sm text-white placeholder-white/30 transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-2 focus:ring-neon-cyan/20"
                  />
                </div>

                {/* Comedy Angle */}
                <div>
                  <label htmlFor="comedy_angle" className="mb-1.5 block text-sm font-medium text-white/70">
                    Comedy Angle
                  </label>
                  <textarea
                    id="comedy_angle"
                    rows={3}
                    value={form.comedy_angle}
                    onChange={(e) => updateField("comedy_angle", e.target.value)}
                    placeholder="What's funny about this character..."
                    className="w-full rounded-lg border border-white/10 bg-twilight/50 px-4 py-2.5 text-sm text-white placeholder-white/30 transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-2 focus:ring-neon-cyan/20"
                  />
                </div>

                {/* Signature Expression */}
                <div>
                  <label htmlFor="signature_expression" className="mb-1.5 block text-sm font-medium text-white/70">
                    Signature Expression
                  </label>
                  <textarea
                    id="signature_expression"
                    rows={2}
                    value={form.signature_expression}
                    onChange={(e) => updateField("signature_expression", e.target.value)}
                    placeholder="Their typical face expression..."
                    className="w-full rounded-lg border border-white/10 bg-twilight/50 px-4 py-2.5 text-sm text-white placeholder-white/30 transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-2 focus:ring-neon-cyan/20"
                  />
                </div>

                {/* Signature Pose */}
                <div>
                  <label htmlFor="signature_pose" className="mb-1.5 block text-sm font-medium text-white/70">
                    Signature Pose
                  </label>
                  <textarea
                    id="signature_pose"
                    rows={2}
                    value={form.signature_pose}
                    onChange={(e) => updateField("signature_pose", e.target.value)}
                    placeholder="Their typical pose or action..."
                    className="w-full rounded-lg border border-white/10 bg-twilight/50 px-4 py-2.5 text-sm text-white placeholder-white/30 transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-2 focus:ring-neon-cyan/20"
                  />
                </div>

                {/* Props */}
                <div>
                  <label htmlFor="props" className="mb-1.5 block text-sm font-medium text-white/70">
                    Props
                  </label>
                  <input
                    id="props"
                    type="text"
                    value={form.props}
                    onChange={(e) => updateField("props", e.target.value)}
                    placeholder="e.g. trophy, helmet, headset"
                    className="w-full rounded-lg border border-white/10 bg-twilight/50 px-4 py-2.5 text-sm text-white placeholder-white/30 transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-2 focus:ring-neon-cyan/20"
                  />
                </div>
              </CardContent>
            </Card>

            {/* Visual Style */}
            <Card>
              <CardHeader>
                <CardTitle>Visual Style</CardTitle>
              </CardHeader>
              <CardContent className="space-y-5">
                {/* Background Type */}
                <div>
                  <label htmlFor="background_type" className="mb-1.5 block text-sm font-medium text-white/70">
                    Background Type
                  </label>
                  <select
                    id="background_type"
                    value={form.background_type}
                    onChange={(e) => updateField("background_type", e.target.value)}
                    className="w-full rounded-lg border border-white/10 bg-twilight/50 px-4 py-2.5 text-sm text-white transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-2 focus:ring-neon-cyan/20"
                  >
                    {BACKGROUND_TYPE_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value} className="bg-midnight text-white">
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Background Detail */}
                <div>
                  <label htmlFor="background_detail" className="mb-1.5 block text-sm font-medium text-white/70">
                    Background Detail
                  </label>
                  <textarea
                    id="background_detail"
                    rows={3}
                    value={form.background_detail}
                    onChange={(e) => updateField("background_detail", e.target.value)}
                    placeholder="Custom background description..."
                    className="w-full rounded-lg border border-white/10 bg-twilight/50 px-4 py-2.5 text-sm text-white placeholder-white/30 transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-2 focus:ring-neon-cyan/20"
                  />
                </div>

                {/* Clothing Description */}
                <div>
                  <label htmlFor="clothing_description" className="mb-1.5 block text-sm font-medium text-white/70">
                    Clothing Description
                  </label>
                  <textarea
                    id="clothing_description"
                    rows={3}
                    value={form.clothing_description}
                    onChange={(e) => updateField("clothing_description", e.target.value)}
                    placeholder="What they wear..."
                    className="w-full rounded-lg border border-white/10 bg-twilight/50 px-4 py-2.5 text-sm text-white placeholder-white/30 transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-2 focus:ring-neon-cyan/20"
                  />
                </div>
              </CardContent>
            </Card>
          </div>
        </div>

        {/* ========== Form Actions ========== */}
        <div className="mt-8 flex items-center justify-end gap-4 border-t border-white/10 pt-6">
          <Link href={`/characters/${characterId}`}>
            <Button type="button" variant="secondary">
              Cancel
            </Button>
          </Link>
          <Button type="submit" loading={saving}>
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            Save Changes
          </Button>
        </div>
      </form>
    </div>
  );
}
