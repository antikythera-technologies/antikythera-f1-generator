"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, Race, EpisodeType } from "@/lib/api";
import { formatDate, cn } from "@/lib/utils";
import { Header } from "@/components/layout/Header";
import { Button, LoadingPage, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";

export default function NewEpisodePage() {
  const router = useRouter();
  
  const [races, setRaces] = useState<Race[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const [selectedRace, setSelectedRace] = useState<Race | null>(null);
  const [episodeType, setEpisodeType] = useState<EpisodeType>("post-race");

  useEffect(() => {
    async function fetchRaces() {
      try {
        const data = await api.races.list({ season: 2026 });
        setRaces(data);
      } catch (err) {
        console.error("Failed to fetch races:", err);
        setError(err instanceof Error ? err.message : "Failed to load races");
      } finally {
        setLoading(false);
      }
    }

    fetchRaces();
  }, []);

  const handleSubmit = async () => {
    if (!selectedRace) {
      setError("Please select a race");
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      const result = await api.episodes.generate({
        race_id: selectedRace.id,
        episode_type: episodeType,
      });
      
      // Redirect to the new episode page
      router.push(`/episodes/${result.episode_id}`);
    } catch (err) {
      console.error("Failed to create episode:", err);
      setError(err instanceof Error ? err.message : "Failed to create episode");
      setSubmitting(false);
    }
  };

  if (loading) {
    return <LoadingPage text="Loading races..." />;
  }

  return (
    <div className="space-y-8">
      <Header
        title="Create New Episode"
        subtitle="Generate a satirical F1 commentary video"
      />

      {error && (
        <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-4">
          <p className="text-racing-red">{error}</p>
        </div>
      )}

      <div className="grid gap-8 lg:grid-cols-3">
        {/* Race Selection */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>Select Race</CardTitle>
            </CardHeader>
            <CardContent>
              {races.length === 0 ? (
                <div className="py-8 text-center">
                  <p className="text-white/60">No races available</p>
                  <p className="mt-2 text-sm text-white/40">
                    Sync the race calendar from settings
                  </p>
                </div>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                  {races.map((race) => (
                    <button
                      key={race.id}
                      onClick={() => setSelectedRace(race)}
                      className={cn(
                        "rounded-lg border p-4 text-left transition-all",
                        selectedRace?.id === race.id
                          ? "border-neon-cyan bg-neon-cyan/10 shadow-glow-cyan"
                          : "border-white/10 bg-twilight/30 hover:border-white/20 hover:bg-twilight/50"
                      )}
                    >
                      <div className="flex items-start justify-between">
                        <div>
                          <h3 className="font-semibold text-white">{race.race_name}</h3>
                          <p className="mt-1 text-sm text-white/60">{race.circuit_name}</p>
                        </div>
                        <span className="rounded-full bg-white/10 px-2 py-0.5 text-xs text-white/70">
                          R{race.round_number}
                        </span>
                      </div>
                      <div className="mt-3 flex items-center gap-3 text-sm">
                        <span className="text-white/50">{race.country}</span>
                        <span className="text-neon-cyan">{formatDate(race.race_date)}</span>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Episode Type & Submit */}
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Episode Type</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <button
                onClick={() => setEpisodeType("pre-race")}
                className={cn(
                  "w-full rounded-lg border p-4 text-left transition-all",
                  episodeType === "pre-race"
                    ? "border-electric-blue bg-electric-blue/10"
                    : "border-white/10 bg-twilight/30 hover:border-white/20"
                )}
              >
                <div className="flex items-center gap-3">
                  <div className={cn(
                    "flex h-10 w-10 items-center justify-center rounded-lg",
                    episodeType === "pre-race" ? "bg-electric-blue/20" : "bg-white/10"
                  )}>
                    <svg className={cn(
                      "h-5 w-5",
                      episodeType === "pre-race" ? "text-electric-blue" : "text-white/50"
                    )} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                  </div>
                  <div>
                    <h4 className="font-medium text-white">Pre-Race</h4>
                    <p className="text-sm text-white/60">Preview & predictions</p>
                  </div>
                </div>
              </button>
              
              <button
                onClick={() => setEpisodeType("post-race")}
                className={cn(
                  "w-full rounded-lg border p-4 text-left transition-all",
                  episodeType === "post-race"
                    ? "border-cyber-purple bg-cyber-purple/10"
                    : "border-white/10 bg-twilight/30 hover:border-white/20"
                )}
              >
                <div className="flex items-center gap-3">
                  <div className={cn(
                    "flex h-10 w-10 items-center justify-center rounded-lg",
                    episodeType === "post-race" ? "bg-cyber-purple/20" : "bg-white/10"
                  )}>
                    <svg className={cn(
                      "h-5 w-5",
                      episodeType === "post-race" ? "text-cyber-purple" : "text-white/50"
                    )} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z" />
                    </svg>
                  </div>
                  <div>
                    <h4 className="font-medium text-white">Post-Race</h4>
                    <p className="text-sm text-white/60">Results & commentary</p>
                  </div>
                </div>
              </button>
            </CardContent>
          </Card>

          {/* Summary */}
          {selectedRace && (
            <Card className="border-neon-cyan/30 bg-neon-cyan/5">
              <CardContent className="space-y-3">
                <h4 className="font-medium text-white">Summary</h4>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-white/60">Race</span>
                    <span className="text-white">{selectedRace.race_name}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-white/60">Type</span>
                    <span className={episodeType === "pre-race" ? "text-electric-blue" : "text-cyber-purple"}>
                      {episodeType === "pre-race" ? "Pre-Race" : "Post-Race"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-white/60">Scenes</span>
                    <span className="text-white">24</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-white/60">Duration</span>
                    <span className="text-white">~2 minutes</span>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Submit */}
          <Button
            className="w-full"
            size="lg"
            disabled={!selectedRace}
            loading={submitting}
            onClick={handleSubmit}
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Generate Episode
          </Button>
        </div>
      </div>
    </div>
  );
}
