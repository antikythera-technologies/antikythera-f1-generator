"use client";

import { useEffect, useState, useCallback } from "react";
import { Scene, SceneDetail, ScenePromptUpdateData, api } from "@/lib/api";
import { cn, formatMs, getMinioUrl } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/StatusBadge";

interface SceneDetailModalProps {
  scene: Scene;
  onClose: () => void;
}

export function SceneDetailModal({ scene, onClose }: SceneDetailModalProps) {
  const [detail, setDetail] = useState<SceneDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Editable prompt fields
  const [startFramePrompt, setStartFramePrompt] = useState("");
  const [endFramePrompt, setEndFramePrompt] = useState("");
  const [videoPrompt, setVideoPrompt] = useState("");
  const [cameraDirection, setCameraDirection] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  // Regeneration loading states
  const [regenStartFrame, setRegenStartFrame] = useState(false);
  const [regenEndFrame, setRegenEndFrame] = useState(false);
  const [regenVideo, setRegenVideo] = useState(false);
  const [regenAll, setRegenAll] = useState(false);
  const [regenMessage, setRegenMessage] = useState<string | null>(null);
  const [regenError, setRegenError] = useState<string | null>(null);
  
  // Cache-buster: increments after each regeneration to force browser to reload assets
  const [cacheBuster, setCacheBuster] = useState(0);
  
  const isRegenerating = regenStartFrame || regenEndFrame || regenVideo || regenAll;

  // Expandable sections
  const [showStartFinal, setShowStartFinal] = useState(false);
  const [showEndFinal, setShowEndFinal] = useState(false);
  const [showTechnical, setShowTechnical] = useState(false);

  const fetchDetail = useCallback(async () => {
    try {
      setLoading(true);
      const data = await api.scenes.get(scene.episode_id, scene.scene_number);
      setDetail(data);
      setStartFramePrompt(data.start_frame_prompt || "");
      setEndFramePrompt(data.end_frame_prompt || "");
      setVideoPrompt(data.video_prompt || "");
      setCameraDirection(data.camera_direction || "");
    } catch (err) {
      console.error("Failed to fetch scene detail:", err);
      setError(err instanceof Error ? err.message : "Failed to load scene details");
    } finally {
      setLoading(false);
    }
  }, [scene.episode_id, scene.scene_number]);

  useEffect(() => {
    fetchDetail();
  }, [fetchDetail]);

  // Close on escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  // Prevent body scroll when modal is open
  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, []);

  const handleSavePrompts = async () => {
    if (!detail) return;
    setSaving(true);
    setSaveMessage(null);
    try {
      const data: ScenePromptUpdateData = {};
      if (startFramePrompt !== (detail.start_frame_prompt || "")) data.start_frame_prompt = startFramePrompt;
      if (endFramePrompt !== (detail.end_frame_prompt || "")) data.end_frame_prompt = endFramePrompt;
      if (videoPrompt !== (detail.video_prompt || "")) data.video_prompt = videoPrompt;
      if (cameraDirection !== (detail.camera_direction || "")) data.camera_direction = cameraDirection;

      if (Object.keys(data).length === 0) {
        setSaveMessage("No changes to save");
        setSaving(false);
        return;
      }

      const updated = await api.scenes.updatePrompts(detail.episode_id, detail.scene_number, data);
      setDetail(updated);
      setSaveMessage("Prompts saved successfully");
    } catch (err) {
      console.error("Failed to save prompts:", err);
      setSaveMessage(err instanceof Error ? err.message : "Failed to save prompts");
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMessage(null), 3000);
    }
  };

  const handleRegenerate = async (
    action: "start-frame" | "end-frame" | "video" | "all",
    setLoadingState: (v: boolean) => void
  ) => {
    if (!detail) {
      setRegenError("Scene details not loaded yet. Close and reopen the scene.");
      return;
    }
    setLoadingState(true);
    setRegenError(null);

    const labels: Record<string, string> = {
      "start-frame": "start frame image",
      "end-frame": "end frame image",
      "video": "video clip",
      "all": "all assets (image + video)",
    };
    setRegenMessage(`Queuing ${labels[action]} regeneration...`);

    try {
      switch (action) {
        case "start-frame":
          await api.scenes.regenerateStartFrame(detail.episode_id, detail.scene_number);
          break;
        case "end-frame":
          await api.scenes.regenerateEndFrame(detail.episode_id, detail.scene_number);
          break;
        case "video":
          await api.scenes.regenerateVideo(detail.episode_id, detail.scene_number);
          break;
        case "all":
          await api.scenes.regenerateAll(detail.episode_id, detail.scene_number);
          break;
      }

      // Poll scene status until it completes or fails
      setRegenMessage(`Generating ${labels[action]}... This may take 1-5 minutes.`);
      const maxPolls = 120; // 10 minutes max (5s intervals)
      for (let i = 0; i < maxPolls; i++) {
        await new Promise((r) => setTimeout(r, 5000));
        try {
          const updated = await api.scenes.get(detail.episode_id, detail.scene_number);
          setDetail(updated);
          setStartFramePrompt(updated.start_frame_prompt || "");
          setEndFramePrompt(updated.end_frame_prompt || "");
          setVideoPrompt(updated.video_prompt || "");
          setCameraDirection(updated.camera_direction || "");

          const elapsed = (i + 1) * 5;
          if (updated.status === "completed") {
            setCacheBuster((prev) => prev + 1);
            setRegenMessage(`${labels[action]} regenerated successfully! (${elapsed}s)`);
            setTimeout(() => setRegenMessage(null), 5000);
            return;
          } else if (updated.status === "failed") {
            setRegenError(
              `${labels[action]} failed: ${updated.last_error || "Unknown error"}`
            );
            setRegenMessage(null);
            return;
          }
          // Still generating — update message with elapsed time
          setRegenMessage(
            `Generating ${labels[action]}... ${elapsed}s elapsed`
          );
        } catch {
          // Network error during poll — keep trying
        }
      }
      setRegenError(`${labels[action]} timed out after 10 minutes`);
      setRegenMessage(null);
    } catch (err) {
      console.error(`Failed to regenerate ${action}:`, err);
      const msg = err instanceof Error ? err.message : "Unknown error";
      setRegenError(`Failed to regenerate ${labels[action]}: ${msg}`);
      setRegenMessage(null);
    } finally {
      setLoadingState(false);
    }
  };

  // ALWAYS cache-bust using generation_completed_at timestamp + local cacheBuster.
  // MinIO paths don't change between regenerations (scene_01.mp4 stays scene_01.mp4),
  // so without this the browser serves stale cached assets indefinitely.
  const cacheKey = `${detail?.generation_completed_at || ""}_${cacheBuster}`;
  const addCacheBuster = (url: string | null) => {
    if (!url) return url;
    const sep = url.includes("?") ? "&" : "?";
    return `${url}${sep}v=${encodeURIComponent(cacheKey)}`;
  };
  const startFrameUrl = addCacheBuster(getMinioUrl(detail?.start_frame_path || null) || getMinioUrl(detail?.source_image_path || null));
  const endFrameUrl = addCacheBuster(getMinioUrl(detail?.end_frame_path || null));
  const videoUrl = addCacheBuster(getMinioUrl(detail?.video_clip_path || scene.video_clip_path || null));

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm animate-fade-in"
        onClick={onClose}
      />

      {/* Slide-over panel */}
      <div
        className={cn(
          "fixed inset-y-0 right-0 z-50 flex w-full flex-col",
          "bg-deep-space border-l border-neon-cyan/20",
          "shadow-[-8px_0_30px_rgba(0,240,212,0.1)]",
          "animate-slide-in-right",
          "sm:w-[600px] lg:w-[720px]"
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
          <div className="flex items-center gap-3 min-w-0">
            <span className="shrink-0 rounded-lg bg-neon-cyan/10 px-3 py-1.5 font-mono text-sm font-bold text-neon-cyan">
              #{scene.scene_number.toString().padStart(2, "0")}
            </span>
            {scene.character_name && (
              <span className="truncate text-lg font-semibold text-white">
                {scene.character_name}
              </span>
            )}
            <StatusBadge status={scene.status} size="sm" pulse={scene.status === "generating"} />
            {detail?.video_generator && (
              <span className="shrink-0 rounded-full bg-cyber-purple/20 px-2.5 py-0.5 text-xs font-medium text-cyber-purple uppercase tracking-wider">
                {detail.video_generator}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="shrink-0 rounded-lg p-2 text-white/50 transition-colors hover:bg-white/10 hover:text-white"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <div className="flex flex-col items-center gap-3">
                <div className="h-10 w-10 animate-spin rounded-full border-2 border-neon-cyan border-t-transparent" />
                <span className="text-sm text-white/50">Loading scene details...</span>
              </div>
            </div>
          ) : error ? (
            <div className="p-6">
              <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-4 text-center">
                <p className="text-sm text-racing-red">{error}</p>
                <Button variant="secondary" size="sm" className="mt-3" onClick={fetchDetail}>
                  Retry
                </Button>
              </div>
            </div>
          ) : detail ? (
            <div className="space-y-6 p-6">
              {/* Regeneration Status Overlay */}
              {(isRegenerating || regenMessage || regenError) && (
                <div className="fixed inset-0 z-[60] flex items-center justify-center bg-deep-space/80 backdrop-blur-sm">
                  <div className="mx-4 w-full max-w-md rounded-2xl border border-white/10 bg-twilight p-8 shadow-2xl">
                    {regenError ? (
                      <>
                        <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-racing-red/20">
                          <svg className="h-8 w-8 text-racing-red" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </div>
                        <h3 className="mb-2 text-center text-lg font-bold text-white">Generation Failed</h3>
                        <p className="mb-6 text-center text-sm text-racing-red">{regenError}</p>
                        <button
                          onClick={() => { setRegenError(null); setRegenMessage(null); }}
                          className="w-full rounded-lg bg-white/10 py-2.5 text-sm font-medium text-white transition-colors hover:bg-white/20"
                        >
                          Dismiss
                        </button>
                      </>
                    ) : regenMessage && !isRegenerating ? (
                      <>
                        <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-neon-cyan/20">
                          <svg className="h-8 w-8 text-neon-cyan" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                          </svg>
                        </div>
                        <h3 className="mb-2 text-center text-lg font-bold text-white">Complete</h3>
                        <p className="mb-6 text-center text-sm text-neon-cyan">{regenMessage}</p>
                        <button
                          onClick={() => setRegenMessage(null)}
                          className="w-full rounded-lg bg-neon-cyan/20 py-2.5 text-sm font-medium text-neon-cyan transition-colors hover:bg-neon-cyan/30"
                        >
                          Done
                        </button>
                      </>
                    ) : (
                      <>
                        <div className="mx-auto mb-6 h-16 w-16 animate-spin rounded-full border-4 border-neon-cyan/30 border-t-neon-cyan" />
                        <h3 className="mb-2 text-center text-lg font-bold text-white">Generating...</h3>
                        <p className="mb-1 text-center text-sm text-white/70">{regenMessage}</p>
                        <p className="text-center text-xs text-white/40">Do not close this window</p>
                      </>
                    )}
                  </div>
                </div>
              )}

              {/* Media Section — landscape layout */}
              <section>
                <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-white/50">Media</h3>
                <div className="space-y-4">
                  {/* Start Frame — full width landscape */}
                  <div className="space-y-1.5">
                    <p className="text-xs font-medium text-white/40">Start Frame</p>
                    <div className="relative aspect-video overflow-hidden rounded-lg border border-white/10 bg-twilight">
                      {startFrameUrl ? (
                        <img
                          src={startFrameUrl}
                          alt="Start frame"
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <div className="flex h-full w-full items-center justify-center">
                          <span className="text-sm text-white/20">No start frame</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Video Player — full width below start frame */}
                  {videoUrl && (
                    <div className="space-y-1.5">
                      <p className="text-xs font-medium text-white/40">Video Clip</p>
                      <div className="overflow-hidden rounded-lg border border-white/10 bg-twilight">
                        <video
                          src={videoUrl}
                          controls
                          className="w-full"
                          preload="metadata"
                        />
                      </div>
                    </div>
                  )}

                  {/* End Frame — full width below video */}
                  {endFrameUrl && (
                    <div className="space-y-1.5">
                      <p className="text-xs font-medium text-white/40">End Frame</p>
                      <div className="relative aspect-video overflow-hidden rounded-lg border border-white/10 bg-twilight">
                        <img
                          src={endFrameUrl}
                          alt="End frame"
                          className="h-full w-full object-cover"
                        />
                      </div>
                    </div>
                  )}
                </div>
              </section>

              {/* Script Section */}
              {(detail.dialogue || detail.action_description || detail.audio_description) && (
                <section>
                  <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-white/50">Script</h3>
                  <div className="space-y-3 rounded-xl border border-white/10 bg-midnight/50 p-4">
                    {detail.dialogue && (
                      <div>
                        <p className="text-xs font-medium text-white/40 mb-1">Dialogue</p>
                        <p className="text-sm text-white/80 italic leading-relaxed">
                          &ldquo;{detail.dialogue}&rdquo;
                        </p>
                      </div>
                    )}
                    {detail.action_description && (
                      <div>
                        <p className="text-xs font-medium text-white/40 mb-1">Action</p>
                        <p className="text-sm text-white/70 leading-relaxed">{detail.action_description}</p>
                      </div>
                    )}
                    {detail.audio_description && (
                      <div>
                        <p className="text-xs font-medium text-white/40 mb-1">Audio</p>
                        <p className="text-sm text-white/70 leading-relaxed">{detail.audio_description}</p>
                      </div>
                    )}
                    {detail.camera_direction && (
                      <div>
                        <p className="text-xs font-medium text-white/40 mb-1">Camera Direction</p>
                        <p className="text-sm text-neon-cyan/70 leading-relaxed">{detail.camera_direction}</p>
                      </div>
                    )}
                  </div>
                </section>
              )}

              {/* Editable Prompts Section */}
              <section>
                <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-white/50">Prompts</h3>
                <div className="space-y-4 rounded-xl border border-white/10 bg-midnight/50 p-4">
                  {/* Start Frame Prompt */}
                  <div>
                    <label className="mb-1 block text-xs font-medium text-white/40">Start Frame Prompt</label>
                    <textarea
                      value={startFramePrompt}
                      onChange={(e) => setStartFramePrompt(e.target.value)}
                      rows={8}
                      className="w-full rounded-lg border border-white/10 bg-twilight/50 px-3 py-2 text-sm text-white/90 placeholder-white/30 transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-1 focus:ring-neon-cyan/30 resize-y"
                      placeholder="Enter start frame prompt..."
                    />
                    {detail.start_frame_prompt_final && (
                      <div className="mt-1.5">
                        <button
                          onClick={() => setShowStartFinal(!showStartFinal)}
                          className="flex items-center gap-1 text-xs text-white/30 hover:text-white/50 transition-colors"
                        >
                          <svg
                            className={cn("h-3 w-3 transition-transform", showStartFinal && "rotate-90")}
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                          </svg>
                          Final enriched prompt
                        </button>
                        {showStartFinal && (
                          <div className="mt-1.5 rounded-lg bg-twilight/30 p-3 border border-white/5">
                            <p className="text-xs text-white/50 whitespace-pre-wrap leading-relaxed">
                              {detail.start_frame_prompt_final}
                            </p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {/* End Frame Prompt */}
                  <div>
                    <label className="mb-1 block text-xs font-medium text-white/40">End Frame Prompt</label>
                    <textarea
                      value={endFramePrompt}
                      onChange={(e) => setEndFramePrompt(e.target.value)}
                      rows={8}
                      className="w-full rounded-lg border border-white/10 bg-twilight/50 px-3 py-2 text-sm text-white/90 placeholder-white/30 transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-1 focus:ring-neon-cyan/30 resize-y"
                      placeholder="Enter end frame prompt..."
                    />
                    {detail.end_frame_prompt_final && (
                      <div className="mt-1.5">
                        <button
                          onClick={() => setShowEndFinal(!showEndFinal)}
                          className="flex items-center gap-1 text-xs text-white/30 hover:text-white/50 transition-colors"
                        >
                          <svg
                            className={cn("h-3 w-3 transition-transform", showEndFinal && "rotate-90")}
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                          </svg>
                          Final enriched prompt
                        </button>
                        {showEndFinal && (
                          <div className="mt-1.5 rounded-lg bg-twilight/30 p-3 border border-white/5">
                            <p className="text-xs text-white/50 whitespace-pre-wrap leading-relaxed">
                              {detail.end_frame_prompt_final}
                            </p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Video Prompt */}
                  <div>
                    <label className="mb-1 block text-xs font-medium text-white/40">Video Prompt</label>
                    <textarea
                      value={videoPrompt}
                      onChange={(e) => setVideoPrompt(e.target.value)}
                      rows={6}
                      className="w-full rounded-lg border border-white/10 bg-twilight/50 px-3 py-2 text-sm text-white/90 placeholder-white/30 transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-1 focus:ring-neon-cyan/30 resize-y"
                      placeholder="Enter video prompt..."
                    />
                  </div>

                  {/* Camera Direction */}
                  <div>
                    <label className="mb-1 block text-xs font-medium text-white/40">Camera Direction</label>
                    <input
                      type="text"
                      value={cameraDirection}
                      onChange={(e) => setCameraDirection(e.target.value)}
                      className="w-full rounded-lg border border-white/10 bg-twilight/50 px-3 py-2 text-sm text-white/90 placeholder-white/30 transition-colors focus:border-neon-cyan/50 focus:outline-none focus:ring-1 focus:ring-neon-cyan/30"
                      placeholder="e.g., slow zoom in, pan left..."
                    />
                  </div>

                  {/* Save Button */}
                  <div className="flex items-center gap-3 pt-1">
                    <Button variant="primary" size="sm" loading={saving} onClick={handleSavePrompts}>
                      Save Prompts
                    </Button>
                    {saveMessage && (
                      <span className={cn(
                        "text-xs",
                        saveMessage.includes("success") ? "text-success-green" : "text-white/50"
                      )}>
                        {saveMessage}
                      </span>
                    )}
                  </div>
                </div>
              </section>

              {/* Regeneration Actions */}
              <section>
                <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-white/50">Regeneration</h3>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={regenStartFrame}
                    onClick={() => handleRegenerate("start-frame", setRegenStartFrame)}
                  >
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    Regenerate Start Frame
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={regenEndFrame}
                    onClick={() => handleRegenerate("end-frame", setRegenEndFrame)}
                  >
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    Regenerate End Frame
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={regenVideo}
                    onClick={() => handleRegenerate("video", setRegenVideo)}
                  >
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    Regenerate Video
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    loading={regenAll}
                    onClick={() => handleRegenerate("all", setRegenAll)}
                  >
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    Regenerate All
                  </Button>
                </div>
              </section>

              {/* Technical Details (collapsed) */}
              <section>
                <button
                  onClick={() => setShowTechnical(!showTechnical)}
                  className="flex w-full items-center gap-2 text-sm font-semibold uppercase tracking-wider text-white/50 hover:text-white/70 transition-colors"
                >
                  <svg
                    className={cn("h-4 w-4 transition-transform", showTechnical && "rotate-90")}
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                  Technical Details
                </button>

                {showTechnical && (
                  <div className="mt-3 space-y-3 rounded-xl border border-white/10 bg-midnight/50 p-4">
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <p className="text-xs text-white/40">Generation Time</p>
                        <p className="mt-0.5 text-sm font-mono text-white/70">
                          {detail.generation_time_ms ? formatMs(detail.generation_time_ms) : "N/A"}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-white/40">Retry Count</p>
                        <p className="mt-0.5 text-sm font-mono text-white/70">{detail.retry_count}</p>
                      </div>
                      <div>
                        <p className="text-xs text-white/40">Duration</p>
                        <p className="mt-0.5 text-sm font-mono text-white/70">{detail.duration_seconds}s</p>
                      </div>
                      <div>
                        <p className="text-xs text-white/40">Character Image ID</p>
                        <p className="mt-0.5 text-sm font-mono text-white/70">
                          {detail.character_image_id ?? "N/A"}
                        </p>
                      </div>
                    </div>

                    {/* Pipeline & Cost Info */}
                    <div className="grid grid-cols-2 gap-4 border-t border-white/10 pt-3">
                      <div>
                        <p className="text-xs text-white/40">Image Backend</p>
                        <p className="mt-0.5 text-sm font-mono text-white/70">
                          {detail.image_backend || "N/A"}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-white/40">Video Backend</p>
                        <p className="mt-0.5 text-sm font-mono text-white/70">
                          {detail.video_generator || "N/A"}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-white/40">Image Cost</p>
                        <p className="mt-0.5 text-sm font-mono text-neon-cyan">
                          {detail.image_cost_usd ? `$${detail.image_cost_usd.toFixed(4)}` : "N/A"}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-white/40">Video Cost</p>
                        <p className="mt-0.5 text-sm font-mono text-cyber-purple">
                          {detail.video_cost_usd ? `$${detail.video_cost_usd.toFixed(4)}` : "N/A"}
                        </p>
                      </div>
                      {(detail.image_cost_usd || detail.video_cost_usd) && (
                        <div className="col-span-2">
                          <p className="text-xs text-white/40">Total Scene Cost</p>
                          <p className="mt-0.5 text-sm font-mono font-bold text-electric-blue">
                            ${((detail.image_cost_usd || 0) + (detail.video_cost_usd || 0)).toFixed(4)}
                          </p>
                        </div>
                      )}
                    </div>

                    {detail.last_error && (
                      <div>
                        <p className="text-xs text-white/40 mb-1">Last Error</p>
                        <div className="rounded-lg bg-racing-red/10 border border-racing-red/20 p-3">
                          <p className="text-xs text-racing-red font-mono whitespace-pre-wrap">{detail.last_error}</p>
                        </div>
                      </div>
                    )}

                    {detail.ovi_prompt && (
                      <div>
                        <p className="text-xs text-white/40 mb-1">Ovi Prompt (Legacy)</p>
                        <div className="rounded-lg bg-twilight/30 border border-white/5 p-3">
                          <p className="text-xs text-white/50 whitespace-pre-wrap">{detail.ovi_prompt}</p>
                        </div>
                      </div>
                    )}

                    {detail.script_prompt && (
                      <div>
                        <p className="text-xs text-white/40 mb-1">Script Prompt</p>
                        <div className="rounded-lg bg-twilight/30 border border-white/5 p-3 max-h-48 overflow-y-auto">
                          <p className="text-xs text-white/50 whitespace-pre-wrap">{detail.script_prompt}</p>
                        </div>
                      </div>
                    )}

                    {detail.script_response && (
                      <div>
                        <p className="text-xs text-white/40 mb-1">Script Response</p>
                        <div className="rounded-lg bg-twilight/30 border border-white/5 p-3 max-h-48 overflow-y-auto">
                          <p className="text-xs text-white/50 whitespace-pre-wrap">{detail.script_response}</p>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </section>
            </div>
          ) : null}
        </div>
      </div>

    </>
  );
}
