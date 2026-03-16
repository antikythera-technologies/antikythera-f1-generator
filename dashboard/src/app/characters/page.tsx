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
  const [search, setSearch] = useState("");

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

  const filteredCharacters = characters
    .filter((c) => showInactive || c.is_active)
    .filter((c) => {
      if (!search) return true;
      const q = search.toLowerCase();
      return (
        c.name.toLowerCase().includes(q) ||
        (c.display_name || "").toLowerCase().includes(q) ||
        (c.team || "").toLowerCase().includes(q) ||
        (c.description || "").toLowerCase().includes(q)
      );
    });

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

      {/* Search bar */}
      <div className="relative">
        <svg
          className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-white/30"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by name, team, or role..."
          className="w-full rounded-lg border border-white/10 bg-midnight/50 py-2.5 pl-10 pr-4 text-white placeholder-white/30 backdrop-blur-sm focus:border-neon-cyan/50 focus:outline-none focus:ring-1 focus:ring-neon-cyan/50"
        />
        {search && (
          <button
            onClick={() => setSearch("")}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-white/30 hover:text-white/60"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
        {search && (
          <p className="mt-1 text-xs text-white/40">
            {filteredCharacters.length} of {characters.filter((c) => showInactive || c.is_active).length} characters
          </p>
        )}
      </div>

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
          <h3 className="mt-4 text-lg font-medium text-white">
            {search ? "No characters match your search" : "No characters found"}
          </h3>
          <p className="mt-2 text-white/60">
            {search ? "Try a different search term" : "Add your first F1 character to get started"}
          </p>
          {!search && <Button className="mt-4">Add Character</Button>}
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
