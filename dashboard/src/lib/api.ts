/**
 * API Client for Antikythera F1 Video Generator Backend
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api/v1";

// Types
export type EpisodeStatus = "pending" | "generating" | "stitching" | "uploading" | "published" | "failed";
export type EpisodeType = "pre-race" | "post-race" | "post-fp2" | "post-sprint" | "weekly-recap";
export type JobStatus = "scheduled" | "running" | "completed" | "failed" | "cancelled";
export type JobTriggerType = "post-fp2" | "post-sprint" | "post-race" | "weekly-recap" | "manual";
export type ArticleContext = "race-weekend" | "off-week" | "breaking" | "feature";
export type SceneStatus = "pending" | "generating" | "completed" | "failed";

export interface Race {
  id: number;
  season: number;
  round_number: number;
  race_name: string;
  circuit_name: string | null;
  country: string | null;
  race_date: string;
  fp1_datetime: string | null;
  fp2_datetime: string | null;
  fp3_datetime: string | null;
  qualifying_datetime: string | null;
  race_datetime: string | null;
  is_sprint_weekend: boolean;
  sprint_qualifying_datetime: string | null;
  sprint_race_datetime: string | null;
  created_at: string;
}

export interface ScheduledJob {
  id: number;
  race_id: number | null;
  trigger_type: JobTriggerType;
  scheduled_for: string;
  description: string | null;
  status: JobStatus;
  started_at: string | null;
  completed_at: string | null;
  episode_id: number | null;
  error_message: string | null;
  retry_count: number;
  max_retries: number;
  scrape_context: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  // Enriched fields
  race_name?: string;
  race_country?: string;
  is_sprint_weekend?: boolean;
}

export interface NewsSource {
  id: number;
  name: string;
  url: string;
  feed_url: string | null;
  scrape_selector: string | null;
  is_active: boolean;
  priority: number;
  last_scraped_at: string | null;
  created_at: string;
}

export interface NewsArticle {
  id: number;
  source_id: number | null;
  source_name?: string;
  title: string;
  url: string;
  summary: string | null;
  full_content: string | null;
  context: ArticleContext;
  keywords: string[] | null;
  mentioned_drivers: string[] | null;
  mentioned_teams: string[] | null;
  sentiment_score: number | null;
  published_at: string | null;
  scraped_at: string;
  used_in_episode_id: number | null;
  used_at: string | null;
  is_processed: boolean;
  created_at: string;
}

export interface EpisodeStoryline {
  id: number;
  episode_id: number;
  main_storyline: string;
  secondary_storylines: string[] | null;
  comedic_angle: string | null;
  news_article_ids: number[] | null;
  key_facts: Record<string, unknown> | null;
  prompt_used: string | null;
  model_used: string | null;
  tokens_used: number | null;
  created_at: string;
}

export interface CalendarSyncResponse {
  races_checked: number;
  jobs_created: number;
  jobs_updated: number;
  off_weeks_scheduled: number;
}

export interface ScrapeRequest {
  context_type: string;
  focus_areas: string[];
  date_range_hours?: number;
  date_range_days?: number;
  max_articles: number;
}

export interface ScrapeResponse {
  articles_scraped: number;
  sources_checked: number;
  errors: string[];
}

export interface Character {
  id: number;
  name: string;
  display_name: string;
  description: string | null;
  voice_description: string | null;
  personality: string | null;
  primary_image_path: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  images: CharacterImage[];
}

export interface CharacterImage {
  id: number;
  character_id: number;
  image_path: string;
  image_type: string;
  pose_description: string | null;
  is_primary: boolean;
  created_at: string;
}

export interface Scene {
  id: number;
  episode_id: number;
  scene_number: number;
  character_id: number | null;
  character_name?: string;
  script_prompt: string | null;
  dialogue: string | null;
  action_description: string | null;
  audio_description: string | null;
  status: SceneStatus;
  source_image_path: string | null;
  video_clip_path: string | null;
  duration_seconds: number;
  generation_time_ms: number | null;
  retry_count: number;
  last_error: string | null;
  created_at: string;
}

export interface Episode {
  id: number;
  race_id: number | null;
  race_name?: string | null;
  race?: Race;
  episode_type: EpisodeType;
  title: string;
  description: string | null;
  status: EpisodeStatus;
  triggered_at: string;
  generation_started_at: string | null;
  generation_completed_at: string | null;
  published_at: string | null;
  final_video_path: string | null;
  youtube_video_id: string | null;
  youtube_url: string | null;
  duration_seconds: number | null;
  scene_count: number;
  generation_time_seconds: number | null;
  anthropic_tokens_used: number;
  anthropic_cost_usd: number;
  ovi_calls: number;
  total_cost_usd: number;
  scenes?: Scene[];
  created_at: string;
}

export interface GenerateEpisodeRequest {
  race_id: number;
  episode_type: EpisodeType;
  force?: boolean;
}

export interface GenerateEpisodeResponse {
  episode_id: number;
  status: EpisodeStatus;
  estimated_completion_minutes: number;
}

export interface CostAnalytics {
  period: string;
  total_cost_usd: number;
  breakdown: {
    anthropic: number;
    ovi: number;
    youtube: number;
    storage: number;
  };
  episodes_generated: number;
  total_tokens: number;
}

export interface DashboardStats {
  total_episodes: number;
  episodes_generating: number;
  episodes_published: number;
  episodes_failed: number;
  total_characters: number;
  upcoming_races: number;
  total_cost_usd: number;
}

// API Error handling
class APIError extends Error {
  constructor(
    public status: number,
    message: string,
    public details?: unknown
  ) {
    super(message);
    this.name = "APIError";
  }
}

async function request<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  
  try {
    const response = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        ...options?.headers,
      },
      ...options,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new APIError(response.status, error.detail || response.statusText, error);
    }

    return response.json();
  } catch (error) {
    if (error instanceof APIError) throw error;
    throw new APIError(0, "Network error - is the backend running?", error);
  }
}

// Episodes API
export const episodesApi = {
  list: (params?: { status?: EpisodeStatus; race_id?: number; limit?: number; offset?: number }) => {
    const searchParams = new URLSearchParams();
    if (params?.status) searchParams.set("status", params.status);
    if (params?.race_id) searchParams.set("race_id", String(params.race_id));
    if (params?.limit) searchParams.set("limit", String(params.limit));
    if (params?.offset) searchParams.set("offset", String(params.offset));
    const query = searchParams.toString();
    return request<Episode[]>(`/episodes${query ? `?${query}` : ""}`);
  },

  get: (id: number) => request<Episode>(`/episodes/${id}`),

  generate: (data: GenerateEpisodeRequest) =>
    request<GenerateEpisodeResponse>("/episodes/generate", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  retry: (id: number, sceneIds?: number[]) =>
    request<{ status: string; episode_id: number }>(`/episodes/${id}/retry`, {
      method: "POST",
      body: JSON.stringify({ scene_ids: sceneIds || [] }),
    }),
};

// Characters API
export const charactersApi = {
  list: () => request<Character[]>("/characters"),
  get: (id: number) => request<Character>(`/characters/${id}`),
  create: (data: Partial<Character>) =>
    request<Character>("/characters", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  update: (id: number, data: Partial<Character>) =>
    request<Character>(`/characters/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
};

// Races API
export const racesApi = {
  list: (params?: { season?: number; upcoming_only?: boolean }) => {
    const searchParams = new URLSearchParams();
    if (params?.season) searchParams.set("season", String(params.season));
    if (params?.upcoming_only) searchParams.set("upcoming_only", "true");
    const query = searchParams.toString();
    return request<Race[]>(`/races${query ? `?${query}` : ""}`);
  },
  get: (id: number) => request<Race>(`/races/${id}`),
  sync: () => request<{ status: string }>("/races/sync", { method: "POST" }),
};

// Analytics API
export const analyticsApi = {
  costs: (params?: { start_date?: string; end_date?: string; group_by?: string }) => {
    const searchParams = new URLSearchParams();
    if (params?.start_date) searchParams.set("start_date", params.start_date);
    if (params?.end_date) searchParams.set("end_date", params.end_date);
    if (params?.group_by) searchParams.set("group_by", params.group_by);
    const query = searchParams.toString();
    return request<CostAnalytics[]>(`/analytics/costs${query ? `?${query}` : ""}`);
  },
  stats: () => request<DashboardStats>("/analytics/stats"),
};

// Scheduler API
export const schedulerApi = {
  sync: (season?: number) => {
    const query = season ? `?season=${season}` : "";
    return request<CalendarSyncResponse>(`/scheduler/sync${query}`, { method: "POST" });
  },
  
  listJobs: (params?: { status?: JobStatus; limit?: number }) => {
    const searchParams = new URLSearchParams();
    if (params?.status) searchParams.set("status", params.status);
    if (params?.limit) searchParams.set("limit", String(params.limit));
    const query = searchParams.toString();
    return request<ScheduledJob[]>(`/scheduler/jobs${query ? `?${query}` : ""}`);
  },
  
  getUpcoming: (days?: number) => {
    const query = days ? `?days=${days}` : "";
    return request<{ jobs: ScheduledJob[]; total: number }>(`/scheduler/jobs/upcoming${query}`);
  },
  
  getPending: (limit?: number) => {
    const query = limit ? `?limit=${limit}` : "";
    return request<ScheduledJob[]>(`/scheduler/jobs/pending${query}`);
  },
  
  getJob: (id: number) => request<ScheduledJob>(`/scheduler/jobs/${id}`),
  
  createJob: (data: Partial<ScheduledJob>) =>
    request<ScheduledJob>("/scheduler/jobs", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  
  cancelJob: (id: number) =>
    request<ScheduledJob>(`/scheduler/jobs/${id}/cancel`, { method: "POST" }),
  
  triggerJob: (id: number) =>
    request<{ status: string; job_id: number; message: string }>(`/scheduler/jobs/${id}/run`, { method: "POST" }),
};

// News API
export const newsApi = {
  listSources: (activeOnly?: boolean) => {
    const query = activeOnly === false ? "?active_only=false" : "";
    return request<NewsSource[]>(`/news/sources${query}`);
  },
  
  createSource: (data: Partial<NewsSource>) =>
    request<NewsSource>("/news/sources", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  
  updateSource: (id: number, data: { is_active?: boolean; priority?: number }) =>
    request<NewsSource>(`/news/sources/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  
  listArticles: (params?: { context?: ArticleContext; source_id?: number; used?: boolean; limit?: number }) => {
    const searchParams = new URLSearchParams();
    if (params?.context) searchParams.set("context", params.context);
    if (params?.source_id) searchParams.set("source_id", String(params.source_id));
    if (params?.used !== undefined) searchParams.set("used", String(params.used));
    if (params?.limit) searchParams.set("limit", String(params.limit));
    const query = searchParams.toString();
    return request<NewsArticle[]>(`/news/articles${query ? `?${query}` : ""}`);
  },
  
  getArticle: (id: number) => request<NewsArticle>(`/news/articles/${id}`),
  
  fetchContent: (id: number) =>
    request<{ status: string; content_length: number }>(`/news/articles/${id}/fetch-content`, { method: "POST" }),
  
  scrape: (data: ScrapeRequest) =>
    request<ScrapeResponse>("/news/scrape", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  
  getForEpisode: (triggerType: JobTriggerType, raceId?: number, limit?: number) => {
    const searchParams = new URLSearchParams();
    searchParams.set("trigger_type", triggerType);
    if (raceId) searchParams.set("race_id", String(raceId));
    if (limit) searchParams.set("limit", String(limit));
    return request<NewsArticle[]>(`/news/for-episode?${searchParams.toString()}`);
  },
};

// Export all APIs
export const api = {
  episodes: episodesApi,
  characters: charactersApi,
  races: racesApi,
  analytics: analyticsApi,
  scheduler: schedulerApi,
  news: newsApi,
};

export default api;
