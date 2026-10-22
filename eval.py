"""Automated Evaluation and Benchmarking Suite for Tiny Shell Intent."""

import gc
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple
import numpy as np
import psutil

from tiny_shell_intent import IntentEngine, KnowledgeBaseStore
from tiny_shell_intent.schema import Candidate, QueryResult


def get_dir_size(path: Path) -> Tuple[int, Dict[str, int]]:
    """Compute total directory size and individual file sizes in bytes."""
    total = 0
    breakdown = {}
    if not path.exists():
        return 0, {}
    for p in path.rglob("*"):
        if p.is_file():
            size = p.stat().st_size
            total += size
            breakdown[p.name] = size
    return total, breakdown


def benchmark_resource_consumption(
    model_path: str = "./models/potion-base-2M",
    kb_path: str = "data/knowledge_base.json",
) -> Dict[str, Any]:
    """Measure model disk footprint, memory increment, and load times."""
    process = psutil.Process(os.getpid())

    # 1. Model disk size
    m_path = Path(model_path)
    total_bytes, file_breakdown = get_dir_size(m_path)
    model_mb = total_bytes / (1024 * 1024)

    # 2. Memory baseline
    gc.collect()
    rss_before = process.memory_info().rss / (1024 * 1024)

    # 3. Startup & indexing time
    t0 = time.perf_counter()
    engine = IntentEngine(kb_path=kb_path, model_path=model_path, offline_mode=True)
    load_time_ms = (time.perf_counter() - t0) * 1000

    # 4. Memory after model loading
    rss_after = process.memory_info().rss / (1024 * 1024)
    rss_delta = max(0.0, rss_after - rss_before)

    return {
        "model_path": str(m_path),
        "disk_size_bytes": total_bytes,
        "disk_size_mb": round(model_mb, 2),
        "file_breakdown": {k: f"{v / (1024 * 1024):.2f} MB" for k, v in file_breakdown.items()},
        "load_time_ms": round(load_time_ms, 2),
        "memory_rss_before_mb": round(rss_before, 2),
        "memory_rss_after_mb": round(rss_after, 2),
        "memory_rss_delta_mb": round(rss_delta, 2),
        "engine": engine,
    }


def evaluate_retrieval_accuracy(
    engine: IntentEngine,
    test_queries: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Evaluate Top-1 and Top-3 accuracy across Rule, Fuzzy, Model, and Hybrid modes."""
    modes = ["rule", "fuzzy", "model", "hybrid"]
    labeled_queries = [t for t in test_queries if t.get("expected_intent_id") is not None]
    total = len(labeled_queries)

    results_by_mode: Dict[str, Dict[str, Any]] = {}

    for mode in modes:
        top1_hits = 0
        top3_hits = 0
        per_type_stats: Dict[str, Dict[str, int]] = {}
        confusion_pairs: List[Tuple[str, str, str]] = []  # (query, expected, got)
        failures: List[Dict[str, Any]] = []

        for item in labeled_queries:
            q = item["query"]
            expected = item["expected_intent_id"]
            q_type = item.get("type", "unknown")

            if q_type not in per_type_stats:
                per_type_stats[q_type] = {"total": 0, "top1": 0, "top3": 0}
            per_type_stats[q_type]["total"] += 1

            res = engine.search(q, top_k=3, mode=mode)
            cands = [c.intent_id for c in res.candidates]

            hit1 = False
            hit3 = False

            if cands and cands[0] == expected:
                top1_hits += 1
                hit1 = True
                per_type_stats[q_type]["top1"] += 1

            if expected in cands[:3]:
                top3_hits += 1
                hit3 = True
                per_type_stats[q_type]["top3"] += 1

            if not hit1:
                got = cands[0] if cands else "None"
                confusion_pairs.append((q, expected, got))
                failures.append({
                    "query": q,
                    "type": q_type,
                    "expected": expected,
                    "got_top1": got,
                    "candidates": [c.to_dict() for c in res.candidates],
                    "in_top3": hit3,
                })

        # Calculate percentages
        type_summary = {}
        for q_type, counts in per_type_stats.items():
            cnt = counts["total"]
            type_summary[q_type] = {
                "total": cnt,
                "top1_acc": round(counts["top1"] / cnt * 100, 1) if cnt else 0.0,
                "top3_acc": round(counts["top3"] / cnt * 100, 1) if cnt else 0.0,
            }

        results_by_mode[mode] = {
            "total_queries": total,
            "top1_hits": top1_hits,
            "top1_acc": round(top1_hits / total * 100, 1),
            "top3_hits": top3_hits,
            "top3_acc": round(top3_hits / total * 100, 1),
            "breakdown_by_type": type_summary,
            "confusion_pairs": confusion_pairs,
            "failures": failures,
        }

    return results_by_mode


def benchmark_latency(
    engine: IntentEngine,
    queries: List[str],
    iterations: int = 5,
) -> Dict[str, Dict[str, float]]:
    """Measure P50, P90, P95, P99, and Mean search latencies for each mode."""
    modes = ["rule", "fuzzy", "model", "hybrid"]
    latency_report = {}

    # Warmup
    for q in queries[:10]:
        for mode in modes:
            _ = engine.search(q, top_k=3, mode=mode)

    for mode in modes:
        latencies = []
        for _ in range(iterations):
            for q in queries:
                t0 = time.perf_counter()
                _ = engine.search(q, top_k=3, mode=mode)
                elapsed_ms = (time.perf_counter() - t0) * 1000
                latencies.append(elapsed_ms)

        latencies_arr = np.array(latencies)
        latency_report[mode] = {
            "mean_ms": round(float(np.mean(latencies_arr)), 3),
            "p50_ms": round(float(np.percentile(latencies_arr, 50)), 3),
            "p90_ms": round(float(np.percentile(latencies_arr, 90)), 3),
            "p95_ms": round(float(np.percentile(latencies_arr, 95)), 3),
            "p99_ms": round(float(np.percentile(latencies_arr, 99)), 3),
            "min_ms": round(float(np.min(latencies_arr)), 3),
            "max_ms": round(float(np.max(latencies_arr)), 3),
        }

    return latency_report


def evaluate_special_cases(
    engine: IntentEngine,
    test_queries: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Specialized evaluation for short commands, out-of-domain queries, and empty inputs."""
    special_types = ["abbreviation", "out_of_domain", "edge_case"]
    special_results = {}

    for st in special_types:
        subset = [t for t in test_queries if t.get("type") == st]
        records = []
        for item in subset:
            q = item["query"]
            res = engine.search(q, top_k=3, mode="hybrid")
            records.append({
                "query": q,
                "expected": item.get("expected_intent_id"),
                "is_empty": res.is_empty,
                "is_out_of_domain": res.is_out_of_domain,
                "top_candidate": res.top_candidate.to_dict() if res.top_candidate else None,
            })
        special_results[st] = records

    return special_results


def print_evaluation_summary(
    resource_info: Dict[str, Any],
    accuracy_info: Dict[str, Any],
    latency_info: Dict[str, Any],
    special_info: Dict[str, Any],
) -> None:
    """Print beautifully formatted evaluation report to stdout."""
    print("\n" + "=" * 76)
    print("        TINY SHELL INTENT — PHASE 1 EMPIRICAL BENCHMARK REPORT")
    print("=" * 76)

    # 1. Resource Consumption
    print("\n[1] RESOURCE FOOTPRINT & STARTUP")
    print("-" * 76)
    print(f"  Model Weight Path:        {resource_info['model_path']}")
    print(f"  Total Model Disk Size:    {resource_info['disk_size_mb']} MB ({resource_info['disk_size_bytes']:,} bytes)")
    for fname, fsize in resource_info["file_breakdown"].items():
        print(f"    - {fname:24} {fsize}")
    print(f"  Cold Load & Index Time:   {resource_info['load_time_ms']} ms")
    print(f"  Baseline Process RSS:     {resource_info['memory_rss_before_mb']} MB")
    print(f"  Loaded Process RSS:       {resource_info['memory_rss_after_mb']} MB")
    print(f"  Incremental Memory (RSS): {resource_info['memory_rss_delta_mb']} MB")

    # 2. Accuracy Comparison
    print("\n[2] RETRIEVAL ACCURACY BY SEARCH MODE")
    print("-" * 76)
    total_q = accuracy_info["hybrid"]["total_queries"]
    print(f"{'Mode':<10} | {'Top-1 Hits':<12} | {'Top-1 Acc':<11} | {'Top-3 Hits':<12} | {'Top-3 Acc':<11}")
    print("-" * 76)
    for mode in ["rule", "fuzzy", "model", "hybrid"]:
        st = accuracy_info[mode]
        print(
            f"{mode.upper():<10} | "
            f"{st['top1_hits']:>3}/{total_q:<7} | "
            f"{st['top1_acc']:>5.1f}%     | "
            f"{st['top3_hits']:>3}/{total_q:<7} | "
            f"{st['top3_acc']:>5.1f}%"
        )

    # 3. Accuracy Breakdown by Query Type (Hybrid Mode)
    print("\n[3] HYBRID MODE BREAKDOWN BY QUERY CATEGORY")
    print("-" * 76)
    print(f"{'Query Type':<20} | {'Count':<7} | {'Top-1 Acc':<12} | {'Top-3 Acc':<12}")
    print("-" * 76)
    hybrid_types = accuracy_info["hybrid"]["breakdown_by_type"]
    for q_type, stats in hybrid_types.items():
        print(
            f"{q_type:<20} | "
            f"{stats['total']:<7} | "
            f"{stats['top1_acc']:>5.1f}%      | "
            f"{stats['top3_acc']:>5.1f}%"
        )

    # 4. Latency Distribution
    print("\n[4] RETRIEVAL LATENCY BENCHMARK (ms)")
    print("-" * 76)
    print(f"{'Mode':<10} | {'Mean':<8} | {'P50':<8} | {'P90':<8} | {'P95':<8} | {'P99':<8}")
    print("-" * 76)
    for mode in ["rule", "fuzzy", "model", "hybrid"]:
        lat = latency_info[mode]
        print(
            f"{mode.upper():<10} | "
            f"{lat['mean_ms']:<8.3f} | "
            f"{lat['p50_ms']:<8.3f} | "
            f"{lat['p90_ms']:<8.3f} | "
            f"{lat['p95_ms']:<8.3f} | "
            f"{lat['p99_ms']:<8.3f}"
        )

    # 5. Confusion & Failure Analysis
    print("\n[5] CONFUSION & FAILURE ANALYSIS (Hybrid Mode)")
    print("-" * 76)
    hybrid_failures = accuracy_info["hybrid"]["failures"]
    miss_top3 = [f for f in hybrid_failures if not f["in_top3"]]
    miss_top1 = [f for f in hybrid_failures if f["in_top3"]]

    print(f"  Total Top-1 misses: {len(hybrid_failures)} / {total_q}")
    print(f"  Queries completely missed in Top-3: {len(miss_top3)}")
    for f in miss_top3:
        print(f"    - Query: \"{f['query']}\"")
        print(f"      Expected: {f['expected']}  -->  Top-1 Got: {f['got_top1']}")

    print(f"\n  Representative Confusing Pairs (Expected in Top-3 but not Top-1):")
    for f in miss_top1[:6]:
        print(f"    - Query: \"{f['query']}\"")
        print(f"      Expected: {f['expected']:<20}  -->  Top-1: {f['got_top1']}")

    # 6. Special Suites
    print("\n[6] SPECIAL SUITE RESULTS")
    print("-" * 76)
    ood_cases = special_info["out_of_domain"]
    ood_flagged = sum(1 for c in ood_cases if c["is_out_of_domain"])
    print(f"  Out-of-Domain Detection: {ood_flagged} / {len(ood_cases)} correctly flagged as OOD")
    for c in ood_cases:
        flag = "[OOD FLAGGED]" if c["is_out_of_domain"] else "[MISSED]"
        top_name = c["top_candidate"]["command"] if c["top_candidate"] else "None"
        print(f"    - {flag:14} Query: \"{c['query']}\"")

    edge_cases = special_info["edge_case"]
    print(f"\n  Edge & Empty Case Handling: {len(edge_cases)} cases")
    for c in edge_cases:
        print(f"    - Input: \"{c['query']}\" -> is_empty={c['is_empty']}, is_out_of_domain={c['is_out_of_domain']}")

    print("\n" + "=" * 76)
    print("                       END OF BENCHMARK REPORT")
    print("=" * 76 + "\n")


def run_full_evaluation(
    kb_path: str = "data/knowledge_base.json",
    test_path: str = "data/test_queries.json",
    model_path: str = "./models/potion-base-2M",
    output_json: str = "eval_results.json",
) -> Dict[str, Any]:
    """Execute complete end-to-end evaluation and persist results."""
    # 1. Resource footprint
    resource_info = benchmark_resource_consumption(model_path=model_path, kb_path=kb_path)
    engine = resource_info.pop("engine")

    # 2. Load test queries
    with open(test_path, "r", encoding="utf-8") as f:
        test_queries = json.load(f)

    # 3. Accuracy
    accuracy_info = evaluate_retrieval_accuracy(engine, test_queries)

    # 4. Latency
    sample_queries = [t["query"] for t in test_queries if t["query"].strip()]
    latency_info = benchmark_latency(engine, sample_queries, iterations=10)

    # 5. Special cases
    special_info = evaluate_special_cases(engine, test_queries)

    # Print summary
    print_evaluation_summary(resource_info, accuracy_info, latency_info, special_info)

    # Compile report dict
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "resource": resource_info,
        "accuracy": {
            mode: {
                "top1_acc": accuracy_info[mode]["top1_acc"],
                "top3_acc": accuracy_info[mode]["top3_acc"],
                "breakdown_by_type": accuracy_info[mode]["breakdown_by_type"],
            }
            for mode in accuracy_info
        },
        "latency": latency_info,
        "special_cases": special_info,
        "failures_hybrid": accuracy_info["hybrid"]["failures"],
    }

    # Save to JSON
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"Full benchmark JSON written to: {Path(output_json).resolve()}\n")

    return report


if __name__ == "__main__":
    run_full_evaluation()
