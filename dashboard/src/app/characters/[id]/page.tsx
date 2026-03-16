"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, Character, CharacterPersonality, FaceReferenceResponse } from "@/lib/api";
import { formatDateTime, getMinioUrl } from "@/lib/utils";
import { Header } from "@/components/layout/Header";
import { Button, LoadingPage, Card, CardContent, CardHeader, CardTitle, StatusBadge } from "@/components/ui";

function DimensionBar({ label, value, max = 10 }: { label: string; value: number; max?: number }) {
  const pct = (value / max) * 100;
  return (
    <div className="flex items-center gap-3">
      <span className="w-24 text-xs text-white/60 capitalize">{label}</span>
      <div className="flex-1 h-2 bg-white/10 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-neon-cyan to-cyber-purple"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-6 text-xs text-white/50 text-right">{value}</span>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h4 className="text-xs font-medium text-white/40 uppercase tracking-wider mb-2">{children}</h4>;
}

function TagList({ items, color = "cyan" }: { items: string[]; color?: string }) {
  const colorMap: Record<string, string> = {
    cyan: "bg-neon-cyan/10 text-neon-cyan border-neon-cyan/20",
    purple: "bg-cyber-purple/10 text-cyber-purple border-cyber-purple/20",
    red: "bg-racing-red/10 text-racing-red border-racing-red/20",
    amber: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    green: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  };
  return (
    <div className="flex flex-wrap gap-2">
      {items.map((item, i) => (
        <span key={i} className={`rounded-full border px-3 py-1 text-xs ${colorMap[color] || colorMap.cyan}`}>
          {item}
        </span>
      ))}
    </div>
  );
}

export default function CharacterDetailPage() {
  const params = useParams();
  const characterId = Number(params.id);

  const [character, setCharacter] = useState<Character | null>(null);
  const [personality, setPersonality] = useState<CharacterPersonality | null>(null);
  const [faceRef, setFaceRef] = useState<FaceReferenceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadingCaricature, setUploadingCaricature] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const caricatureInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    async function fetchData() {
      try {
        const [charData, persData, faceData] = await Promise.allSettled([
          api.characters.get(characterId),
          api.characters.getPersonality(characterId),
          api.characters.getFaceReference(characterId),
        ]);
        if (charData.status === "fulfilled") setCharacter(charData.value);
        else throw charData.reason;
        if (persData.status === "fulfilled") setPersonality(persData.value);
        if (faceData.status === "fulfilled") setFaceRef(faceData.value);
      } catch (err) {
        console.error("Failed to fetch character:", err);
        setError(err instanceof Error ? err.message : "Failed to load character");
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [characterId]);

  async function handleFaceUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const result = await api.characters.uploadFaceReference(characterId, file);
      setFaceRef(result);
    } catch (err) {
      console.error("Face upload failed:", err);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleCaricatureUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingCaricature(true);
    try {
      await api.characters.uploadCaricature(characterId, file);
      // Refresh character to get new primary_image_path
      const updated = await api.characters.get(characterId);
      setCharacter(updated);
    } catch (err) {
      console.error("Caricature upload failed:", err);
    } finally {
      setUploadingCaricature(false);
      if (caricatureInputRef.current) caricatureInputRef.current.value = "";
    }
  }

  if (loading) return <LoadingPage text="Loading character..." />;

  if (error || !character) {
    return (
      <div className="space-y-4">
        <Header title="Character Not Found" />
        <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-6 text-center">
          <p className="text-racing-red">{error || "Character not found"}</p>
          <Link href="/characters" className="mt-4 inline-block">
            <Button variant="secondary">Back to Characters</Button>
          </Link>
        </div>
      </div>
    );
  }

  const primaryImage = getMinioUrl(character.primary_image_path, true);
  const p = personality;

  return (
    <div className="space-y-8">
      <Header
        title={character.display_name}
        subtitle={p ? `${p.nationality || ""} ${character.team ? `| ${character.team}` : ""}`.trim() : character.name}
        actions={
          <div className="flex items-center gap-3">
            <StatusBadge status={character.is_active ? "active" : "inactive"} />
            <Link href="/characters">
              <Button variant="secondary">Back to Characters</Button>
            </Link>
          </div>
        }
      />

      <div className="grid gap-8 lg:grid-cols-3">
        {/* Left column — Image + Quick Info */}
        <div className="lg:col-span-1 space-y-6">
          {/* Caricature */}
          <Card className="overflow-hidden">
            <div className="bg-gradient-to-br from-twilight to-deep-space">
              {primaryImage ? (
                <img
                  src={primaryImage}
                  alt={character.display_name}
                  className="w-full object-contain"
                />
              ) : (
                <div className="flex h-64 w-full items-center justify-center">
                  <div className="text-center">
                    <div className="mx-auto flex h-24 w-24 items-center justify-center rounded-full bg-white/10">
                      <svg className="h-12 w-12 text-white/30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                      </svg>
                    </div>
                    <p className="mt-4 text-white/30">No primary image</p>
                  </div>
                </div>
              )}
            </div>
            <CardContent className="pt-3">
              <input
                ref={caricatureInputRef}
                type="file"
                accept="image/*"
                onChange={handleCaricatureUpload}
                className="hidden"
              />
              <Button
                variant="secondary"
                onClick={() => caricatureInputRef.current?.click()}
                disabled={uploadingCaricature}
                className="w-full"
              >
                {uploadingCaricature ? "Uploading..." : primaryImage ? "Replace Caricature" : "Upload Caricature"}
              </Button>
            </CardContent>
          </Card>

          {/* Face Reference (PuLID source) */}
          <Card>
            <CardHeader>
              <CardTitle>Face Reference</CardTitle>
            </CardHeader>
            <CardContent>
              {faceRef?.face_reference_path ? (
                <div className="space-y-3">
                  <img
                    src={getMinioUrl(faceRef.face_reference_path) as string}
                    alt={`${character.display_name} face reference`}
                    className="w-full rounded-lg object-cover"
                  />
                  <p className="text-xs text-white/40 truncate">{faceRef.face_reference_path}</p>
                </div>
              ) : (
                <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-white/20">
                  <p className="text-sm text-white/30">No face reference uploaded</p>
                </div>
              )}
              <div className="mt-3">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  onChange={handleFaceUpload}
                  className="hidden"
                />
                <Button
                  variant="secondary"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading}
                  className="w-full"
                >
                  {uploading ? "Uploading..." : faceRef?.face_reference_path ? "Replace Face Photo" : "Upload Face Photo"}
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Personality Dimensions */}
          {p?.personality_dimensions && (
            <Card>
              <CardHeader>
                <CardTitle>Personality Dimensions</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {Object.entries(p.personality_dimensions).map(([key, value]) => (
                  <DimensionBar key={key} label={key} value={value as number} />
                ))}
              </CardContent>
            </Card>
          )}

          {/* Quick Stats */}
          <Card>
            <CardContent className="space-y-4 pt-6">
              {character.team && (
                <div>
                  <SectionLabel>Team</SectionLabel>
                  <p className="text-white font-medium">{character.team}</p>
                </div>
              )}
              {p?.comedy_archetype && (
                <div>
                  <SectionLabel>Comedy Archetype</SectionLabel>
                  <p className="text-neon-cyan font-mono text-sm">{p.comedy_archetype.replace(/_/g, " ")}</p>
                </div>
              )}
              {p?.humor_style && (
                <div>
                  <SectionLabel>Humor Style</SectionLabel>
                  <p className="text-white/80 text-sm">{p.humor_style.replace(/_/g, " ")}</p>
                </div>
              )}
              {p?.meme_status && (
                <div>
                  <SectionLabel>Meme Status</SectionLabel>
                  <p className="text-white/70 text-sm italic">{p.meme_status}</p>
                </div>
              )}
              <div className="border-t border-white/10 pt-4">
                <p className="text-xs text-white/40">Created {formatDateTime(character.created_at)}</p>
                <p className="text-xs text-white/40">Updated {formatDateTime(character.updated_at)}</p>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Right column — Personality Details */}
        <div className="space-y-6 lg:col-span-2">
          {/* Satirical Angle */}
          {p?.satirical_angle && (
            <Card>
              <CardHeader>
                <CardTitle>Satirical Angle</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-white/90 text-lg leading-relaxed italic">
                  &ldquo;{p.satirical_angle}&rdquo;
                </p>
              </CardContent>
            </Card>
          )}

          {/* Season Arc */}
          {p?.season_arc && (() => {
            const arc = p.season_arc as Record<string, unknown>;
            return (
              <Card className="border-racing-red/30">
                <CardHeader>
                  <CardTitle>Season Arc: {String(arc.title || "")}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {arc.description ? (
                    <p className="text-white/80">{String(arc.description)}</p>
                  ) : null}
                  {Array.isArray(arc.arc_beats) ? (
                    <div>
                      <SectionLabel>Story Beats</SectionLabel>
                      <ol className="space-y-2">
                        {(arc.arc_beats as string[]).map((beat: string, i: number) => (
                          <li key={i} className="flex gap-3 text-sm text-white/70">
                            <span className="text-neon-cyan font-mono">{i + 1}.</span>
                            {String(beat)}
                          </li>
                        ))}
                      </ol>
                    </div>
                  ) : null}
                  {Array.isArray(arc.running_gags) ? (
                    <div>
                      <SectionLabel>Running Gags</SectionLabel>
                      <TagList items={(arc.running_gags as string[]).map(String)} color="red" />
                    </div>
                  ) : null}
                </CardContent>
              </Card>
            );
          })()}

          {/* Core Traits & Blind Spots */}
          {p && (p.core_traits?.length > 0 || p.blind_spots?.length > 0) && (
            <Card>
              <CardHeader>
                <CardTitle>Character DNA</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {p.core_traits?.length > 0 && (
                  <div>
                    <SectionLabel>Core Traits</SectionLabel>
                    <TagList items={p.core_traits} color="green" />
                  </div>
                )}
                {p.blind_spots?.length > 0 && (
                  <div>
                    <SectionLabel>Blind Spots</SectionLabel>
                    <TagList items={p.blind_spots} color="red" />
                  </div>
                )}
                {p.management_style && (
                  <div>
                    <SectionLabel>Management Style</SectionLabel>
                    <p className="text-white/80 text-sm">{p.management_style}</p>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Catchphrases */}
          {p?.catchphrases && p.catchphrases.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Catchphrases</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {p.catchphrases.map((phrase, i) => (
                    <div key={i} className="flex items-start gap-3 rounded-lg bg-white/5 px-4 py-3">
                      <span className="text-neon-cyan mt-0.5">&ldquo;</span>
                      <p className="text-white/80 italic">{phrase}</p>
                      <span className="text-neon-cyan mt-0.5">&rdquo;</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Speaking Style */}
          {p?.speaking_style && (
            <Card>
              <CardHeader>
                <CardTitle>Speaking Style</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <SectionLabel>Formality</SectionLabel>
                    <p className="text-white/80 text-sm">{p.speaking_style.formality?.replace(/_/g, " ")}</p>
                  </div>
                  <div>
                    <SectionLabel>Sentence Structure</SectionLabel>
                    <p className="text-white/80 text-sm">{p.speaking_style.sentence_structure?.replace(/_/g, " ")}</p>
                  </div>
                </div>
                {p.speaking_style.tone && (
                  <div>
                    <SectionLabel>Tone</SectionLabel>
                    <p className="text-white/80 text-sm">{p.speaking_style.tone}</p>
                  </div>
                )}
                {p.speaking_style.accent_hints && (
                  <div>
                    <SectionLabel>Accent</SectionLabel>
                    <p className="text-white/80 text-sm">{p.speaking_style.accent_hints}</p>
                  </div>
                )}
                {p.speaking_style.vocabulary?.length > 0 && (
                  <div>
                    <SectionLabel>Vocabulary</SectionLabel>
                    <TagList items={p.speaking_style.vocabulary} color="purple" />
                  </div>
                )}
                {p.speaking_style.filler_words?.length > 0 && (
                  <div>
                    <SectionLabel>Filler Words</SectionLabel>
                    <TagList items={p.speaking_style.filler_words} color="amber" />
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Signature Reactions */}
          {p?.signature_reactions && Object.keys(p.signature_reactions).length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Signature Reactions</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {Object.entries(p.signature_reactions).map(([situation, reaction]) => (
                    <div key={situation} className="rounded-lg bg-white/5 px-4 py-3">
                      <p className="text-xs font-medium text-neon-cyan uppercase tracking-wider mb-1">
                        {situation.replace(/_/g, " ")}
                      </p>
                      <p className="text-white/80 text-sm italic">{reaction}</p>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Topics & Storylines */}
          {p && (p.topics_of_passion?.length > 0 || p.topics_to_avoid?.length > 0 || p.storyline_hooks?.length > 0) && (
            <Card>
              <CardHeader>
                <CardTitle>Topics & Storylines</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {p.topics_of_passion?.length > 0 && (
                  <div>
                    <SectionLabel>Loves Talking About</SectionLabel>
                    <TagList items={p.topics_of_passion} color="green" />
                  </div>
                )}
                {p.topics_to_avoid?.length > 0 && (
                  <div>
                    <SectionLabel>Avoid These Topics</SectionLabel>
                    <TagList items={p.topics_to_avoid} color="red" />
                  </div>
                )}
                {p.storyline_hooks?.length > 0 && (
                  <div>
                    <SectionLabel>Storyline Hooks</SectionLabel>
                    <ul className="space-y-2">
                      {p.storyline_hooks.map((hook, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-white/70">
                          <span className="text-cyber-purple mt-1">&#x2022;</span>
                          {hook}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Example Dialogue */}
          {p?.example_dialogue && Object.keys(p.example_dialogue).length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Example Dialogue</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {Object.entries(p.example_dialogue).map(([context, line]) => (
                    <div key={context} className="rounded-lg bg-white/5 px-4 py-3">
                      <p className="text-xs font-medium text-cyber-purple uppercase tracking-wider mb-1">
                        {context.replace(/_/g, " ")}
                      </p>
                      <p className="text-white/80 text-sm">&ldquo;{line}&rdquo;</p>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Relationships */}
          {p?.relationships_summary && Object.keys(p.relationships_summary).length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Relationships</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {Object.entries(p.relationships_summary).map(([key, value]) => (
                  <div key={key}>
                    <SectionLabel>{key.replace(/_/g, " ")}</SectionLabel>
                    <p className="text-white/80 text-sm">
                      {Array.isArray(value) ? (value as string[]).map(String).join(", ").replace(/_/g, " ") : String(value ?? "")}
                    </p>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
