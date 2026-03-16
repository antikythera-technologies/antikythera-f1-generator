"use client";

import { useState, useEffect } from "react";
import { Header } from "@/components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle, Button } from "@/components/ui";
import { settingsApi, type PipelineSettings, type VideoGenerator, type ImageGenerator, type ServiceBalances, type CostSummary } from "@/lib/api";

const BACKEND_INFO: Record<string, { label: string; maxDuration: number; audio: boolean; costPerSec: number; note: string }> = {
  "fal-ovi":              { label: "Ovi (fal.ai)",                    maxDuration: 10, audio: true,  costPerSec: 0.04,   note: "5s or 10s, native audio" },
  "fal-ltx":              { label: "LTX 2.3 + Audio (fal.ai)",       maxDuration: 20, audio: true,  costPerSec: 0.06,   note: "6-20s, native audio, 1080p" },
  "fal-kling-std":        { label: "Kling 3.0 Standard (fal.ai)",    maxDuration: 15, audio: false, costPerSec: 0.084,  note: "3-15s, no audio" },
  "fal-kling-std-audio":  { label: "Kling 3.0 Std + Audio (fal.ai)", maxDuration: 15, audio: true,  costPerSec: 0.126,  note: "3-15s, native audio" },
  "fal-kling-pro":        { label: "Kling 3.0 Pro (fal.ai)",         maxDuration: 15, audio: false, costPerSec: 0.112,  note: "3-15s, higher quality, no audio" },
  "fal-kling-pro-audio":  { label: "Kling 3.0 Pro + Audio (fal.ai)", maxDuration: 15, audio: true,  costPerSec: 0.168,  note: "3-15s, highest quality + audio" },
};

function StatusIndicator({ status }: { status: "connected" | "disconnected" | "warning" }) {
  const colors = { connected: "bg-success-green", disconnected: "bg-racing-red", warning: "bg-yellow-500" };
  return (
    <div className="flex items-center gap-2">
      <div className={`h-2 w-2 rounded-full ${colors[status]} animate-pulse`} />
      <span className="text-xs text-white/50 capitalize">{status}</span>
    </div>
  );
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<PipelineSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [balances, setBalances] = useState<ServiceBalances | null>(null);
  const [videoGenerator, setVideoGenerator] = useState<VideoGenerator>("fal-ltx");
  const [costs, setCosts] = useState<CostSummary | null>(null);
  const [imageGenerator, setImageGenerator] = useState<ImageGenerator>("flux-lora");

  useEffect(() => {
    Promise.all([
      settingsApi.getPipeline(),
      settingsApi.getBalances().catch(() => null),
      settingsApi.getCosts().catch(() => null),
    ])
      .then(([pipelineData, balanceData, costData]) => {
        setSettings(pipelineData);
        setVideoGenerator(pipelineData.video_generator);
        setImageGenerator((pipelineData as any).image_generator || "flux-lora");
        if (balanceData) setBalances(balanceData);
        if (costData) setCosts(costData);
      })
      .catch((err) => {
        console.error("Failed to load pipeline settings:", err);
        setSaveMessage({ type: "error", text: "Failed to load settings from backend" });
      })
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setSaveMessage(null);
    try {
      const updated = await settingsApi.updatePipeline({ video_generator: videoGenerator, image_generator: imageGenerator } as any);
      setSettings(updated);
      setSaveMessage({ type: "success", text: "Settings saved successfully" });
      setTimeout(() => setSaveMessage(null), 3000);
    } catch {
      setSaveMessage({ type: "error", text: "Failed to save settings" });
    } finally {
      setSaving(false);
    }
  };

  const hasChanges = settings && (videoGenerator !== settings.video_generator || imageGenerator !== (settings as any).image_generator);
  const info = BACKEND_INFO[videoGenerator];
  const sceneDuration = settings?.video_scene_duration_seconds ?? 5;
  const sceneCount = settings?.video_scene_count ?? 24;
  const costPerClip = info ? info.costPerSec * sceneDuration : 0;
  const costPerEpisode = costPerClip * sceneCount;

  const envConfig = {
    apiUrl: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001",
    minioUrl: process.env.NEXT_PUBLIC_MINIO_URL || "https://minio.antikythera.co.za",
  };

  return (
    <div className="space-y-8">
      <Header title="Settings" subtitle="Configure your F1 Video Generator" />

      <div className="grid gap-8 lg:grid-cols-2">
        {/* Video Pipeline Settings */}
        <Card className="lg:col-span-2 border-cyber-purple/30">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <svg className="h-5 w-5 text-cyber-purple" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
              Video Pipeline
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            {loading ? (
              <div className="flex items-center gap-2 text-white/50">
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/20 border-t-neon-cyan" />
                Loading settings...
              </div>
            ) : (
              <>
                {/* Image Generator Selector */}
                <div className="grid gap-6 md:grid-cols-2">
                  <div>
                    <label className="block text-sm font-medium text-white/60 mb-1">Image Generator</label>
                    <select
                      value={imageGenerator}
                      onChange={(e) => setImageGenerator(e.target.value as ImageGenerator)}
                      className="w-full rounded-lg border border-white/10 bg-twilight px-3 py-2.5 text-white focus:border-cyber-purple focus:outline-none focus:ring-1 focus:ring-cyber-purple"
                    >
                      <option value="flux-lora">Flux LoRA (style only, no face ref) — $0.035/image</option>
                      <option value="instant-character">Instant Character (face ref + identity) — experimental</option>
                    </select>
                    <p className="mt-1 text-xs text-white/40">
                      {imageGenerator === "instant-character"
                        ? "Uses face reference images for character consistency. Experimental — testing in progress."
                        : "Current default. LoRA style consistency, faces driven by prompt only."}
                    </p>
                  </div>
                  <div className="flex items-center">
                    <div className={`rounded-lg border p-3 w-full ${
                      imageGenerator === "instant-character"
                        ? "border-neon-cyan/30 bg-neon-cyan/5"
                        : "border-white/10 bg-twilight/30"
                    }`}>
                      <p className="text-xs text-white/50">Face References</p>
                      <p className={`text-sm font-medium ${
                        imageGenerator === "instant-character" ? "text-neon-cyan" : "text-white/40"
                      }`}>
                        {imageGenerator === "instant-character" ? "Enabled — using character face images" : "Disabled — prompt-only faces"}
                      </p>
                    </div>
                  </div>
                </div>

                {/* Video Generator Selector */}
                <div>
                  <label className="block text-sm font-medium text-white/60 mb-1">Video Generator</label>
                  <select
                    value={videoGenerator}
                    onChange={(e) => setVideoGenerator(e.target.value as VideoGenerator)}
                    className="w-full rounded-lg border border-white/10 bg-twilight px-3 py-2.5 text-white focus:border-cyber-purple focus:outline-none focus:ring-1 focus:ring-cyber-purple"
                  >
                    {Object.entries(BACKEND_INFO).map(([value, bi]) => (
                      <option key={value} value={value}>
                        {bi.label} {bi.audio ? "" : "(no audio)"} — ${bi.costPerSec.toFixed(3)}/s
                      </option>
                    ))}
                  </select>
                  {info && (
                    <p className="mt-1 text-xs text-white/40">
                      {info.note} — Max {info.maxDuration}s per clip — {info.audio ? "Audio included" : "No audio"}
                    </p>
                  )}
                </div>

                {/* Backend capabilities */}
                {info && (
                  <div className="rounded-lg border border-white/10 bg-twilight/50 p-4">
                    <h4 className="text-sm font-medium text-white/70 mb-3">Backend Capabilities</h4>
                    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                      <div className="text-center">
                        <p className="text-xs text-white/40">Max Duration</p>
                        <p className="text-lg font-bold text-neon-cyan">{info.maxDuration}s</p>
                      </div>
                      <div className="text-center">
                        <p className="text-xs text-white/40">Audio</p>
                        <p className={`text-lg font-bold ${info.audio ? "text-success-green" : "text-racing-red"}`}>
                          {info.audio ? "Yes" : "No"}
                        </p>
                      </div>
                      <div className="text-center">
                        <p className="text-xs text-white/40">Cost / clip ({sceneDuration}s)</p>
                        <p className="text-lg font-bold text-white">${costPerClip.toFixed(2)}</p>
                      </div>
                      <div className="text-center">
                        <p className="text-xs text-white/40">Cost / episode ({sceneCount}x)</p>
                        <p className="text-lg font-bold text-electric-blue">${costPerEpisode.toFixed(2)}</p>
                      </div>
                    </div>
                  </div>
                )}

                {/* Episode stats */}
                <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                  <div>
                    <label className="block text-sm font-medium text-white/60">Scene Count</label>
                    <div className="mt-1 rounded-lg border border-white/10 bg-twilight px-3 py-2 text-white">{sceneCount}</div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-white/60">Scene Duration</label>
                    <div className="mt-1 rounded-lg border border-white/10 bg-twilight px-3 py-2 text-white">{sceneDuration}s</div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-white/60">Total Duration</label>
                    <div className="mt-1 rounded-lg border border-white/10 bg-twilight px-3 py-2 text-white">{(sceneCount * sceneDuration / 60).toFixed(1)}m</div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-white/60">Active Backend</label>
                    <div className="mt-1 rounded-lg border border-white/10 bg-twilight px-3 py-2 text-electric-blue">fal.ai</div>
                  </div>
                </div>

                {/* Save button */}
                <div className="flex items-center gap-4 border-t border-white/10 pt-4">
                  <Button variant="primary" size="sm" onClick={handleSave} disabled={saving || !hasChanges}>
                    {saving ? "Saving..." : "Save Changes"}
                  </Button>
                  {saveMessage && (
                    <span className={`text-sm ${saveMessage.type === "success" ? "text-success-green" : "text-racing-red"}`}>
                      {saveMessage.text}
                    </span>
                  )}
                  {!hasChanges && !saveMessage && <span className="text-sm text-white/30">No unsaved changes</span>}
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* API Configuration */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <svg className="h-5 w-5 text-neon-cyan" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
              </svg>
              API Configuration
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-white/60">Backend URL</label>
              <input type="text" value={envConfig.apiUrl} readOnly className="mt-1 w-full rounded-lg border border-white/10 bg-twilight px-3 py-2 text-white/80" />
              <p className="mt-1 text-xs text-white/40">Set via NEXT_PUBLIC_API_URL</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-white/60">MinIO URL</label>
              <input type="text" value={envConfig.minioUrl} readOnly className="mt-1 w-full rounded-lg border border-white/10 bg-twilight px-3 py-2 text-white/80" />
              <p className="mt-1 text-xs text-white/40">Set via NEXT_PUBLIC_MINIO_URL</p>
            </div>
            <div className="flex items-center gap-3 rounded-lg bg-success-green/10 p-3">
              <div className="h-2 w-2 rounded-full bg-success-green animate-pulse" />
              <span className="text-sm text-success-green">Backend connection active</span>
            </div>
          </CardContent>
        </Card>

        {/* External Services */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <svg className="h-5 w-5 text-electric-blue" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9" />
              </svg>
              External Services
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between rounded-lg border border-white/10 p-4">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-electric-blue/10">
                  <span className="text-sm font-bold text-electric-blue">fal</span>
                </div>
                <div>
                  <p className="font-medium text-white">fal.ai</p>
                  <p className="text-xs text-white/50">Image gen (Flux LoRA) + Video (Ovi, LTX, Kling)</p>
                </div>
              </div>
              <StatusIndicator status="connected" />
            </div>
            <div className="flex items-center justify-between rounded-lg border border-white/10 p-4">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-cyber-purple/10">
                  <svg className="h-5 w-5 text-cyber-purple" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.894 8.221l-1.97 9.28c-.145.658-.537.818-1.084.508l-3-2.21-1.446 1.394c-.14.18-.357.295-.6.295l.213-3.054 5.56-5.022c.242-.213-.054-.333-.373-.121l-6.869 4.326-2.96-.924c-.64-.203-.658-.64.135-.954l11.566-4.458c.538-.196 1.006.128.828.94z"/>
                  </svg>
                </div>
                <div>
                  <p className="font-medium text-white">Anthropic Claude</p>
                  <p className="text-xs text-white/50">Script generation (Sonnet 4)</p>
                </div>
              </div>
              <StatusIndicator status="connected" />
            </div>
            <div className="flex items-center justify-between rounded-lg border border-white/10 p-4">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-racing-red/10">
                  <svg className="h-5 w-5 text-racing-red" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M19.615 3.184c-3.604-.246-11.631-.245-15.23 0-3.897.266-4.356 2.62-4.385 8.816.029 6.185.484 8.549 4.385 8.816 3.6.245 11.626.246 15.23 0 3.897-.266 4.356-2.62 4.385-8.816-.029-6.185-.484-8.549-4.385-8.816zm-10.615 12.816v-8l8 3.993-8 4.007z"/>
                  </svg>
                </div>
                <div>
                  <p className="font-medium text-white">YouTube</p>
                  <p className="text-xs text-white/50">Video upload & publishing</p>
                </div>
              </div>
              <StatusIndicator status="connected" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Service Balances */}
      {balances && (
        <Card className="border-neon-cyan/30">
          <CardHeader><CardTitle>Service Balances</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-cyber-purple/20">
                  <span className="text-lg font-bold text-cyber-purple">f</span>
                </div>
                <div>
                  <p className="font-medium text-white">fal.ai</p>
                  <p className="text-xs text-white/50">Image & video generation</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className={`rounded-full px-2 py-1 text-xs font-medium ${
                  balances.fal_status === "active" ? "bg-success-green/20 text-success-green" : "bg-racing-red/20 text-racing-red"
                }`}>
                  {balances.fal_status === "active" ? "Active" : balances.fal_status}
                </span>
                <a href={balances.fal_balance_url} target="_blank" rel="noopener noreferrer"
                  className="rounded-lg bg-white/10 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-white/20">
                  View Balance
                </a>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
