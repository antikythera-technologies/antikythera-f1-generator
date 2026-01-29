"use client";

import { useEffect, useState } from "react";
import { api, ScheduledJob, JobStatus } from "@/lib/api";
import { formatDateTime, formatRelativeTime } from "@/lib/utils";
import { Header } from "@/components/layout/Header";
import { Button, Card, LoadingPage, StatusBadge } from "@/components/ui";

const statusColors: Record<JobStatus, "cyan" | "blue" | "green" | "red" | "gray"> = {
  scheduled: "cyan",
  running: "blue",
  completed: "green",
  failed: "red",
  cancelled: "gray",
};

const triggerTypeLabels: Record<string, string> = {
  "post-fp2": "Post FP2",
  "post-sprint": "Post Sprint",
  "post-race": "Post Race",
  "weekly-recap": "Weekly Recap",
  "manual": "Manual",
};

export default function SchedulerPage() {
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [upcomingJobs, setUpcomingJobs] = useState<ScheduledJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<JobStatus | "all">("all");

  useEffect(() => {
    fetchData();
  }, [filter]);

  async function fetchData() {
    try {
      setLoading(true);
      
      // Fetch upcoming jobs
      const upcoming = await api.scheduler.getUpcoming(14);
      setUpcomingJobs(upcoming.jobs);
      
      // Fetch all jobs with optional filter
      const allJobs = await api.scheduler.listJobs({
        status: filter === "all" ? undefined : filter,
        limit: 50,
      });
      setJobs(allJobs);
      
      setError(null);
    } catch (err) {
      console.error("Failed to fetch scheduler data:", err);
      setError(err instanceof Error ? err.message : "Failed to load scheduler");
    } finally {
      setLoading(false);
    }
  }

  async function handleSync() {
    try {
      setSyncing(true);
      const result = await api.scheduler.sync();
      alert(`Synced! Created ${result.jobs_created} jobs, scheduled ${result.off_weeks_scheduled} off-week recaps`);
      await fetchData();
    } catch (err) {
      console.error("Sync failed:", err);
      setError(err instanceof Error ? err.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  }

  async function handleTrigger(jobId: number) {
    try {
      await api.scheduler.triggerJob(jobId);
      await fetchData();
    } catch (err) {
      console.error("Trigger failed:", err);
      alert(err instanceof Error ? err.message : "Failed to trigger job");
    }
  }

  async function handleCancel(jobId: number) {
    if (!confirm("Cancel this job?")) return;
    try {
      await api.scheduler.cancelJob(jobId);
      await fetchData();
    } catch (err) {
      console.error("Cancel failed:", err);
      alert(err instanceof Error ? err.message : "Failed to cancel job");
    }
  }

  if (loading) {
    return <LoadingPage text="Loading scheduler..." />;
  }

  return (
    <div className="space-y-8">
      <Header
        title="Content Scheduler"
        subtitle="Manage automated video generation schedule"
        actions={
          <Button onClick={handleSync} disabled={syncing}>
            {syncing ? (
              <>
                <svg className="h-4 w-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
                Syncing...
              </>
            ) : (
              <>
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                Sync Calendar
              </>
            )}
          </Button>
        }
      />

      {error && (
        <div className="rounded-lg border border-racing-red/50 bg-racing-red/10 p-4">
          <p className="text-racing-red">{error}</p>
        </div>
      )}

      {/* Upcoming Jobs Timeline */}
      <section>
        <h2 className="mb-4 text-xl font-semibold text-white">Upcoming Content (Next 14 Days)</h2>
        
        {upcomingJobs.length === 0 ? (
          <Card className="p-8 text-center">
            <svg className="mx-auto h-12 w-12 text-white/20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            <h3 className="mt-4 text-lg font-medium text-white">No upcoming jobs</h3>
            <p className="mt-2 text-white/60">Sync the calendar to schedule content generation</p>
          </Card>
        ) : (
          <div className="relative">
            {/* Timeline line */}
            <div className="absolute left-4 top-0 bottom-0 w-0.5 bg-white/10" />
            
            <div className="space-y-4">
              {upcomingJobs.map((job) => (
                <div key={job.id} className="relative ml-10">
                  {/* Timeline dot */}
                  <div className={`absolute -left-[26px] top-3 h-3 w-3 rounded-full border-2 ${
                    job.status === "running" ? "bg-electric-blue border-electric-blue animate-pulse" :
                    job.status === "completed" ? "bg-success-green border-success-green" :
                    job.status === "failed" ? "bg-racing-red border-racing-red" :
                    "bg-midnight border-neon-cyan"
                  }`} />
                  
                  <Card className="p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className={`rounded px-2 py-0.5 text-xs font-medium ${
                            job.trigger_type === "weekly-recap" ? "bg-cyber-purple/20 text-cyber-purple" :
                            job.trigger_type === "post-fp2" ? "bg-neon-cyan/20 text-neon-cyan" :
                            job.trigger_type === "post-sprint" ? "bg-electric-blue/20 text-electric-blue" :
                            "bg-racing-red/20 text-racing-red"
                          }`}>
                            {triggerTypeLabels[job.trigger_type]}
                          </span>
                          <StatusBadge status={job.status} color={statusColors[job.status]} />
                          {job.is_sprint_weekend && (
                            <span className="rounded bg-warning-yellow/20 px-2 py-0.5 text-xs text-warning-yellow">
                              Sprint Weekend
                            </span>
                          )}
                        </div>
                        
                        <h3 className="mt-2 font-medium text-white">
                          {job.race_name || job.description || "Scheduled Job"}
                        </h3>
                        
                        <p className="mt-1 text-sm text-white/60">
                          {formatDateTime(job.scheduled_for)} • {formatRelativeTime(job.scheduled_for)}
                        </p>
                        
                        {job.error_message && (
                          <p className="mt-2 text-sm text-racing-red">{job.error_message}</p>
                        )}
                      </div>
                      
                      <div className="flex gap-2">
                        {job.status === "scheduled" && (
                          <>
                            <Button variant="secondary" size="sm" onClick={() => handleTrigger(job.id)}>
                              Run Now
                            </Button>
                            <Button variant="ghost" size="sm" onClick={() => handleCancel(job.id)}>
                              Cancel
                            </Button>
                          </>
                        )}
                        {job.episode_id && (
                          <a href={`/episodes/${job.episode_id}`}>
                            <Button variant="secondary" size="sm">View Episode</Button>
                          </a>
                        )}
                      </div>
                    </div>
                  </Card>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* All Jobs Table */}
      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-semibold text-white">All Jobs</h2>
          
          <div className="flex gap-2">
            {(["all", "scheduled", "running", "completed", "failed"] as const).map((status) => (
              <button
                key={status}
                onClick={() => setFilter(status)}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                  filter === status
                    ? "bg-neon-cyan/20 text-neon-cyan"
                    : "text-white/60 hover:bg-white/5 hover:text-white"
                }`}
              >
                {status.charAt(0).toUpperCase() + status.slice(1)}
              </button>
            ))}
          </div>
        </div>

        <Card className="overflow-hidden">
          <table className="w-full">
            <thead className="border-b border-white/10 bg-white/5">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-white/60">Type</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-white/60">Race/Description</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-white/60">Scheduled</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-white/60">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-white/60">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {jobs.map((job) => (
                <tr key={job.id} className="hover:bg-white/5">
                  <td className="px-4 py-3">
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${
                      job.trigger_type === "weekly-recap" ? "bg-cyber-purple/20 text-cyber-purple" :
                      job.trigger_type === "post-fp2" ? "bg-neon-cyan/20 text-neon-cyan" :
                      job.trigger_type === "post-sprint" ? "bg-electric-blue/20 text-electric-blue" :
                      "bg-racing-red/20 text-racing-red"
                    }`}>
                      {triggerTypeLabels[job.trigger_type]}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-white">
                    {job.race_name || job.description || "-"}
                  </td>
                  <td className="px-4 py-3 text-sm text-white/60">
                    {formatDateTime(job.scheduled_for)}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={job.status} color={statusColors[job.status]} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2">
                      {job.status === "scheduled" && (
                        <button
                          onClick={() => handleTrigger(job.id)}
                          className="text-xs text-neon-cyan hover:underline"
                        >
                          Run
                        </button>
                      )}
                      {job.episode_id && (
                        <a href={`/episodes/${job.episode_id}`} className="text-xs text-electric-blue hover:underline">
                          Episode
                        </a>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          
          {jobs.length === 0 && (
            <div className="p-8 text-center text-white/60">
              No jobs found
            </div>
          )}
        </Card>
      </section>
    </div>
  );
}
