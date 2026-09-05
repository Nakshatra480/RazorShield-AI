/**
 * hooks/useSystemHealth.ts
 * ──────────────────────────────────────────────────────────────────────
 * Polls GET /api/v1/readiness so the header reports the *actual* state of
 * the database, browser pool, and LLM provider.
 *
 * The previous build hardcoded "OpenRouter: Active / Neon DB: Connected",
 * which stayed green even when the backend was entirely offline.
 */
"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { getReadiness, type ReadinessReport } from "@/lib/api";

export type ComponentState = "ok" | "degraded" | "down" | "unknown";

export interface SystemHealth {
  backend: ComponentState;
  database: ComponentState;
  llm: ComponentState;
  browser: ComponentState;
  llmModel: string | null;
  llmDetail: string | null;
  checkedAt: Date | null;
}

const INITIAL: SystemHealth = {
  backend: "unknown",
  database: "unknown",
  llm: "unknown",
  browser: "unknown",
  llmModel: null,
  llmDetail: null,
  checkedAt: null,
};

const POLL_INTERVAL_MS = 30_000;

function toState(raw: string | undefined): ComponentState {
  if (raw === "ok") return "ok";
  if (raw === "degraded") return "degraded";
  if (raw === "down" || raw === "unavailable") return "down";
  return "unknown";
}

export function useSystemHealth(): { health: SystemHealth; refresh: () => void } {
  const [health, setHealth] = useState<SystemHealth>(INITIAL);
  const mountedRef = useRef(true);

  const check = useCallback(async () => {
    try {
      const report: ReadinessReport = await getReadiness();
      if (!mountedRef.current) return;
      setHealth({
        backend: "ok",
        database: toState(report.components?.database?.status),
        llm: toState(report.components?.llm?.status),
        browser: toState(report.components?.browser?.status),
        llmModel: report.components?.llm?.model ?? null,
        llmDetail: report.components?.llm?.detail ?? null,
        checkedAt: new Date(),
      });
    } catch {
      if (!mountedRef.current) return;
      // Backend unreachable — every downstream component is unknown, not "ok".
      setHealth({
        backend: "down",
        database: "unknown",
        llm: "unknown",
        browser: "unknown",
        llmModel: null,
        llmDetail: null,
        checkedAt: new Date(),
      });
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    check();
    const id = setInterval(check, POLL_INTERVAL_MS);
    return () => {
      mountedRef.current = false;
      clearInterval(id);
    };
  }, [check]);

  return { health, refresh: check };
}
