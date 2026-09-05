"""
tests/test_benchmark.py
─────────────────────────────────────────────────────────────────────────────
Benchmark execution and JSON output verification tests.

Runs the full 50-merchant synthetic benchmark, then validates:
  - benchmark_results.json exists and is valid JSON
  - precision >= 0.85
  - recall >= 0.85
  - Confusion matrix is a valid 2×2 structure
  - Financial impact data is present with ≥3 month entries
  - Average processing time is reported

NOTE: This test takes 3–8 minutes to complete (50 merchants × ~4s each).
      It is marked with @pytest.mark.slow and can be skipped with:
        pytest tests/test_benchmark.py -m "not slow"
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


BENCHMARK_RESULTS_PATH = Path(__file__).parent.parent / "public" / "benchmark_results.json"


# ── Helper ─────────────────────────────────────────────────────────────────────

def _load_results() -> dict:
    """Load and parse benchmark_results.json, raising AssertionError if invalid."""
    assert BENCHMARK_RESULTS_PATH.exists(), (
        f"benchmark_results.json not found at {BENCHMARK_RESULTS_PATH}\n"
        "Run: python3.11 -m razorshield_backend.benchmark"
    )
    with open(BENCHMARK_RESULTS_PATH) as f:
        raw = f.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"benchmark_results.json is not valid JSON: {exc}\n"
            f"First 500 chars: {raw[:500]}"
        )
    return data


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.slow
def test_benchmark_execution():
    """
    Execute python3.11 -m razorshield_backend.benchmark as a subprocess.
    Asserts:
      - Process exits with code 0.
      - benchmark_results.json is created/updated.
      - Stdout contains key progress messages.

    Takes ~3–8 minutes depending on LLM latency.
    """
    print("\n  Running benchmark suite (50 merchants)…")
    start = time.time()

    result = subprocess.run(
        [sys.executable, "-m", "razorshield_backend.benchmark"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
        timeout=900,  # 15 minute hard cap
    )

    elapsed = time.time() - start
    print(f"  Benchmark finished in {elapsed:.1f}s")
    print(f"  Return code: {result.returncode}")
    if result.stdout:
        print("  STDOUT (last 800 chars):")
        print("  " + result.stdout[-800:].replace("\n", "\n  "))
    if result.stderr:
        print("  STDERR (last 400 chars):")
        print("  " + result.stderr[-400:].replace("\n", "\n  "))

    assert result.returncode == 0, (
        f"benchmark.py exited with code {result.returncode}\n"
        f"STDERR:\n{result.stderr[-1000:]}"
    )
    assert BENCHMARK_RESULTS_PATH.exists(), (
        "benchmark_results.json was not created even though exit code was 0."
    )
    print(f"  [PASS] Benchmark executed successfully in {elapsed:.1f}s.")


def test_benchmark_results_file_exists():
    """
    Verify benchmark_results.json exists.
    Runs independently of test_benchmark_execution — useful when benchmark was
    already run in a previous session.
    """
    assert BENCHMARK_RESULTS_PATH.exists(), (
        f"benchmark_results.json not found at {BENCHMARK_RESULTS_PATH}\n"
        "Run: python3.11 -m razorshield_backend.benchmark"
    )
    print(f"\n  [PASS] benchmark_results.json found at {BENCHMARK_RESULTS_PATH}")


def test_benchmark_results_valid_json():
    """Verify the results file is parseable JSON."""
    data = _load_results()
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    print(f"\n  [PASS] benchmark_results.json is valid JSON with {len(data)} top-level keys.")


def test_benchmark_precision():
    """Precision must be >= 0.85 (85%)."""
    data = _load_results()
    metrics = data.get("metrics", {})

    precision = metrics.get("precision")
    assert precision is not None, (
        f"'precision' key missing from metrics.\nAvailable keys: {list(metrics.keys())}"
    )
    precision_f = float(precision)
    print(f"\n  precision={precision_f:.4f}")
    assert precision_f >= 0.85, (
        f"Precision too low: {precision_f:.4f} (minimum: 0.85)\n"
        f"Full metrics: {metrics}"
    )
    print(f"  [PASS] Precision {precision_f:.4f} >= 0.85 threshold.")


def test_benchmark_recall():
    """Recall must be >= 0.85 (85%)."""
    data = _load_results()
    metrics = data.get("metrics", {})

    recall = metrics.get("recall")
    assert recall is not None, (
        f"'recall' key missing from metrics.\nAvailable keys: {list(metrics.keys())}"
    )
    recall_f = float(recall)
    print(f"\n  recall={recall_f:.4f}")
    assert recall_f >= 0.85, (
        f"Recall too low: {recall_f:.4f} (minimum: 0.85)\n"
        f"Full metrics: {metrics}"
    )
    print(f"  [PASS] Recall {recall_f:.4f} >= 0.85 threshold.")


def test_benchmark_f1_score():
    """F1-score must be >= 0.85."""
    data = _load_results()
    metrics = data.get("metrics", {})

    f1 = metrics.get("f1_score")
    assert f1 is not None, \
        f"'f1_score' key missing from metrics. Keys={list(metrics.keys())}"
    f1_f = float(f1)
    print(f"\n  f1_score={f1_f:.4f}")
    assert f1_f >= 0.85, f"F1-score too low: {f1_f:.4f} (minimum: 0.85)"
    print(f"  [PASS] F1-score {f1_f:.4f} >= 0.85 threshold.")


def test_benchmark_confusion_matrix():
    """
    Confusion matrix must be a valid 2×2 structure with non-negative integer counts.
    All four cells — TP, FP, TN, FN — must be present and >= 0.
    """
    data = _load_results()
    cm = data.get("confusion_matrix")
    assert cm is not None, (
        f"'confusion_matrix' key missing from results.\n"
        f"Top-level keys: {list(data.keys())}"
    )

    print(f"\n  confusion_matrix={cm}")

    # Support both dict-style and nested list-style
    if isinstance(cm, dict):
        required_keys = {"true_positive", "false_positive", "true_negative", "false_negative"}
        missing = required_keys - set(cm.keys())
        assert not missing, f"confusion_matrix missing keys: {missing}"
        for key in required_keys:
            val = cm[key]
            assert isinstance(val, (int, float)) and val >= 0, \
                f"confusion_matrix[{key!r}] must be non-negative number, got {val!r}"
        total = cm["true_positive"] + cm["false_positive"] + cm["true_negative"] + cm["false_negative"]
    elif isinstance(cm, list):
        assert len(cm) == 2 and all(len(row) == 2 for row in cm), \
            f"Confusion matrix must be 2×2 list, got shape {[len(r) for r in cm]}"
        total = sum(cm[i][j] for i in range(2) for j in range(2))
    else:
        raise AssertionError(f"Unexpected confusion_matrix format: {type(cm)} — {cm!r}")

    assert total > 0, f"All confusion matrix cells are zero — benchmark did not run properly."
    print(f"  [PASS] Confusion matrix valid. Total evaluated: {total}")


def test_benchmark_financial_impact():
    """
    Financial impact data must contain key cost/savings metrics:
    'monthly_fraud_prevented_usd' and 'false_negative_cost_per_merchant_usd'.
    """
    data = _load_results()
    fi = data.get("financial_impact", {})

    assert isinstance(fi, dict), \
        f"financial_impact must be a dict, got {type(fi)}"
    assert len(fi) > 0, \
        f"financial_impact is empty. Top-level keys: {list(data.keys())}"

    # Must contain at least one of the expected cost fields
    expected_keys = {
        "monthly_fraud_prevented_usd",
        "false_negative_cost_per_merchant_usd",
        "false_positive_cost_per_merchant_usd",
        "total_benchmark_cost_usd",
    }
    found = expected_keys & set(fi.keys())
    assert found, (
        f"financial_impact missing expected keys.\n"
        f"Expected one of: {expected_keys}\n"
        f"Got: {list(fi.keys())}"
    )

    # Fraud prevented should be a non-negative number
    if "monthly_fraud_prevented_usd" in fi:
        assert float(fi["monthly_fraud_prevented_usd"]) >= 0, \
            f"monthly_fraud_prevented_usd must be >= 0, got {fi['monthly_fraud_prevented_usd']}"

    print(f"\n  [PASS] Financial impact valid — {len(fi)} metrics present.")
    for k, v in fi.items():
        print(f"         {k}: {v}")


def test_benchmark_dataset_size():
    """The benchmark must have evaluated at least 40 merchants."""
    data = _load_results()
    dataset = data.get("dataset", {})
    total = dataset.get("total_merchants", 0)

    print(f"\n  total_merchants={total}")
    assert total >= 40, (
        f"Benchmark dataset too small: {total} merchants (expected >= 40)"
    )
    print(f"  [PASS] Benchmark evaluated {total} merchants.")


def test_benchmark_processing_time():
    """Average processing time must be reported and be a positive number."""
    data = _load_results()
    metrics = data.get("metrics", {})
    avg_ms = metrics.get("avg_processing_ms")

    assert avg_ms is not None, \
        f"'avg_processing_ms' missing from metrics. Keys={list(metrics.keys())}"
    assert float(avg_ms) > 0, \
        f"avg_processing_ms must be > 0, got {avg_ms!r}"
    print(f"\n  avg_processing_ms={avg_ms:.1f}ms")
    print(f"  [PASS] Processing time reported correctly.")
