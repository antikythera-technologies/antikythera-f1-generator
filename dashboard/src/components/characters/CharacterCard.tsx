"use client";

import Link from "next/link";
import { Character } from "@/lib/api";
import { cn, truncate, getMinioUrl } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/Card";

interface CharacterCardProps {
  character: Character;
}

export function CharacterCard({ character }: CharacterCardProps) {
  const imageUrl = getMinioUrl(character.primary_image_path);

  return (
    <Link href={`/characters/${character.id}`}>
      <Card hover glow="cyan" className="overflow-hidden">
        {/* Character image */}
        <div className="relative aspect-square bg-gradient-to-br from-twilight to-deep-space">
          {imageUrl ? (
            <img
              src={imageUrl}
              alt={character.display_name}
              className="h-full w-full object-cover"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center">
              <div className="text-center">
                <div className="mx-auto mb-2 flex h-16 w-16 items-center justify-center rounded-full bg-white/10">
                  <svg className="h-8 w-8 text-white/30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                  </svg>
                </div>
                <span className="text-sm text-white/30">No image</span>
              </div>
            </div>
          )}

          {/* Gradient overlay */}
          <div className="absolute inset-0 bg-gradient-to-t from-deep-space via-transparent to-transparent" />

          {/* Active badge */}
          {!character.is_active && (
            <div className="absolute right-2 top-2 rounded-full bg-racing-red/80 px-2 py-0.5 text-xs text-white">
              Inactive
            </div>
          )}
        </div>

        <CardContent className="relative -mt-12 space-y-2 pt-0">
          {/* Name */}
          <div>
            <h3 className="text-xl font-bold text-white">{character.display_name}</h3>
            <p className="font-mono text-sm text-neon-cyan">{character.name}</p>
          </div>

          {/* Voice description */}
          {character.voice_description && (
            <div className="flex items-center gap-2 text-sm text-white/60">
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
              <span className="truncate">{truncate(character.voice_description, 40)}</span>
            </div>
          )}

          {/* Personality snippet */}
          {character.personality && (
            <p className="text-sm text-white/50 line-clamp-2">
              {truncate(character.personality, 80)}
            </p>
          )}

          {/* Image count */}
          <div className="flex items-center gap-2 pt-2 text-xs text-white/40">
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            <span>{character.images?.length || 0} reference images</span>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
