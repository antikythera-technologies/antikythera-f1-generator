"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, Character } from "@/lib/api";
import { formatDateTime, getMinioUrl } from "@/lib/utils";
import { Header } from "@/components/layout/Header";
import { Button, LoadingPage, Card, CardContent, CardHeader, CardTitle, StatusBadge } from "@/components/ui";

export default function CharacterDetailPage() {
  const params = useParams();
  const characterId = Number(params.id);
  
  const [character, setCharacter] = useState<Character | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchCharacter() {
      try {
        const data = await api.characters.get(characterId);
        setCharacter(data);
      } catch (err) {
        console.error("Failed to fetch character:", err);
        setError(err instanceof Error ? err.message : "Failed to load character");
      } finally {
        setLoading(false);
      }
    }

    fetchCharacter();
  }, [characterId]);

  if (loading) {
    return <LoadingPage text="Loading character..." />;
  }

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

  const primaryImage = getMinioUrl(character.primary_image_path);

  return (
    <div className="space-y-8">
      <Header
        title={character.display_name}
        subtitle={character.name}
        actions={
          <div className="flex items-center gap-3">
            <StatusBadge status={character.is_active ? "active" : "inactive"} />
            <Link href={`/characters/${characterId}/edit`}>
              <Button variant="secondary">Edit Character</Button>
            </Link>
          </div>
        }
      />

      <div className="grid gap-8 lg:grid-cols-3">
        {/* Main Image */}
        <div className="lg:col-span-1">
          <Card className="overflow-hidden">
            <div className="aspect-square bg-gradient-to-br from-twilight to-deep-space">
              {primaryImage ? (
                <img
                  src={primaryImage}
                  alt={character.display_name}
                  className="h-full w-full object-cover"
                />
              ) : (
                <div className="flex h-full w-full items-center justify-center">
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
          </Card>
        </div>

        {/* Details */}
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>Character Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Description */}
              {character.description && (
                <div>
                  <h4 className="text-sm font-medium text-white/50 uppercase tracking-wider">Description</h4>
                  <p className="mt-2 text-white/80">{character.description}</p>
                </div>
              )}

              {/* Voice */}
              {character.voice_description && (
                <div>
                  <h4 className="text-sm font-medium text-white/50 uppercase tracking-wider">Voice</h4>
                  <div className="mt-2 flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-cyber-purple/20">
                      <svg className="h-5 w-5 text-cyber-purple" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                      </svg>
                    </div>
                    <p className="text-white/80">{character.voice_description}</p>
                  </div>
                </div>
              )}

              {/* Personality */}
              {character.personality && (
                <div>
                  <h4 className="text-sm font-medium text-white/50 uppercase tracking-wider">Personality</h4>
                  <p className="mt-2 text-white/80">{character.personality}</p>
                </div>
              )}

              {/* Timestamps */}
              <div className="grid gap-4 border-t border-white/10 pt-6 sm:grid-cols-2">
                <div>
                  <p className="text-xs text-white/50">Created</p>
                  <p className="mt-1 text-sm text-white/70">{formatDateTime(character.created_at)}</p>
                </div>
                <div>
                  <p className="text-xs text-white/50">Updated</p>
                  <p className="mt-1 text-sm text-white/70">{formatDateTime(character.updated_at)}</p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Caricature Traits */}
          {(character.role || character.team || character.physical_features || character.comedy_angle) && (
            <Card>
              <CardHeader>
                <CardTitle>Caricature Traits</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  {character.role && (
                    <div>
                      <p className="text-xs text-white/50 uppercase tracking-wider">Role</p>
                      <p className="mt-1 text-sm text-white/80 capitalize">{character.role.replace("_", " ")}</p>
                    </div>
                  )}
                  {character.team && (
                    <div>
                      <p className="text-xs text-white/50 uppercase tracking-wider">Team</p>
                      <p className="mt-1 text-sm text-white/80">{character.team}</p>
                    </div>
                  )}
                  {character.nationality && (
                    <div>
                      <p className="text-xs text-white/50 uppercase tracking-wider">Nationality</p>
                      <p className="mt-1 text-sm text-white/80">{character.nationality}</p>
                    </div>
                  )}
                  {character.background_type && (
                    <div>
                      <p className="text-xs text-white/50 uppercase tracking-wider">Background</p>
                      <p className="mt-1 text-sm text-white/80 capitalize">{character.background_type.replace("_", " ")}</p>
                    </div>
                  )}
                </div>
                {character.physical_features && (
                  <div className="border-t border-white/10 pt-4">
                    <p className="text-xs text-white/50 uppercase tracking-wider">Physical Features</p>
                    <p className="mt-1 text-sm text-white/80">{character.physical_features}</p>
                  </div>
                )}
                {character.comedy_angle && (
                  <div className="border-t border-white/10 pt-4">
                    <p className="text-xs text-white/50 uppercase tracking-wider">Comedy Angle</p>
                    <p className="mt-1 text-sm text-white/80">{character.comedy_angle}</p>
                  </div>
                )}
                {character.signature_expression && (
                  <div className="border-t border-white/10 pt-4">
                    <p className="text-xs text-white/50 uppercase tracking-wider">Signature Expression</p>
                    <p className="mt-1 text-sm text-white/80">{character.signature_expression}</p>
                  </div>
                )}
                {character.clothing_description && (
                  <div className="border-t border-white/10 pt-4">
                    <p className="text-xs text-white/50 uppercase tracking-wider">Clothing</p>
                    <p className="mt-1 text-sm text-white/80">{character.clothing_description}</p>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Reference Images */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Reference Images ({character.images?.length || 0})</CardTitle>
              <Button variant="secondary" size="sm">
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
                Upload Image
              </Button>
            </CardHeader>
            <CardContent>
              {character.images && character.images.length > 0 ? (
                <div className="grid gap-4 sm:grid-cols-3">
                  {character.images.map((image) => {
                    const imageUrl = getMinioUrl(image.image_path);
                    return (
                      <div key={image.id} className="relative group">
                        <div className="aspect-square overflow-hidden rounded-lg bg-twilight">
                          {imageUrl ? (
                            <img
                              src={imageUrl}
                              alt={image.pose_description || "Reference image"}
                              className="h-full w-full object-cover"
                            />
                          ) : (
                            <div className="flex h-full w-full items-center justify-center">
                              <span className="text-white/30">No preview</span>
                            </div>
                          )}
                        </div>
                        {image.is_primary && (
                          <div className="absolute left-2 top-2 rounded-full bg-neon-cyan px-2 py-0.5 text-xs font-medium text-deep-space">
                            Primary
                          </div>
                        )}
                        <div className="mt-2">
                          <p className="text-sm text-white">{image.image_type}</p>
                          {image.pose_description && (
                            <p className="text-xs text-white/50">{image.pose_description}</p>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="py-8 text-center">
                  <svg className="mx-auto h-12 w-12 text-white/20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                  <p className="mt-4 text-white/60">No reference images yet</p>
                  <Button className="mt-4" variant="secondary">
                    Upload First Image
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
