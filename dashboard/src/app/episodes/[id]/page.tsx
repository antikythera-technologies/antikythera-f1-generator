"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api, Episode, Scene } from "@/lib/api";
import { formatDateTime, formatDuration, formatCurrency, cn, getMinioUrl } from "@/lib/utils";
import { Header } from "@/components/layout/Header";
import { Button, StatusBadge, GenerationProgress, LoadingPage, Card, CardContent } from "@/components/ui";
import { SceneCard } from "@/components/episodes/SceneCard";
import { SceneDetailModal } from "@/components/episodes/SceneDetailModal";

export default function EpisodeDetailPage() {
  const params = useParams();
  const router = useRouter();
  const episodeId = Number(params.id);

  const [episode, setEpisode] = useState<Episode | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [selectedScene, setSelectedScene] = useState<Scene | null>(null);
  const [stitching, setStitching] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [validating, setValidating] = useState(false);

  const fetchEpisode = useCallback(async () => {
    try {
      const data = await api.episodes.get(episodeId);
      setEpisode(data);
    } catch (err) {
      console.error("Failed to fetch episode:", err);
      setError(err instanceof Error ? err.message : "Failed to load episode");
    } finally {
      setLoading(false);
    }
  }, [episodeId]);

  useEffect(() => {
    fetchEpisode();

    // Poll for updates if generating/stitching/uploading
    const interval = setInterval(() => {
      if (episode && ["generating", "stitching", "uploading"].includes(episode.status)) {
        fetchEpisode();
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [episodeId, episode?.status, fetchEpisode]);

  const handleRetry = async (sceneIds?: number[]) => {
    if (!episode) return;

    setRetrying(true);
    try {
      await api.episodes.retry(episode.id, sceneIds);
      await fetchEpisode();
    } catch (err) {
      console.error("Retry failed:", err);
    } finally {
      setRetrying(false);
    }
  };

  const handleStitch = async () => {
    if (!episode) return;
    setStitching(true);
    try {
      await api.episodes.stitch(episode.id);
      await fetchEpisode();
    } catch (err) {
      console.error("Stitch failed:", err);
    } finally {
      setStitching(false);
    }
  };

  const handleUploadYoutube = async () => {
    if (!episode) return;
    setUploading(true);
    try {
      await api.episodes.uploadYoutube(episode.id);
      await fetchEpisode();
    } catch (err) {
      console.error("Upload failed:", err);
    } finally {
      setUploading(false);
    }
  };

  const handleValidate = async () => {
    if (!episode) return;
    setValidating(true);
    try {
      await api.episodes.validate(episode.id);
      await fetchEpisode();
    } catch (err) {
      console.error("Validate failed:", err);
    } finally {
      setValidating(false);
    }
  };

  if (loading) {
    return <LoadingPage text="Loading episode..." />;
  }

  if (error || !episode) {
    return (
      <div className="space-y-4">
        <Header title="Episode Not Found" />
        <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-6 text-center">
          <p className="text-racing-red">{error || "Episode not found"}</p>
          <Link href="/episodes" className="mt-4 inline-block">
            <Button variant="secondary">Back to Episodes</Button>
          </Link>
        </div>
      </div>
    );
  }

  const isGenerating = ["generating", "stitching", "uploading"].includes(episode.status);
  const completedScenes = episode.scenes?.filter(s => s.status === "completed").length || 0;
  const failedScenes = episode.scenes?.filter(s => s.status === "failed") || [];
  const allScenesCompleted = completedScenes === episode.scene_count && episode.scene_count > 0;
  const hasFinalVideo = !!episode.final_video_path;
  const finalVideoUrl = getMinioUrl(episode.final_video_path, episode.generation_completed_at || true);

  return (
    <div className="space-y-8">
      <Header
        title={episode.title}
        subtitle={episode.race?.race_name || "Unknown Race"}
        actions={
          <div className="flex items-center gap-3 flex-wrap">
            {/* Validate Scenes */}
            {completedScenes > 0 && (
              <Button
                variant="secondary"
                loading={validating}
                onClick={handleValidate}
                disabled={isGenerating}
              >
                <svg className="h-4 w-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Validate Scenes
              </Button>
            )}

            {/* Stitch Episode */}
            {allScenesCompleted && (
              <Button
                variant="secondary"
                loading={stitching || episode.status === "stitching"}
                onClick={handleStitch}
                disabled={isGenerating && episode.status !== "stitching"}
              >
                <svg className="h-4 w-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 4V2m0 2a2 2 0 012 2v1H5V6a2 2 0 012-2zm0 12v2m0-2a2 2 0 01-2-2v-1h4v1a2 2 0 01-2 2zM17 4V2m0 2a2 2 0 012 2v1h-4V6a2 2 0 012-2zm0 12v2m0-2a2 2 0 01-2-2v-1h4v1a2 2 0 01-2 2z" />
                </svg>
                {hasFinalVideo ? "Re-stitch" : "Stitch Episode"}
              </Button>
            )}

            {/* Upload to YouTube */}
            {hasFinalVideo && !episode.youtube_url && (
              <Button
                variant="primary"
                loading={uploading || episode.status === "uploading"}
                onClick={handleUploadYoutube}
                disabled={isGenerating && episode.status !== "uploading"}
              >
                <svg className="h-4 w-4 mr-1" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M19.615 3.184c-3.604-.246-11.631-.245-15.23 0-3.897.266-4.356 2.62-4.385 8.816.029 6.185.484 8.549 4.385 8.816 3.6.245 11.626.246 15.23 0 3.897-.266 4.356-2.62 4.385-8.816-.029-6.185-.484-8.549-4.385-8.816zm-10.615 12.816v-8l8 3.993-8 4.007z"/>
                </svg>
                Upload to YouTube
              </Button>
            )}

            {/* Watch on YouTube */}
            {episode.youtube_url && (
              <a href={episode.youtube_url} target="_blank" rel="noopener noreferrer">
                <Button variant="secondary">
                  <svg className="h-4 w-4 mr-1" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M19.615 3.184c-3.604-.246-11.631-.245-15.23 0-3.897.266-4.356 2.62-4.385 8.816.029 6.185.484 8.549 4.385 8.816 3.6.245 11.626.246 15.23 0 3.897-.266 4.356-2.62 4.385-8.816-.029-6.185-.484-8.549-4.385-8.816zm-10.615 12.816v-8l8 3.993-8 4.007z"/>
                  </svg>
                  Watch on YouTube
                </Button>
              </a>
            )}

            {/* Retry Failed */}
            {(episode.status === "failed" || failedScenes.length > 0) && (
              <Button
                variant="danger"
                loading={retrying}
                onClick={() => handleRetry(failedScenes.map(s => s.id))}
              >
                Retry Failed Scenes
              </Button>
            )}
          </div>
        }
      />

      {/* Final Video Player */}
      {hasFinalVideo && finalVideoUrl && (
        <Card>
          <CardContent>
            <h2 className="mb-3 text-lg font-semibold text-white">Final Episode Video</h2>
            <div className="relative aspect-video w-full overflow-hidden rounded-lg bg-black">
              <video
                className="h-full w-full"
                controls
                preload="metadata"
              >
                <source src={finalVideoUrl} type="video/mp4" />
                Your browser does not support the video tag.
              </video>
            </div>
            <div className="mt-3 flex items-center gap-4 text-sm text-white/60">
              {episode.duration_seconds && (
                <span>Duration: {formatDuration(episode.duration_seconds)}</span>
              )}
              {episode.youtube_url && (
                <a
                  href={episode.youtube_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-electric-blue hover:text-electric-blue/80 transition-colors"
                >
                  View on YouTube
                </a>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Status & Progress */}
      <Card>
        <CardContent className="space-y-6">
          <div className="flex items-center justify-between">
            <StatusBadge status={episode.status} size="lg" pulse={isGenerating} />
            {episode.generation_time_seconds && (
              <span className="text-sm text-white/60">
                Generation time: {formatDuration(episode.generation_time_seconds)}
              </span>
            )}
          </div>

          {isGenerating && (
            <GenerationProgress
              current={completedScenes}
              total={episode.scene_count}
              status={episode.status}
            />
          )}

          {/* Stats Grid */}
          <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
            <div>
              <p className="text-xs text-white/50 uppercase tracking-wider">Type</p>
              <p className={cn(
                "mt-1 text-lg font-semibold",
                episode.episode_type === "pre-race" ? "text-electric-blue" : "text-cyber-purple"
              )}>
                {episode.episode_type.replace("-", " ").replace(/\b\w/g, c => c.toUpperCase())}
              </p>
            </div>
            <div>
              <p className="text-xs text-white/50 uppercase tracking-wider">Scenes</p>
              <p className="mt-1 text-lg font-semibold text-white">
                {completedScenes}/{episode.scene_count}
              </p>
            </div>
            <div>
              <p className="text-xs text-white/50 uppercase tracking-wider">Total Cost</p>
              <p className="mt-1 text-lg font-semibold text-success-green">
                {formatCurrency(episode.total_cost_usd)}
              </p>
            </div>
            <div>
              <p className="text-xs text-white/50 uppercase tracking-wider">Ovi Calls</p>
              <p className="mt-1 text-lg font-semibold text-neon-cyan">
                {episode.ovi_calls}
              </p>
            </div>
          </div>

          {/* Timestamps */}
          <div className="grid grid-cols-2 gap-4 border-t border-white/10 pt-6 sm:grid-cols-4">
            <div>
              <p className="text-xs text-white/50">Created</p>
              <p className="mt-1 text-sm text-white/70">{formatDateTime(episode.triggered_at)}</p>
            </div>
            {episode.generation_started_at && (
              <div>
                <p className="text-xs text-white/50">Started</p>
                <p className="mt-1 text-sm text-white/70">{formatDateTime(episode.generation_started_at)}</p>
              </div>
            )}
            {episode.generation_completed_at && (
              <div>
                <p className="text-xs text-white/50">Completed</p>
                <p className="mt-1 text-sm text-white/70">{formatDateTime(episode.generation_completed_at)}</p>
              </div>
            )}
            {episode.published_at && (
              <div>
                <p className="text-xs text-white/50">Published</p>
                <p className="mt-1 text-sm text-white/70">{formatDateTime(episode.published_at)}</p>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Scenes Grid */}
      <section>
        <h2 className="mb-4 text-xl font-semibold text-white">
          Scenes ({episode.scenes?.length || 0})
        </h2>

        {episode.scenes && episode.scenes.length > 0 ? (
          <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
            {episode.scenes
              .sort((a, b) => a.scene_number - b.scene_number)
              .map((scene) => (
                <SceneCard
                  key={scene.id}
                  scene={scene}
                  onRegenerate={(sceneId) => handleRetry([sceneId])}
                  onView={(scene) => setSelectedScene(scene)}
                />
              ))}
          </div>
        ) : (
          <div className="rounded-xl border border-white/10 bg-midnight/50 p-8 text-center">
            <p className="text-white/60">No scenes generated yet</p>
          </div>
        )}
      </section>

      {/* Scene Detail Modal */}
      {selectedScene && (
        <SceneDetailModal
          scene={selectedScene}
          onClose={() => setSelectedScene(null)}
        />
      )}
    </div>
  );
}
