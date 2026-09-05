"use client";
import React, { useState } from "react";
import { motion } from "framer-motion";
import { Search, Zap, Shield, X, Globe } from "lucide-react";
import dynamic from "next/dynamic";

const ScannerGlobe = dynamic(() => import("@/components/three/ScannerGlobe"), {
  ssr: false,
  loading: () => <div className="w-full h-full" />,
});

interface ScannerHeaderProps {
  onStartScan: (url: string) => void;
  isScanning: boolean;
  onReset?: () => void;
}

export default function ScannerHeader({
  onStartScan,
  isScanning,
  onReset,
}: ScannerHeaderProps) {
  const [url, setUrl] = useState("");
  const [focused, setFocused] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim() || isScanning) return;
    let target = url.trim();
    if (!target.startsWith("http")) target = `https://${target}`;
    onStartScan(target);
  };

  return (
    <div className="relative overflow-hidden rounded-xl border border-slate-800 bg-[#0C1220]">
      {/* Scan line animation */}
      <div className="scan-line" />

      {/* Three.js Globe - background */}
      <div className="absolute right-0 top-0 w-80 h-full opacity-60 pointer-events-none">
        <ScannerGlobe />
      </div>

      {/* Grid overlay */}
      <div
        className="absolute inset-0 scanner-grid-bg opacity-50"
        aria-hidden="true"
      />

      {/* Content */}
      <div className="relative z-10 px-8 py-10">
        {/* Title row */}
        <div className="flex items-center gap-3 mb-6">
          <div className="flex items-center gap-2 px-2.5 py-1 rounded-md bg-blue-500/10 border border-blue-500/20">
            <Globe className="w-3 h-3 text-blue-400" />
            <span className="text-xs font-mono text-blue-400 tracking-widest">
              DEEP_SCAN_MODE
            </span>
          </div>
          <div className="flex items-center gap-2 px-2.5 py-1 rounded-md bg-slate-900 border border-slate-800">
            <Shield className="w-3 h-3 text-indigo-400" />
            <span className="text-xs font-mono text-slate-400">
              3 Agents Active
            </span>
          </div>
        </div>

        <h1 className="text-2xl font-semibold text-white mb-1 tracking-tight">
          Merchant Inspection Terminal
        </h1>
        <p className="text-sm text-slate-500 mb-8 max-w-xl">
          Submit a merchant URL for autonomous multi-agent risk analysis. Policy,
          catalog, and digital footprint agents operate in parallel.
        </p>

        {/* URL Input */}
        <form onSubmit={handleSubmit} className="flex gap-3 max-w-2xl">
          <div
            className={`relative flex-1 flex items-center rounded-lg border transition-all duration-200 ${
              focused
                ? "border-blue-500/60 bg-slate-900/80 shadow-brand-sm"
                : "border-slate-700 bg-slate-900/50"
            }`}
          >
            <Search className="w-4 h-4 text-slate-500 ml-3.5 flex-shrink-0" />
            <input
              id="merchant-url-input"
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              placeholder="https://merchant-store.com"
              className="flex-1 bg-transparent px-3 py-3 text-sm text-white placeholder:text-slate-600 outline-none font-mono"
              disabled={isScanning}
              autoComplete="off"
              spellCheck={false}
            />
            {url && (
              <button
                type="button"
                onClick={() => setUrl("")}
                className="mr-3 text-slate-600 hover:text-slate-400 transition-colors"
                aria-label="Clear input"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {isScanning ? (
            <button
              type="button"
              onClick={onReset}
              id="cancel-scan-btn"
              className="flex items-center gap-2 px-5 py-3 rounded-lg text-sm font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors"
            >
              <X className="w-4 h-4" />
              Cancel
            </button>
          ) : (
            <motion.button
              type="submit"
              id="start-scan-btn"
              disabled={!url.trim()}
              whileHover={{ scale: url.trim() ? 1.02 : 1 }}
              whileTap={{ scale: url.trim() ? 0.98 : 1 }}
              className={`relative flex items-center gap-2 px-6 py-3 rounded-lg text-sm font-semibold transition-all duration-200 overflow-hidden ${
                url.trim()
                  ? "bg-blue-600 hover:bg-blue-500 text-white shadow-brand-sm"
                  : "bg-slate-800 text-slate-600 cursor-not-allowed border border-slate-700"
              }`}
            >
              {/* Pulse border animation */}
              {url.trim() && (
                <motion.div
                  className="absolute inset-0 rounded-lg"
                  animate={{
                    boxShadow: [
                      "0 0 0 0 rgba(59,130,246,0)",
                      "0 0 0 4px rgba(59,130,246,0.15)",
                      "0 0 0 0 rgba(59,130,246,0)",
                    ],
                  }}
                  transition={{ duration: 2, repeat: Infinity }}
                />
              )}
              <Zap className="w-4 h-4 relative z-10" />
              <span className="relative z-10">Start Deep Scan</span>
            </motion.button>
          )}
        </form>

        {/* Sample domains */}
        <div className="flex items-center gap-2 mt-4">
          <span className="text-xs text-slate-600">Try:</span>
          {[
            "merchant-electronics.shop",
            "organicwellness.store",
            "fastpills-rx.net",
          ].map((demo) => (
            <button
              key={demo}
              onClick={() => setUrl(`https://${demo}`)}
              disabled={isScanning}
              className="text-xs font-mono text-slate-500 hover:text-blue-400 transition-colors disabled:opacity-40"
            >
              {demo}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
