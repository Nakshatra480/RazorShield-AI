"use client";
import { useState, useCallback, useRef } from "react";
import { MOCK_SCAN_RESULT, type ScanResult, type AgentStatus } from "@/lib/mockData";

export interface ScanState {
  phase: "idle" | "scanning" | "complete" | "error";
  url: string;
  agentStatuses: Record<string, AgentStatus>;
  agentDurations: Record<string, number>;
  result: ScanResult | null;
  progress: number; // 0-100
  currentAgentIndex: number;
}

const INITIAL_STATE: ScanState = {
  phase: "idle",
  url: "",
  agentStatuses: {
    policy: "idle",
    catalog: "idle",
    footprint: "idle",
  },
  agentDurations: {
    policy: 0,
    catalog: 0,
    footprint: 0,
  },
  result: null,
  progress: 0,
  currentAgentIndex: -1,
};

const AGENT_SEQUENCE = ["policy", "catalog", "footprint"] as const;
const AGENT_DELAYS = { policy: 2800, catalog: 3100, footprint: 2300 };

export function useScanSimulation() {
  const [state, setState] = useState<ScanState>(INITIAL_STATE);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const startTimeRef = useRef<number>(0);
  const tickRef = useRef<NodeJS.Timeout | null>(null);

  const clearTimers = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (tickRef.current) clearInterval(tickRef.current);
  };

  const startScan = useCallback((url: string) => {
    clearTimers();
    startTimeRef.current = Date.now();

    setState({
      ...INITIAL_STATE,
      phase: "scanning",
      url,
      agentStatuses: { policy: "idle", catalog: "idle", footprint: "idle" },
      progress: 0,
      currentAgentIndex: 0,
    });

    let cumulativeDelay = 0;
    const agentOrder = AGENT_SEQUENCE;

    // Start each agent sequentially with cumulative delays
    agentOrder.forEach((agentId, idx) => {
      const startDelay = cumulativeDelay + 200;
      const endDelay = cumulativeDelay + AGENT_DELAYS[agentId];
      cumulativeDelay += AGENT_DELAYS[agentId] + 400;

      // Mark running
      setTimeout(() => {
        setState((prev) => ({
          ...prev,
          agentStatuses: { ...prev.agentStatuses, [agentId]: "running" },
          currentAgentIndex: idx,
          progress: Math.round(((idx) / agentOrder.length) * 90),
        }));
      }, startDelay);

      // Mark complete
      setTimeout(() => {
        setState((prev) => ({
          ...prev,
          agentStatuses: { ...prev.agentStatuses, [agentId]: "complete" },
          agentDurations: {
            ...prev.agentDurations,
            [agentId]: AGENT_DELAYS[agentId],
          },
          progress: Math.round(((idx + 1) / agentOrder.length) * 90),
        }));
      }, endDelay);
    });

    // Final completion
    const totalDelay = cumulativeDelay + 600;
    setTimeout(() => {
      setState((prev) => ({
        ...prev,
        phase: "complete",
        result: MOCK_SCAN_RESULT,
        progress: 100,
        currentAgentIndex: -1,
      }));
    }, totalDelay);
  }, []);

  const reset = useCallback(() => {
    clearTimers();
    setState(INITIAL_STATE);
  }, []);

  return { state, startScan, reset };
}
