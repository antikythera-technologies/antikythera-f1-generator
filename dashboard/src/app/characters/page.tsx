"use client";

import { useEffect, useState } from "react";
import { api, Character } from "@/lib/api";
import { Header } from "@/components/layout/Header";
import { Button, LoadingPage } from "@/components/ui";
import { CharacterCard } from "@/components/characters/CharacterCard";

export default function CharactersPage() {
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showInactive, setShowInactive] = useState(false);

  useEffect(() => {
    async function fetchCharacters() {
      try {
        const data = await api.characters.list();
        setCharacters(data);
      } catch (err) {
        console.error("Failed to fetch characters:", err);
        setError(err instanceof Error ? err.message : "Failed to load characters");
      } finally {
        setLoading(false);
      }
    }

    fetchCharacters();
  }, []);

  const filteredCharacters = showInactive
    ? characters
    : characters.filter((c) => c.is_active);

  return (
    <div className="space-y-8">
      <Header
        title="Characters"
        subtitle="Manage your F1 3D characters and their reference images"
        actions={
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-white/60">
              <input
                type="checkbox"
                checked={showInactive}
                onChange={(e) => setShowInactive(e.target.checked)}
                className="rounded border-white/20 bg-twilight text-neon-cyan focus:ring-neon-cyan"
              />
              Show inactive
            </label>
            <Button>
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              Add Character
            </Button>
          </div>
        }
      />

      {error && (
        <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-4">
          <p className="text-racing-red">{error}</p>
        </div>
      )}

      {loading ? (
        <LoadingPage text="Loading characters..." />
      ) : filteredCharacters.length === 0 ? (
        <div className="rounded-xl border border-white/10 bg-midnight/50 p-12 text-center">
          <svg className="mx-auto h-12 w-12 text-white/20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
          </svg>
          <h3 className="mt-4 text-lg font-medium text-white">No characters found</h3>
          <p className="mt-2 text-white/60">Add your first F1 character to get started</p>
          <Button className="mt-4">Add Character</Button>
        </div>
      ) : (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filteredCharacters.map((character) => (
            <CharacterCard key={character.id} character={character} />
          ))}
        </div>
      )}
    </div>
  );
}
