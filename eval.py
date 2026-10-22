"""Automated Evaluation and Benchmarking Suite for Tiny Shell Intent (Phase 1 Refined)."""

import gc
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple
import numpy as np
import psutil

from tiny_shell_intent import IntentEngine, KnowledgeBaseStore, RiskLevel
from tiny_shell_intent.schema import Candidate, QueryResult, ConfidenceLevel


HISTORICAL_BASELINE = {
    "rule": {"top1_acc": 16.7, "top3_acc": 16.7},
    "fuzzy": {"top1_acc": 58.3, "top3_acc": 86.1},
    "model": {"top1_acc": 65.3, "top3_acc": 80.6},
    "hybrid": {"top1_acc": 75.0, "top3_acc": 91.7},
}


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
    """Measure model disk footprint, memory increment, and cold/warm load times."""
    process = psutil.Process(os.getpid())

    # 1. Model disk size
    m_path = Path(model_path)
    total_bytes, file_breakdown = get_dir_size(m_path)
    model_mb = total_bytes / (1024 * 1024)

    # 2. Baseline process memory
    gc.collect()
    rss_baseline = process.memory_info().rss / (1024 * 1024)

    # 3. Cold engine initialization (Rule + Store + Fuzzy, lazy model)
    t0 = time.perf_counter()
    engine = IntentEngine(kb_path=kb_path, model_path=model_path, offline_mode=True)
    engine_init_time_ms = (time.perf_counter() - t0) * 1000
    rss_after_engine = process.memory_info().rss / (1024 * 1024)

    # 4. Model cold loading and index precomputation
    t1 = time.perf_counter()
    _ = engine.model_matcher  # Trigger lazy loading
    model_load_time_ms = (time.perf_counter() - t1) * 1000
    rss_after_model = process.memory_info().rss / (1024 * 1024)

    rss_delta = max(0.0, rss_after_model - rss_baseline)

    return {
        "model_path": str(m_path),
        "disk_size_bytes": total_bytes,
        "disk_size_mb": round(model_mb, 2),
        "file_breakdown": {k: f"{v / (1024 * 1024):.2f} MB" for k, v in file_breakdown.items()},
        "engine_init_time_ms": round(engine_init_time_ms, 2),
        "model_load_time_ms": round(model_load_time_ms, 2),
        "total_cold_startup_ms": round(engine_init_time_ms + model_load_time_ms, 2),
        "memory_rss_baseline_mb": round(rss_baseline, 2),
        "memory_rss_engine_only_mb": round(rss_after_engine, 2),
        "memory_rss_loaded_mb": round(rss_after_model, 2),
        "memory_rss_delta_mb": round(rss_delta, 2),
        "engine": engine,
    }


def evaluate_retrieval_accuracy(
    engine: IntentEngine,
    test_queries: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Evaluate Top-1 and Top-3 accuracy, acceptance gating, and dangerous misrecommendations."""
    modes = ["rule", "fuzzy", "model", "hybrid"]
    labeled_queries = [t for t in test_queries if t.get("expected_intent_id") is not None]
    total = len(labeled_queries)

    results_by_mode: Dict[str, Dict[str, Any]] = {}

    for mode in modes:
        top1_hits = 0
        top3_hits = 0
        gated_top1_hits = 0
        gated_top3_hits = 0
        false_rejections = 0
        dangerous_misrecs = 0

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

            res = engine.search(q, top_k=3, mode=mode, ood_threshold=0.42)

            # Available candidates (either accepted or debug for raw retrieval accuracy)
            raw_cands = res.candidates if res.candidates else res.debug_candidates
            raw_cand_ids = [c.intent_id for c in raw_cands]

            # Gated candidates (only accepted completions)
            gated_cand_ids = [c.intent_id for c in res.candidates]

            hit1 = bool(raw_cand_ids and raw_cand_ids[0] == expected)
            hit3 = bool(expected in raw_cand_ids[:3])

            gated_hit1 = bool(gated_cand_ids and gated_cand_ids[0] == expected)
            gated_hit3 = bool(expected in gated_cand_ids[:3])

            if hit1:
                top1_hits += 1
                per_type_stats[q_type]["top1"] += 1
            if hit3:
                top3_hits += 1
                per_type_stats[q_type]["top3"] += 1

            if gated_hit1:
                gated_top1_hits += 1
            if gated_hit3:
                gated_top3_hits += 1

            if res.is_rejected:
                false_rejections += 1

            # Check dangerous misrecommendation: query expected safe/warning, but recommended dangerous
            expected_intent = engine.store.get_by_id(expected)
            if expected_intent and expected_intent.risk_level != RiskLevel.DANGEROUS:
                if res.top_candidate and res.top_candidate.risk_level == RiskLevel.DANGEROUS.value:
                    if res.top_candidate.intent_id != expected:
                        dangerous_misrecs += 1

            if not hit1:
                got = raw_cand_ids[0] if raw_cand_ids else "None"
                confusion_pairs.append((q, expected, got))
                failures.append({
                    "query": q,
                    "type": q_type,
                    "expected": expected,
                    "got_top1": got,
                    "in_top3": hit3,
                    "is_rejected": res.is_rejected,
                    "candidates": [c.to_dict() for c in (res.candidates or res.debug_candidates)],
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
            "gated_top1_hits": gated_top1_hits,
            "gated_top1_acc": round(gated_top1_hits / total * 100, 1),
            "gated_top3_hits": gated_top3_hits,
            "gated_top3_acc": round(gated_top3_hits / total * 100, 1),
            "false_rejections": false_rejections,
            "dangerous_misrecs": dangerous_misrecs,
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

    # Test short-circuit exact query latency separately
    exact_latencies = []
    for _ in range(iterations * 2):
        for eq in ["pwd", "cls"]:
            t0 = time.perf_counter()
            _ = engine.search(eq, top_k=3, mode="hybrid")
            exact_latencies.append((time.perf_counter() - t0) * 1000)

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

    arr_exact = np.array(exact_latencies)
    latency_report["short_circuit_exact"] = {
        "mean_ms": round(float(np.mean(arr_exact)), 3),
        "p50_ms": round(float(np.percentile(arr_exact, 50)), 3),
        "p95_ms": round(float(np.percentile(arr_exact, 95)), 3),
    }

    return latency_report


def evaluate_special_cases(
    engine: IntentEngine,
    test_queries: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Specialized evaluation for short commands, out-of-domain queries, and empty inputs."""
    ood_queries = [t for t in test_queries if t.get("expected_intent_id") is None and t.get("type") != "edge_case"]
    edge_queries = [t for t in test_queries if t.get("type") == "edge_case"]

    ood_records = []
    false_acceptances = 0
    for item in ood_queries:
        q = item["query"]
        res = engine.search(q, top_k=3, mode="hybrid")
        if res.is_accepted:
            false_acceptances += 1
        ood_records.append({
            "query": q,
            "subtype": item.get("subtype", "general"),
            "is_rejected": res.is_rejected,
            "is_out_of_domain": res.is_out_of_domain,
            "rejection_reason": res.rejection_reason,
            "num_accepted_candidates": len(res.candidates),
            "debug_top": res.top_candidate.to_dict() if res.top_candidate else None,
        })

    edge_records = []
    for item in edge_queries:
        q = item["query"]
        res = engine.search(q, mode="hybrid")
        edge_records.append({
            "query": q,
            "is_empty": res.is_empty,
            "is_rejected": res.is_rejected,
            "is_out_of_domain": res.is_out_of_domain,
            "rejection_reason": res.rejection_reason,
            "candidates_count": len(res.candidates),
        })

    return {
        "out_of_domain": {
            "total": len(ood_queries),
            "correctly_rejected": len(ood_queries) - false_acceptances,
            "rejection_rate": round((len(ood_queries) - false_acceptances) / len(ood_queries) * 100, 1),
            "false_acceptances": false_acceptances,
            "records": ood_records,
        },
        "edge_cases": edge_records,
    }


def print_evaluation_summary(
    resource_info: Dict[str, Any],
    accuracy_info: Dict[str, Any],
    latency_info: Dict[str, Any],
    special_info: Dict[str, Any],
) -> None:
    """Print formatted evaluation report to stdout."""
    print("\n" + "=" * 78)
    print("      TINY SHELL INTENT — PHASE 1 REFINED QUALITY & BENCHMARK REPORT")
    print("=" * 78)

    # 1. Resource Consumption
    print("\n[1] RESOURCE FOOTPRINT & STARTUP TIMING")
    print("-" * 78)
    print(f"  Model Weight Path:          {resource_info['model_path']}")
    print(f"  Total Model Disk Size:      {resource_info['disk_size_mb']} MB ({resource_info['disk_size_bytes']:,} bytes)")
    for fname, fsize in resource_info["file_breakdown"].items():
        print(f"    - {fname:24}  {fsize}")
    print(f"  Engine Init (Lazy Model):   {resource_info['engine_init_time_ms']} ms")
    print(f"  Model Load & Pre-index:     {resource_info['model_load_time_ms']} ms")
    print(f"  Total Cold Startup Time:    {resource_info['total_cold_startup_ms']} ms")
    print(f"  Baseline Process RSS:       {resource_info['memory_rss_baseline_mb']} MB")
    print(f"  Engine Only RSS:            {resource_info['memory_rss_engine_only_mb']} MB")
    print(f"  Loaded Process RSS:         {resource_info['memory_rss_loaded_mb']} MB")
    print(f"  Incremental Memory (RSS):   {resource_info['memory_rss_delta_mb']} MB")

    # 2. Accuracy Comparison with Baseline
    print("\n[2] ACCURACY COMPARISON WITH HISTORICAL BASELINE")
    print("-" * 78)
    total_q = accuracy_info["hybrid"]["total_queries"]
    print(f"{'Mode':<10} | {'Current Top-1':<14} | {'Baseline Top-1':<15} | {'Current Top-3':<14} | {'Baseline Top-3':<14}")
    print("-" * 78)
    for mode in ["rule", "fuzzy", "model", "hybrid"]:
        st = accuracy_info[mode]
        base = HISTORICAL_BASELINE.get(mode, {"top1_acc": 0.0, "top3_acc": 0.0})
        delta1 = st['top1_acc'] - base['top1_acc']
        delta3 = st['top3_acc'] - base['top3_acc']
        sign1 = "+" if delta1 >= 0 else ""
        sign3 = "+" if delta3 >= 0 else ""
        print(
            f"{mode.upper():<10} | "
            f"{st['top1_acc']:>5.1f}% ({st['top1_hits']}/{total_q})   | "
            f"{base['top1_acc']:>5.1f}%          | "
            f"{st['top3_acc']:>5.1f}% ({st['top3_hits']}/{total_q})   | "
            f"{base['top3_acc']:>5.1f}% ({sign3}{delta3:.1f}%)"
        )

    # 3. Safety & Gating Metrics
    print("\n[3] SAFETY GATING & RISK METRICS (Hybrid Mode)")
    print("-" * 78)
    hy = accuracy_info["hybrid"]
    print(f"  Gated Accepted Top-1 Acc:   {hy['gated_top1_acc']}% ({hy['gated_top1_hits']}/{total_q})")
    print(f"  Gated Accepted Top-3 Acc:   {hy['gated_top3_acc']}% ({hy['gated_top3_hits']}/{total_q})")
    print(f"  False In-Domain Rejections: {hy['false_rejections']} / {total_q}")
    print(f"  Dangerous Misrecommendations: {hy['dangerous_misrecs']} (queries recommending unrequested DANGEROUS actions)")

    # 4. Breakdown by Query Type (Hybrid Mode)
    print("\n[4] ACCURACY BREAKDOWN BY QUERY CATEGORY (Hybrid Mode)")
    print("-" * 78)
    print(f"{'Query Type':<22} | {'Count':<7} | {'Top-1 Acc':<12} | {'Top-3 Acc':<12}")
    print("-" * 78)
    hybrid_types = accuracy_info["hybrid"]["breakdown_by_type"]
    for q_type, stats in hybrid_types.items():
        print(
            f"{q_type:<22} | "
            f"{stats['total']:<7} | "
            f"{stats['top1_acc']:>5.1f}%      | "
            f"{stats['top3_acc']:>5.1f}%"
        )

    # 5. Latency Distribution
    print("\n[5] RETRIEVAL LATENCY BENCHMARK (ms)")
    print("-" * 78)
    print(f"{'Mode':<22} | {'Mean':<8} | {'P50':<8} | {'P90':<8} | {'P95':<8} | {'P99':<8}")
    print("-" * 78)
    for mode in ["rule", "fuzzy", "model", "hybrid"]:
        lat = latency_info[mode]
        print(
            f"{mode.upper():<22} | "
            f"{lat['mean_ms']:<8.3f} | "
            f"{lat['p50_ms']:<8.3f} | "
            f"{lat['p90_ms']:<8.3f} | "
            f"{lat['p95_ms']:<8.3f} | "
            f"{lat['p99_ms']:<8.3f}"
        )
    sc = latency_info.get("short_circuit_exact")
    if sc:
        print(f"{'EXACT SHORT-CIRCUIT':<22} | {sc['mean_ms']:<8.3f} | {sc['p50_ms']:<8.3f} | {'-':<8} | {sc['p95_ms']:<8.3f} | {'-':<8}")

    # 6. OOD & Special Suites
    print("\n[6] OUT-OF-DOMAIN & NEGATIVE SAMPLE REJECTION")
    print("-" * 78)
    ood_data = special_info["out_of_domain"]
    print(f"  Total OOD / Negatives:      {ood_data['total']}")
    print(f"  Correctly Rejected:         {ood_data['correctly_rejected']} / {ood_data['total']} ({ood_data['rejection_rate']}%)")
    print(f"  False Acceptances:          {ood_data['false_acceptances']}")
    print(f"\n  Sample OOD Rejection Status:")
    for rec in ood_data["records"][:8]:
        status = "[REJECTED]" if rec["is_rejected"] else "[ACCEPTED-BUG]"
        print(f"    - {status:15} ({rec['subtype']:<20}) \"{rec['query']}\"")

    # 7. Remaining Failures
    print("\n[7] REMAINING FAILURE & CONFUSION ANALYSIS (Hybrid Mode)")
    print("-" * 78)
    hybrid_failures = accuracy_info["hybrid"]["failures"]
    miss_top3 = [f for f in hybrid_failures if not f["in_top3"]]
    print(f"  Total Top-1 misses: {len(hybrid_failures)} / {total_q}")
    print(f"  Queries completely missed in Top-3: {len(miss_top3)}")
    for f in miss_top3:
        print(f"    - Query: \"{f['query']}\"")
        print(f"      Expected: {f['expected']:<22} --> Top-1 Got: {f['got_top1']}")

    print("\n" + "=" * 78)
    print("                       END OF BENCHMARK REPORT")
    print("=" * 78 + "\n")


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
        "historical_baseline": HISTORICAL_BASELINE,
        "accuracy": {
            mode: {
                "top1_acc": accuracy_info[mode]["top1_acc"],
                "top3_acc": accuracy_info[mode]["top3_acc"],
                "gated_top1_acc": accuracy_info[mode]["gated_top1_acc"],
                "gated_top3_acc": accuracy_info[mode]["gated_top3_acc"],
                "dangerous_misrecs": accuracy_info[mode]["dangerous_misrecs"],
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
