"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, Team } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";
import { Header } from "@/components/layout/Header";
import { Button, LoadingPage, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h4 className="text-xs font-medium text-white/40 uppercase tracking-wider mb-2">{children}</h4>;
}

function ColourSwatch({ colour, label }: { colour: string | null; label: string }) {
  if (!colour) return null;
  return (
    <div className="flex items-center gap-3">
      <div
        className="h-8 w-8 rounded-lg border border-white/20"
        style={{ backgroundColor: colour }}
      />
      <div>
        <p className="text-sm text-white/80">{label}</p>
        <p className="text-xs font-mono text-white/40">{colour}</p>
      </div>
    </div>
  );
}

export default function TeamDetailPage() {
  const params = useParams();
  const teamId = Number(params.id);

  const [team, setTeam] = useState<Team | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  // Editable fields
  const [liveryDescription, setLiveryDescription] = useState("");
  const [carDescription, setCarDescription] = useState("");
  const [overallsDescription, setOverallsDescription] = useState("");

  useEffect(() => {
    async function fetchTeam() {
      try {
        const data = await api.teams.get(teamId);
        setTeam(data);
        setLiveryDescription(data.livery_description || "");
        setCarDescription(data.car_description || "");
        setOverallsDescription(data.overalls_description || "");
      } catch (err) {
        console.error("Failed to fetch team:", err);
        setError(err instanceof Error ? err.message : "Failed to load team");
      } finally {
        setLoading(false);
      }
    }
    fetchTeam();
  }, [teamId]);

  async function handleSave() {
    setSaving(true);
    setSaveMessage(null);
    try {
      const updated = await api.teams.update(teamId, {
        livery_description: liveryDescription || null,
        car_description: carDescription || null,
        overalls_description: overallsDescription || null,
      });
      setTeam(updated);
      setSaveMessage("Saved successfully");
      setTimeout(() => setSaveMessage(null), 3000);
    } catch (err) {
      console.error("Failed to save team:", err);
      setSaveMessage(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <LoadingPage text="Loading team..." />;

  if (error || !team) {
    return (
      <div className="space-y-4">
        <Header title="Team Not Found" />
        <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-6 text-center">
          <p className="text-racing-red">{error || "Team not found"}</p>
          <Link href="/teams" className="mt-4 inline-block">
            <Button variant="secondary">Back to Teams</Button>
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <Header
        title={team.name}
        subtitle={`${team.short_name} | ${team.season} Season`}
        actions={
          <Link href="/teams">
            <Button variant="secondary">Back to Teams</Button>
          </Link>
        }
      />

      {/* Colour bar */}
      <div className="flex h-4 overflow-hidden rounded-lg">
        {team.primary_colour && (
          <div className="flex-1" style={{ backgroundColor: team.primary_colour }} />
        )}
        {team.secondary_colour && (
          <div className="flex-1" style={{ backgroundColor: team.secondary_colour }} />
        )}
        {team.accent_colour && (
          <div className="flex-1" style={{ backgroundColor: team.accent_colour }} />
        )}
      </div>

      <div className="grid gap-8 lg:grid-cols-3">
        {/* Left column - Info */}
        <div className="space-y-6 lg:col-span-1">
          {/* Team Details */}
          <Card>
            <CardHeader>
              <CardTitle>Team Info</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {team.constructor_name && (
                <div>
                  <SectionLabel>Constructor</SectionLabel>
                  <p className="text-white font-medium">{team.constructor_name}</p>
                </div>
              )}
              {team.principal_name && (
                <div>
                  <SectionLabel>Team Principal</SectionLabel>
                  <p className="text-white/80">{team.principal_name}</p>
                </div>
              )}
              {team.engine_supplier && (
                <div>
                  <SectionLabel>Engine Supplier</SectionLabel>
                  <p className="text-white/80">{team.engine_supplier}</p>
                </div>
              )}
              {team.headquarters && (
                <div>
                  <SectionLabel>Headquarters</SectionLabel>
                  <p className="text-white/80">{team.headquarters}</p>
                </div>
              )}
              <div className="border-t border-white/10 pt-4">
                <p className="text-xs text-white/40">Created {formatDateTime(team.created_at)}</p>
              </div>
            </CardContent>
          </Card>

          {/* Colours */}
          <Card>
            <CardHeader>
              <CardTitle>Team Colours</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <ColourSwatch colour={team.primary_colour} label="Primary" />
              <ColourSwatch colour={team.secondary_colour} label="Secondary" />
              <ColourSwatch colour={team.accent_colour} label="Accent" />
              {!team.primary_colour && !team.secondary_colour && !team.accent_colour && (
                <p className="text-sm text-white/30 italic">No colours configured</p>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right column - Editable descriptions */}
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>Visual Descriptions</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div>
                <SectionLabel>Livery Description</SectionLabel>
                <p className="mb-2 text-xs text-white/30">
                  Describes the car livery for image generation prompts
                </p>
                <textarea
                  value={liveryDescription}
                  onChange={(e) => setLiveryDescription(e.target.value)}
                  rows={4}
                  className="w-full rounded-lg border border-white/10 bg-deep-space/50 px-4 py-3 text-sm text-white placeholder-white/30 focus:border-neon-cyan/50 focus:outline-none focus:ring-1 focus:ring-neon-cyan/50"
                  placeholder="Describe the car livery colours and patterns..."
                />
              </div>

              <div>
                <SectionLabel>Car Description</SectionLabel>
                <p className="mb-2 text-xs text-white/30">
                  Physical car details for scene generation
                </p>
                <textarea
                  value={carDescription}
                  onChange={(e) => setCarDescription(e.target.value)}
                  rows={4}
                  className="w-full rounded-lg border border-white/10 bg-deep-space/50 px-4 py-3 text-sm text-white placeholder-white/30 focus:border-neon-cyan/50 focus:outline-none focus:ring-1 focus:ring-neon-cyan/50"
                  placeholder="Describe the car design, aero features, visual identity..."
                />
              </div>

              <div>
                <SectionLabel>Overalls Description</SectionLabel>
                <p className="mb-2 text-xs text-white/30">
                  Driver overalls/suit appearance for character scenes
                </p>
                <textarea
                  value={overallsDescription}
                  onChange={(e) => setOverallsDescription(e.target.value)}
                  rows={4}
                  className="w-full rounded-lg border border-white/10 bg-deep-space/50 px-4 py-3 text-sm text-white placeholder-white/30 focus:border-neon-cyan/50 focus:outline-none focus:ring-1 focus:ring-neon-cyan/50"
                  placeholder="Describe the driver suit design and branding..."
                />
              </div>

              <div className="flex items-center gap-4">
                <Button onClick={handleSave} disabled={saving}>
                  {saving ? "Saving..." : "Save Descriptions"}
                </Button>
                {saveMessage && (
                  <span className={`text-sm ${saveMessage.includes("success") ? "text-success-green" : "text-racing-red"}`}>
                    {saveMessage}
                  </span>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
