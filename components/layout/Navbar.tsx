"use client";
import React, { useState } from "react";
import { motion } from "framer-motion";
import { Shield, Zap, Database, Activity } from "lucide-react";

type Tab = "scanner" | "feed" | "benchmark";

interface NavbarProps {
  activeTab: Tab;
  onTabChange: (tab: Tab) => void;
}

const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  {
    id: "scanner",
    label: "Merchant Scanner",
    icon: <Shield className="w-3.5 h-3.5" />,
  },
  {
    id: "feed",
    label: "Risk Operations Feed",
    icon: <Activity className="w-3.5 h-3.5" />,
  },
  {
    id: "benchmark",
    label: "Benchmark & Metrics",
    icon: <Database className="w-3.5 h-3.5" />,
  },
];

export default function Navbar({ activeTab, onTabChange }: NavbarProps) {
  const [hoveredTab, setHoveredTab] = useState<Tab | null>(null);

  return (
    <header className="fixed top-0 left-0 right-0 z-50 h-14 glass-surface border-b border-slate-800">
      <div className="max-w-screen-2xl mx-auto h-full px-6 flex items-center justify-between">
        {/* Logo */}
        <div className="flex items-center gap-3 flex-shrink-0">
          <div className="relative w-8 h-8 flex items-center justify-center">
            <svg viewBox="0 0 32 32" className="w-8 h-8" fill="none">
              <path
                d="M16 2L4 8v8c0 7 5.3 13.1 12 14.9C22.7 29.1 28 23 28 16V8L16 2z"
                fill="url(#shieldGrad)"
                stroke="#6366F1"
                strokeWidth="0.5"
              />
              <path
                d="M16 2L4 8v8c0 7 5.3 13.1 12 14.9C22.7 29.1 28 23 28 16V8L16 2z"
                fill="none"
                stroke="#3B82F6"
                strokeWidth="1"
                strokeDasharray="2 1"
                opacity="0.6"
              />
              {/* Circuit lines */}
              <line x1="16" y1="11" x2="16" y2="21" stroke="#60A5FA" strokeWidth="1.2" strokeLinecap="round" />
              <line x1="11" y1="16" x2="21" y2="16" stroke="#60A5FA" strokeWidth="1.2" strokeLinecap="round" />
              <circle cx="16" cy="16" r="2" fill="#3B82F6" />
              <circle cx="16" cy="11" r="1" fill="#6366F1" />
              <circle cx="16" cy="21" r="1" fill="#6366F1" />
              <circle cx="11" cy="16" r="1" fill="#6366F1" />
              <circle cx="21" cy="16" r="1" fill="#6366F1" />
              <defs>
                <linearGradient id="shieldGrad" x1="16" y1="2" x2="16" y2="30" gradientUnits="userSpaceOnUse">
                  <stop offset="0%" stopColor="#1e1b4b" />
                  <stop offset="100%" stopColor="#0f172a" />
                </linearGradient>
              </defs>
            </svg>
          </div>
          <div>
            <span className="text-sm font-semibold text-white tracking-tight">
              RazorShield
            </span>
            <span className="text-sm font-light text-blue-400 ml-1 tracking-tight">
              AI
            </span>
          </div>
          <div className="hidden md:block w-px h-4 bg-slate-700 ml-1" />
          <span className="hidden md:block text-xs text-slate-500 font-mono tracking-wide">
            v2.4.1
          </span>
        </div>

        {/* Nav Tabs */}
        <nav className="flex items-center gap-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              id={`nav-tab-${tab.id}`}
              onClick={() => onTabChange(tab.id)}
              onMouseEnter={() => setHoveredTab(tab.id)}
              onMouseLeave={() => setHoveredTab(null)}
              className={`relative flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors duration-150 ${
                activeTab === tab.id
                  ? "text-white"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {activeTab === tab.id && (
                <motion.div
                  layoutId="navActive"
                  className="absolute inset-0 bg-slate-800 rounded-md border border-slate-700"
                  transition={{ type: "spring", duration: 0.3, bounce: 0.2 }}
                />
              )}
              {hoveredTab === tab.id && activeTab !== tab.id && (
                <motion.div
                  layoutId="navHover"
                  className="absolute inset-0 bg-slate-800/50 rounded-md"
                  transition={{ duration: 0.15 }}
                />
              )}
              <span className="relative z-10 flex items-center gap-1.5">
                {tab.icon}
                {tab.label}
              </span>
            </button>
          ))}
        </nav>

        {/* System Status */}
        <div className="flex items-center gap-4">
          <div className="hidden lg:flex items-center gap-2 px-3 py-1.5 rounded-md bg-slate-900 border border-slate-800">
            <div className="flex items-center gap-1.5">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500" />
              </span>
              <span className="text-xs text-slate-400 font-mono">
                OpenRouter API:{" "}
                <span className="text-emerald-400">Active</span>
              </span>
            </div>
            <span className="text-slate-700">•</span>
            <div className="flex items-center gap-1.5">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-blue-500" />
              </span>
              <span className="text-xs text-slate-400 font-mono">
                Neon DB: <span className="text-blue-400">Connected</span>
              </span>
            </div>
          </div>
          <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-slate-900 border border-slate-800">
            <Zap className="w-3 h-3 text-yellow-400" />
            <span className="text-xs font-mono text-slate-400">
              <span className="text-yellow-400">GPT-4o</span>
            </span>
          </div>
        </div>
      </div>
    </header>
  );
}
