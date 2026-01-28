"use client";

import { useState } from "react";
import { Header } from "@/components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle, Button } from "@/components/ui";

export default function SettingsPage() {
  const [saving, setSaving] = useState(false);

  // These would normally come from environment or an API
  const config = {
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
                value={config.apiUrl}
                readOnly
                className="mt-1 w-full rounded-lg border border-white/10 bg-twilight px-3 py-2 text-white/80"
              />
              <p className="mt-1 text-xs text-white/40">Set via NEXT_PUBLIC_API_URL environment variable</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-white/60">MinIO URL</label>
              <input
                type="text"
                value={config.minioUrl}
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

        {/* Video Generation */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <svg className="h-5 w-5 text-cyber-purple" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
              Video Generation
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-white/60">Scene Count</label>
                <div className="mt-1 rounded-lg border border-white/10 bg-twilight px-3 py-2 text-white">24</div>
              </div>
              <div>
                <label className="block text-sm font-medium text-white/60">Scene Duration</label>
                <div className="mt-1 rounded-lg border border-white/10 bg-twilight px-3 py-2 text-white">5 seconds</div>
              </div>
              <div>
                <label className="block text-sm font-medium text-white/60">Total Duration</label>
                <div className="mt-1 rounded-lg border border-white/10 bg-twilight px-3 py-2 text-white">2 minutes</div>
              </div>
              <div>
                <label className="block text-sm font-medium text-white/60">Resolution</label>
                <div className="mt-1 rounded-lg border border-white/10 bg-twilight px-3 py-2 text-white">1080p</div>
              </div>
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
                  <p className="text-xs text-white/50">HuggingFace Gradio Space</p>
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
                  <p className="text-xs text-white/50">Script generation (Haiku)</p>
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

        {/* Cost Tracking */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <svg className="h-5 w-5 text-success-green" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Cost Tracking
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
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
              Costs are tracked per API call (Anthropic tokens, Ovi calls)
            </p>
          </CardContent>
        </Card>
      </div>

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
