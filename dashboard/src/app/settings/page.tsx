"use client";

import { useState, useEffect } from "react";
import { Header } from "@/components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle, Button } from "@/components/ui";
import { settingsApi, type PipelineSettings, type VideoGenerator, type OviQuality, type ServiceBalances } from "@/lib/api";

export default function SettingsPage() {
  const [settings, setSettings] = useState<PipelineSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [balances, setBalances] = useState<ServiceBalances | null>(null);

  // Local state for editable fields
  const [videoGenerator, setVideoGenerator] = useState<VideoGenerator>("ovi");
  const [ttsEnabled, setTtsEnabled] = useState(true);
  const [oviQuality, setOviQuality] = useState<OviQuality>("standard");

  useEffect(() => {
    Promise.all([
      settingsApi.getPipeline(),
      settingsApi.getBalances().catch(() => null),
    ])
      .then(([pipelineData, balanceData]) => {
        setSettings(pipelineData);
        setVideoGenerator(pipelineData.video_generator);
        setTtsEnabled(pipelineData.tts_enabled);
        setOviQuality(pipelineData.ovi_quality as OviQuality);
        if (balanceData) setBalances(balanceData);
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
      const updated = await settingsApi.updatePipeline({
        video_generator: videoGenerator,
        tts_enabled: ttsEnabled,
        ovi_quality: oviQuality,
      });
      setSettings(updated);
      setSaveMessage({ type: "success", text: "Settings saved successfully" });
      setTimeout(() => setSaveMessage(null), 3000);
    } catch (err) {
      setSaveMessage({ type: "error", text: "Failed to save settings" });
    } finally {
      setSaving(false);
    }
  };

  const hasChanges = settings && (
    videoGenerator !== settings.video_generator ||
    ttsEnabled !== settings.tts_enabled ||
    oviQuality !== settings.ovi_quality
  );

  // These are read-only env-level config
  const envConfig = {
    apiUrl: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001",
    minioUrl: process.env.NEXT_PUBLIC_MINIO_URL || "https://minio.antikythera.co.za",
  };

  return (
    <div className="space-y-8">
      <Header
        title="Settings"
        subtitle="Configure your F1 Video Generator"
      />

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
                {/* Video Generator Selector */}
                <div className="grid gap-6 md:grid-cols-2">
                  <div>
                    <label className="block text-sm font-medium text-white/60 mb-1">Video Generator</label>
                    <select
                      value={videoGenerator}
                      onChange={(e) => setVideoGenerator(e.target.value as VideoGenerator)}
                      className="w-full rounded-lg border border-white/10 bg-twilight px-3 py-2.5 text-white focus:border-cyber-purple focus:outline-none focus:ring-1 focus:ring-cyber-purple"
                    >
                      <optgroup label="Self-Hosted (RunPod)">
                        <option value="ovi">Ovi (RunPod Gradio)</option>
                        <option value="ltx">LTX 2.3 (RunPod ComfyUI) — Blocked</option>
                      </optgroup>
                      <optgroup label="fal.ai Hosted">
                        <option value="fal-ovi">Ovi (fal.ai) — $0.20/clip</option>
                        <option value="fal-ltx">LTX 2.3 + Audio (fal.ai) — $0.30/clip</option>
                        <option value="fal-kling-std">Kling 3.0 Standard (fal.ai) — $0.42/clip</option>
                        <option value="fal-kling-std-audio">Kling 3.0 Standard + Audio (fal.ai) — $0.63/clip</option>
                        <option value="fal-kling-pro">Kling 3.0 Pro (fal.ai) — $0.42/clip</option>
                        <option value="fal-kling-pro-audio">Kling 3.0 Pro + Audio (fal.ai) — $0.84/clip</option>
                      </optgroup>
                    </select>
                    <p className="mt-1 text-xs text-white/40">
                      {videoGenerator.startsWith("fal-")
                        ? `fal.ai hosted — no GPU management needed. Est. $${({
                            "fal-ovi": "4.80", "fal-ltx": "7.20",
                            "fal-kling-std": "10.08", "fal-kling-std-audio": "15.12",
                            "fal-kling-pro": "10.08", "fal-kling-pro-audio": "20.16",
                          } as Record<string, string>)[videoGenerator] || "?"}/episode (24 scenes)`
                        : videoGenerator === "ovi"
                          ? "Self-hosted Ovi on RunPod. ~16 min/clip, requires GPU pod running."
                          : "LTX 2.3 on RunPod — currently blocked after 20h of failed attempts."}
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-white/60 mb-1">Ovi Quality Preset</label>
                    <select
                      value={oviQuality}
                      onChange={(e) => setOviQuality(e.target.value as OviQuality)}
                      disabled={videoGenerator !== "ovi"}
                      className="w-full rounded-lg border border-white/10 bg-twilight px-3 py-2.5 text-white focus:border-cyber-purple focus:outline-none focus:ring-1 focus:ring-cyber-purple disabled:opacity-40"
                    >
                      <option value="draft">Draft (fast, lower quality)</option>
                      <option value="standard">Standard</option>
                      <option value="high">High</option>
                      <option value="ultra">Ultra (slow, highest quality)</option>
                      <option value="caricature">Caricature (style preservation)</option>
                    </select>
                    <p className="mt-1 text-xs text-white/40">
                      Controls steps, conditioning strength, and denoise
                    </p>
                  </div>
                </div>

                {/* TTS Toggle */}
                <div className="flex items-center justify-between rounded-lg border border-white/10 p-4">
                  <div>
                    <p className="font-medium text-white">Text-to-Speech Audio</p>
                    <p className="text-sm text-white/50">Generate character voices via Edge TTS and mux onto video clips</p>
                  </div>
                  <button
                    onClick={() => setTtsEnabled(!ttsEnabled)}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                      ttsEnabled ? "bg-cyber-purple" : "bg-white/20"
                    }`}
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        ttsEnabled ? "translate-x-6" : "translate-x-1"
                      }`}
                    />
                  </button>
                </div>

                {/* Read-only stats */}
                <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                  <div>
                    <label className="block text-sm font-medium text-white/60">Scene Count</label>
                    <div className="mt-1 rounded-lg border border-white/10 bg-twilight px-3 py-2 text-white">
                      {settings?.video_scene_count ?? 24}
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-white/60">Scene Duration</label>
                    <div className="mt-1 rounded-lg border border-white/10 bg-twilight px-3 py-2 text-white">
                      {settings?.video_scene_duration_seconds ?? 5}s
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-white/60">Total Duration</label>
                    <div className="mt-1 rounded-lg border border-white/10 bg-twilight px-3 py-2 text-white">
                      {((settings?.video_scene_count ?? 24) * (settings?.video_scene_duration_seconds ?? 5)) / 60}m
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-white/60">Active Backend</label>
                    <div className={`mt-1 rounded-lg border border-white/10 bg-twilight px-3 py-2 ${
                      videoGenerator.startsWith("fal-") ? "text-electric-blue" : "text-neon-cyan"
                    }`}>
                      {videoGenerator.startsWith("fal-") ? "fal.ai" : "RunPod"}
                    </div>
                  </div>
                </div>

                {/* Save button + status */}
                <div className="flex items-center gap-4 border-t border-white/10 pt-4">
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={handleSave}
                    disabled={saving || !hasChanges}
                  >
                    {saving ? "Saving..." : "Save Changes"}
                  </Button>
                  {saveMessage && (
                    <span className={`text-sm ${saveMessage.type === "success" ? "text-success-green" : "text-racing-red"}`}>
                      {saveMessage.text}
                    </span>
                  )}
                  {!hasChanges && !saveMessage && (
                    <span className="text-sm text-white/30">No unsaved changes</span>
                  )}
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
              <input
                type="text"
                value={envConfig.apiUrl}
                readOnly
                className="mt-1 w-full rounded-lg border border-white/10 bg-twilight px-3 py-2 text-white/80"
              />
              <p className="mt-1 text-xs text-white/40">Set via NEXT_PUBLIC_API_URL environment variable</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-white/60">MinIO URL</label>
              <input
                type="text"
                value={envConfig.minioUrl}
                readOnly
                className="mt-1 w-full rounded-lg border border-white/10 bg-twilight px-3 py-2 text-white/80"
              />
              <p className="mt-1 text-xs text-white/40">Set via NEXT_PUBLIC_MINIO_URL environment variable</p>
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
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-neon-cyan/10">
                  <span className="text-sm font-bold text-neon-cyan">Ovi</span>
                </div>
                <div>
                  <p className="font-medium text-white">Ovi Video Generator</p>
                  <p className="text-xs text-white/50">RunPod GPU Pod (Gradio)</p>
                </div>
              </div>
              <StatusIndicator status="connected" />
            </div>

            <div className="flex items-center justify-between rounded-lg border border-white/10 p-4">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-electric-blue/10">
                  <span className="text-sm font-bold text-electric-blue">fal</span>
                </div>
                <div>
                  <p className="font-medium text-white">fal.ai</p>
                  <p className="text-xs text-white/50">Hosted video generation (Ovi, LTX, Kling)</p>
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

        {/* fal.ai Credits & Cost Tracking */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <svg className="h-5 w-5 text-success-green" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Credits & Cost Tracking
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* fal.ai Balance */}
            {videoGenerator.startsWith("fal-") && (
              <div className="rounded-lg border border-electric-blue/30 bg-electric-blue/5 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-electric-blue/70 uppercase tracking-wider">fal.ai Credits</p>
                    <p className="text-sm text-white/60 mt-1">
                      Check balance at{" "}
                      <a href="https://fal.ai/dashboard/billing" target="_blank" rel="noopener noreferrer"
                        className="text-electric-blue hover:underline">
                        fal.ai/dashboard/billing
                      </a>
                    </p>
                  </div>
                  <a href="https://fal.ai/dashboard/billing" target="_blank" rel="noopener noreferrer">
                    <Button variant="secondary" size="sm">Check Balance</Button>
                  </a>
                </div>
                <div className="mt-3 grid grid-cols-3 gap-3">
                  <div className="rounded-lg bg-midnight/50 p-3 text-center">
                    <p className="text-xs text-white/40">Cost per clip</p>
                    <p className="mt-1 text-lg font-bold text-white">
                      ${({
                        "fal-ovi": "0.20", "fal-ltx": "0.30",
                        "fal-kling-std": "0.42", "fal-kling-std-audio": "0.63",
                        "fal-kling-pro": "0.42", "fal-kling-pro-audio": "0.84",
                      } as Record<string, string>)[videoGenerator] || "?"}
                    </p>
                  </div>
                  <div className="rounded-lg bg-midnight/50 p-3 text-center">
                    <p className="text-xs text-white/40">Per episode (24)</p>
                    <p className="mt-1 text-lg font-bold text-neon-cyan">
                      ${({
                        "fal-ovi": "4.80", "fal-ltx": "7.20",
                        "fal-kling-std": "10.08", "fal-kling-std-audio": "15.12",
                        "fal-kling-pro": "10.08", "fal-kling-pro-audio": "20.16",
                      } as Record<string, string>)[videoGenerator] || "?"}
                    </p>
                  </div>
                  <div className="rounded-lg bg-midnight/50 p-3 text-center">
                    <p className="text-xs text-white/40">Episodes possible</p>
                    <p className="mt-1 text-lg font-bold text-success-green">
                      ~{Math.floor(15 / parseFloat(({
                        "fal-ovi": "4.80", "fal-ltx": "7.20",
                        "fal-kling-std": "10.08", "fal-kling-std-audio": "15.12",
                        "fal-kling-pro": "10.08", "fal-kling-pro-audio": "20.16",
                      } as Record<string, string>)[videoGenerator] || "5"))}
                    </p>
                    <p className="text-xs text-white/30">at $15 balance</p>
                  </div>
                </div>
              </div>
            )}

            <div className="grid grid-cols-2 gap-4">
              <div className="rounded-lg border border-white/10 p-4">
                <p className="text-xs text-white/50 uppercase tracking-wider">This Month</p>
                <p className="mt-1 text-2xl font-bold text-success-green">$0.00</p>
              </div>
              <div className="rounded-lg border border-white/10 p-4">
                <p className="text-xs text-white/50 uppercase tracking-wider">Total</p>
                <p className="mt-1 text-2xl font-bold text-white">$0.00</p>
              </div>
            </div>
            <p className="text-xs text-white/40">
              Costs tracked per API call (Anthropic tokens, fal.ai video generation, ComfyUI images)
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Service Balances */}
      {balances && (
        <Card className="border-neon-cyan/30">
          <CardHeader>
            <CardTitle>Service Balances</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* fal.ai */}
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
                  balances.fal_status === "active"
                    ? "bg-success-green/20 text-success-green"
                    : "bg-racing-red/20 text-racing-red"
                }`}>
                  {balances.fal_status === "active" ? "Active" : balances.fal_status}
                </span>
                <a
                  href={balances.fal_balance_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-lg bg-white/10 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-white/20"
                >
                  View Balance
                </a>
              </div>
            </div>

            {/* RunPod */}
            <div className="flex items-center justify-between border-t border-white/10 pt-4">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-neon-cyan/20">
                  <span className="text-lg font-bold text-neon-cyan">R</span>
                </div>
                <div>
                  <p className="font-medium text-white">RunPod</p>
                  <p className="text-xs text-white/50">
                    GPU pod: {balances.runpod_pod_status || "Unknown"}
                    {balances.runpod_spend_per_hr ? ` | $${balances.runpod_spend_per_hr.toFixed(3)}/hr` : ""}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className={`rounded-full px-2 py-1 text-xs font-medium ${
                  (balances.runpod_balance ?? 0) > 1
                    ? "bg-success-green/20 text-success-green"
                    : "bg-racing-red/20 text-racing-red"
                }`}>
                  ${(balances.runpod_balance ?? 0).toFixed(2)}
                </span>
                <a
                  href="https://www.runpod.io/console/user/billing"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-lg bg-white/10 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-white/20"
                >
                  Add Funds
                </a>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Danger Zone */}
      <Card className="border-racing-red/30">
        <CardHeader>
          <CardTitle className="text-racing-red">Danger Zone</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium text-white">Clear Generation Queue</p>
              <p className="text-sm text-white/50">Cancel all pending video generations</p>
            </div>
            <Button variant="danger" size="sm">Clear Queue</Button>
          </div>
          <div className="flex items-center justify-between border-t border-white/10 pt-4">
            <div>
              <p className="font-medium text-white">Reset Database</p>
              <p className="text-sm text-white/50">Delete all episodes and scenes (characters preserved)</p>
            </div>
            <Button variant="danger" size="sm">Reset</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function StatusIndicator({ status }: { status: "connected" | "disconnected" | "error" }) {
  const styles = {
    connected: "bg-success-green/20 text-success-green",
    disconnected: "bg-white/10 text-white/50",
    error: "bg-racing-red/20 text-racing-red",
  };

  return (
    <span className={`rounded-full px-2 py-1 text-xs font-medium ${styles[status]}`}>
      {status === "connected" && "● Connected"}
      {status === "disconnected" && "○ Disconnected"}
      {status === "error" && "✕ Error"}
    </span>
  );
}
