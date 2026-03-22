"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { getProgressUrl } from "@/lib/api";

interface OperationProgressModalProps {
  title: string;
  jobId: string;
  episodeId: number;
  onClose: () => void;
  onComplete?: () => void;
}

interface ProgressEvent {
  step: string;
  message: string;
  progress: number;
  total: number;
  status: string;
}

const STITCH_STEPS = ["downloading", "stitching", "uploading", "complete"];
const VALIDATE_STEPS = ["validating", "complete"];

function getSteps(title: string): string[] {
  if (title.toLowerCase().includes("validat")) return VALIDATE_STEPS;
  return STITCH_STEPS;
}

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}

export function OperationProgressModal({
  title,
  jobId,
  episodeId,
  onClose,
  onComplete,
}: OperationProgressModalProps) {
  const [currentEvent, setCurrentEvent] = useState<ProgressEvent | null>(null);
  const [status, setStatus] = useState<"running" | "success" | "error">("running");
  const [finalMessage, setFinalMessage] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const eventSourceRef = useRef<EventSource | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const steps = getSteps(title);

  // Elapsed timer
  useEffect(() => {
    timerRef.current = setInterval(() => {
      setElapsed((prev) => prev + 1);
    }, 1000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  // Stop timer when done
  useEffect(() => {
    if (status !== "running" && timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, [status]);

  // SSE connection
  useEffect(() => {
    const url = getProgressUrl(episodeId, jobId);
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const data: ProgressEvent = JSON.parse(event.data);
        setCurrentEvent(data);

        if (data.status === "finished" || data.step === "complete") {
          setStatus("success");
          setFinalMessage(data.message || "Operation completed successfully.");
          es.close();
          onComplete?.();
        } else if (data.status === "failed" || data.status === "stopped" || data.step === "error") {
          setStatus("error");
          setFinalMessage(data.message || "Operation failed.");
          es.close();
        }
      } catch {
        // Ignore parse errors from keep-alive pings
      }
    };

    es.onerror = () => {
      // EventSource will auto-reconnect on transient errors.
      // If the connection is fully closed server-side, readyState becomes CLOSED.
      if (es.readyState === EventSource.CLOSED) {
        if (status === "running") {
          setStatus("error");
          setFinalMessage("Connection to server lost.");
        }
      }
    };

    return () => {
      es.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [episodeId, jobId]);

  // Prevent body scroll
  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, []);

  // Close on Escape
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && status !== "running") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose, status]);

  const completedStepIndex = currentEvent
    ? steps.indexOf(currentEvent.step)
    : -1;

  const progressPercent =
    currentEvent && currentEvent.total > 0
      ? Math.round((currentEvent.progress / currentEvent.total) * 100)
      : 0;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-[60] bg-black/60 backdrop-blur-sm animate-fade-in"
        onClick={status !== "running" ? onClose : undefined}
      />

      {/* Modal card */}
      <div className="fixed inset-0 z-[70] flex items-start justify-center pointer-events-none">
        <div
          className="pointer-events-auto mt-[20vh] w-full max-w-lg rounded-2xl border border-slate-700 bg-midnight p-8 shadow-2xl animate-fade-in"
        >
          {status === "running" && (
            <RunningState
              title={title}
              message={currentEvent?.message || "Connecting..."}
              steps={steps}
              completedStepIndex={completedStepIndex}
              progressPercent={progressPercent}
              hasProgress={!!currentEvent && currentEvent.total > 0}
              elapsed={elapsed}
            />
          )}

          {status === "success" && (
            <ResultState
              variant="success"
              message={finalMessage}
              elapsed={elapsed}
              onClose={onClose}
            />
          )}

          {status === "error" && (
            <ResultState
              variant="error"
              message={finalMessage}
              elapsed={elapsed}
              onClose={onClose}
            />
          )}
        </div>
      </div>
    </>
  );
}

/* ---------- Running State ---------- */

function RunningState({
  title,
  message,
  steps,
  completedStepIndex,
  progressPercent,
  hasProgress,
  elapsed,
}: {
  title: string;
  message: string;
  steps: string[];
  completedStepIndex: number;
  progressPercent: number;
  hasProgress: boolean;
  elapsed: number;
}) {
  return (
    <div className="flex flex-col items-center gap-6 text-center">
      {/* Spinner */}
      <div className="relative h-14 w-14">
        <div className="absolute inset-0 animate-spin rounded-full border-2 border-transparent border-t-neon-cyan h-14 w-14" />
        <div className="absolute inset-1 rounded-full border-2 border-transparent border-b-electric-blue animate-[spin_1.5s_linear_infinite_reverse]" />
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="h-2 w-2 animate-pulse rounded-full bg-neon-cyan" />
        </div>
      </div>

      {/* Title */}
      <h2 className="text-xl font-semibold text-white">{title}</h2>

      {/* Current step message */}
      <p className="text-lg text-white/80">{message}</p>

      {/* Progress bar */}
      {hasProgress && (
        <div className="w-full">
          <div className="mb-1 flex justify-between text-xs text-white/50">
            <span>{progressPercent}%</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-700">
            <div
              className="h-full rounded-full bg-gradient-to-r from-neon-cyan to-electric-blue transition-all duration-300"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>
      )}

      {/* Step indicators */}
      <div className="flex items-center gap-2">
        {steps.filter((s) => s !== "complete").map((step, i) => (
          <div key={step} className="flex items-center gap-2">
            <div
              className={`h-2.5 w-2.5 rounded-full transition-colors ${
                i < completedStepIndex
                  ? "bg-emerald-400"
                  : i === completedStepIndex
                    ? "bg-neon-cyan animate-pulse"
                    : "bg-slate-600"
              }`}
              title={step}
            />
            {i < steps.filter((s) => s !== "complete").length - 1 && (
              <div
                className={`h-px w-4 ${
                  i < completedStepIndex ? "bg-emerald-400/50" : "bg-slate-600"
                }`}
              />
            )}
          </div>
        ))}
      </div>

      {/* Elapsed */}
      <p className="text-sm text-white/40">{formatElapsed(elapsed)} elapsed</p>
    </div>
  );
}

/* ---------- Result State (success / error) ---------- */

function ResultState({
  variant,
  message,
  elapsed,
  onClose,
}: {
  variant: "success" | "error";
  message: string;
  elapsed: number;
  onClose: () => void;
}) {
  const isSuccess = variant === "success";

  return (
    <div className="flex flex-col items-center gap-5 text-center">
      {/* Icon */}
      <div
        className={`flex h-16 w-16 items-center justify-center rounded-full ${
          isSuccess ? "bg-emerald-400/10" : "bg-red-400/10"
        }`}
      >
        {isSuccess ? (
          <svg className="h-8 w-8 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        ) : (
          <svg className="h-8 w-8 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        )}
      </div>

      {/* Title */}
      <h2 className={`text-xl font-semibold ${isSuccess ? "text-emerald-400" : "text-red-400"}`}>
        {isSuccess ? "Complete" : "Failed"}
      </h2>

      {/* Message */}
      <p className="text-white/70">{message}</p>

      {/* Elapsed */}
      <p className="text-sm text-white/40">Finished in {formatElapsed(elapsed)}</p>

      {/* Close button */}
      <button
        onClick={onClose}
        className={`mt-2 rounded-lg px-6 py-2.5 font-medium transition-colors ${
          isSuccess
            ? "bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30"
            : "bg-red-500/20 text-red-400 hover:bg-red-500/30"
        }`}
      >
        Close
      </button>
    </div>
  );
}
