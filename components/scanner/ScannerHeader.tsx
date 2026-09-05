"use client";
import React, { useState } from "react";
import { ArrowRight, Loader2, Search, X } from "lucide-react";

interface ScannerHeaderProps {
  onStartScan: (url: string) => void;
  isScanning: boolean;
  onReset?: () => void;
}

/**
 * Real, publicly reachable sites so the demo actually completes a scan.
 * The previous list ("fastpills-rx.net", "merchant-electronics.shop") pointed at
 * domains that do not resolve, so every sample click ended in a scrape error.
 */
const SAMPLE_DOMAINS = ["stripe.com", "razorpay.com", "example.com"];

export default function ScannerHeader({
  onStartScan,
  isScanning,
  onReset,
}: ScannerHeaderProps) {
  const [url, setUrl] = useState("");
  const [touched, setTouched] = useState(false);

  const trimmed = url.trim();
  // Accept a bare hostname; require at least one dot and no spaces.
  const looksValid = /^([a-z]+:\/\/)?[^\s/]+\.[^\s/]{2,}/i.test(trimmed);
  const showError = touched && trimmed.length > 0 && !looksValid;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!looksValid || isScanning) return;
    const target = trimmed.startsWith("http") ? trimmed : `https://${trimmed}`;
    onStartScan(target);
  };

  return (
    <section className="rounded-xl border border-line bg-surface shadow-card overflow-hidden">
      <div className="px-6 py-7 sm:px-8 sm:py-9">
        <h1 className="text-[26px] leading-tight font-semibold tracking-tight text-ink">
          Merchant risk inspection
        </h1>
        <p className="mt-2 text-[14px] leading-relaxed text-ink-2 max-w-2xl">
          Enter a merchant URL to run a full underwriting check. Three agents
          inspect policy compliance, product catalogue, and domain footprint in
          parallel, then return a single weighted risk verdict.
        </p>

        <form onSubmit={handleSubmit} className="mt-6 max-w-2xl">
          <div className="flex flex-col sm:flex-row gap-2.5">
            <div
              className={`relative flex-1 flex items-center rounded-lg border bg-surface transition-shadow ${
                showError
                  ? "border-risk-danger"
                  : "border-line-strong focus-within:border-brand focus-within:shadow-focus"
              }`}
            >
              <Search className="w-4 h-4 text-ink-4 ml-3.5 flex-shrink-0" aria-hidden />
              <input
                id="merchant-url-input"
                type="text"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onBlur={() => setTouched(true)}
                placeholder="merchant-store.com"
                aria-label="Merchant URL"
                aria-invalid={showError}
                aria-describedby={showError ? "url-error" : undefined}
                className="flex-1 bg-transparent px-3 py-3 text-[14px] text-ink placeholder:text-ink-4 outline-none min-w-0"
                disabled={isScanning}
                autoComplete="off"
                spellCheck={false}
              />
              {url && !isScanning && (
                <button
                  type="button"
                  onClick={() => {
                    setUrl("");
                    setTouched(false);
                  }}
                  className="mr-3 p-0.5 rounded text-ink-4 hover:text-ink-2 transition-colors"
                  aria-label="Clear input"
                >
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>

            {isScanning ? (
              <button
                type="button"
                onClick={onReset}
                id="cancel-scan-btn"
                className="flex items-center justify-center gap-2 px-5 py-3 rounded-lg text-[14px] font-medium text-ink-2 bg-surface-muted border border-line-strong hover:bg-surface-sunken transition-colors"
              >
                <Loader2 className="w-4 h-4 animate-spin" aria-hidden />
                Cancel
              </button>
            ) : (
              <button
                type="submit"
                id="start-scan-btn"
                disabled={!trimmed}
                // Disabled state is a light, clearly-inactive surface. A solid
                // mid-tone fill reads as an available primary action.
                className="flex items-center justify-center gap-2 px-6 py-3 rounded-lg text-[14px] font-semibold transition-colors text-white bg-brand hover:bg-brand-hover active:bg-brand-press disabled:bg-surface-muted disabled:text-ink-4 disabled:border disabled:border-line disabled:cursor-not-allowed"
              >
                Run inspection
                <ArrowRight className="w-4 h-4" aria-hidden />
              </button>
            )}
          </div>

          {showError && (
            <p id="url-error" role="alert" className="mt-2 text-xs text-risk-danger">
              Enter a valid domain, for example <span className="font-mono">merchant-store.com</span>
            </p>
          )}
        </form>

        <div className="flex items-center gap-2 mt-4 flex-wrap">
          <span className="text-xs text-ink-3">Try:</span>
          {SAMPLE_DOMAINS.map((domain) => (
            <button
              key={domain}
              type="button"
              onClick={() => {
                setUrl(domain);
                setTouched(false);
              }}
              disabled={isScanning}
              className="text-xs font-mono px-2 py-1 rounded-md border border-line text-ink-2 hover:border-brand-border hover:bg-brand-soft hover:text-brand-ink transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {domain}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
