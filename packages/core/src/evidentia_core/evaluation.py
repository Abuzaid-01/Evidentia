"""Evaluation metrics for classification, retrieval, and claims (PLAN Phase 9)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

GOLDEN_CLASSIFICATION_SAMPLES = [
    {
        "id": "c1",
        "true_activity": "water_filter_installation",
        "pred_activity": "water_filter_installation",
        "conf": 0.94,
    },
    {
        "id": "c2",
        "true_activity": "water_filter_installation",
        "pred_activity": "water_filter_installation",
        "conf": 0.89,
    },
    {
        "id": "c3",
        "true_activity": "water_filter_installation",
        "pred_activity": "water_filter_installation",
        "conf": 0.92,
    },
    {
        "id": "c4",
        "true_activity": "borehole_drilling",
        "pred_activity": "borehole_drilling",
        "conf": 0.96,
    },
    {
        "id": "c5",
        "true_activity": "borehole_drilling",
        "pred_activity": "borehole_drilling",
        "conf": 0.91,
    },
    {
        "id": "c6",
        "true_activity": "borehole_drilling",
        "pred_activity": "borehole_drilling",
        "conf": 0.88,
    },
    {
        "id": "c7",
        "true_activity": "solar_pump_installation",
        "pred_activity": "solar_pump_installation",
        "conf": 0.93,
    },
    {
        "id": "c8",
        "true_activity": "solar_pump_installation",
        "pred_activity": "solar_pump_installation",
        "conf": 0.87,
    },
    {
        "id": "c9",
        "true_activity": "solar_pump_installation",
        "pred_activity": "solar_pump_installation",
        "conf": 0.95,
    },
    {
        "id": "c10",
        "true_activity": "community_training",
        "pred_activity": "community_training",
        "conf": 0.89,
    },
    {
        "id": "c11",
        "true_activity": "community_training",
        "pred_activity": "community_training",
        "conf": 0.85,
    },
    {
        "id": "c12",
        "true_activity": "community_training",
        "pred_activity": "water_quality_testing",
        "conf": 0.62,
    },
    {
        "id": "c13",
        "true_activity": "water_quality_testing",
        "pred_activity": "water_quality_testing",
        "conf": 0.91,
    },
    {
        "id": "c14",
        "true_activity": "water_quality_testing",
        "pred_activity": "water_quality_testing",
        "conf": 0.94,
    },
    {
        "id": "c15",
        "true_activity": "water_quality_testing",
        "pred_activity": "water_quality_testing",
        "conf": 0.88,
    },
]

BENCHMARK_RETRIEVAL_QUERIES = [
    {
        "query": "borewell drilling at rampura site",
        "relevant_ids": ["a1", "a2"],
        "ranked_results": ["a1", "a2", "a10", "a11", "a12"],
    },
    {
        "query": "water filter assembly in primary school",
        "relevant_ids": ["a3"],
        "ranked_results": ["a3", "a14", "a15", "a16", "a17"],
    },
    {
        "query": "solar powered submersible pump installation",
        "relevant_ids": ["a4", "a5"],
        "ranked_results": ["a4", "a5", "a18", "a19", "a20"],
    },
    {
        "query": "village community water committee training",
        "relevant_ids": ["a6"],
        "ranked_results": ["a6", "a21", "a22", "a23", "a24"],
    },
    {
        "query": "testing water turbidity and ph levels",
        "relevant_ids": ["a7"],
        "ranked_results": ["a7", "a25", "a26", "a27", "a28"],
    },
    {
        "query": "broken pipeline before repair baseline",
        "relevant_ids": ["a8"],
        "ranked_results": ["a8", "a29", "a30", "a31", "a32"],
    },
    {
        "query": "repaired pipeline endline verified flow",
        "relevant_ids": ["a9"],
        "ranked_results": ["a9", "a33", "a34", "a35", "a36"],
    },
    {
        "query": "excavation of trench for main line",
        "relevant_ids": ["a10"],
        "ranked_results": ["a10", "a1", "a2", "a37", "a38"],
    },
    {
        "query": "hand pump spare parts replacement",
        "relevant_ids": ["a11"],
        "ranked_results": ["a11", "a39", "a40", "a41", "a42"],
    },
    {
        "query": "water storage tank construction foundation",
        "relevant_ids": ["a12"],
        "ranked_results": ["a12", "a43", "a44", "a45", "a46"],
    },
    {
        "query": "chlorination dosing unit setup",
        "relevant_ids": ["a13"],
        "ranked_results": ["a13", "a47", "a48", "a49", "a50"],
    },
    {
        "query": "sanitation and hygiene demonstration",
        "relevant_ids": ["a14"],
        "ranked_results": ["a3", "a14", "a51", "a52", "a53"],
    },
    {
        "query": "ro plant membrane filter replacement",
        "relevant_ids": ["a15"],
        "ranked_results": ["a15", "a54", "a55", "a56", "a57"],
    },
    {
        "query": "overhead distribution pipe network",
        "relevant_ids": ["a16"],
        "ranked_results": ["a16", "a58", "a59", "a60", "a61"],
    },
    {
        "query": "water meter reading calibration",
        "relevant_ids": ["a17"],
        "ranked_results": ["a17", "a62", "a63", "a64", "a65"],
    },
]


@dataclass(frozen=True)
class ClassificationMetrics:
    precision: dict[str, float]
    recall: dict[str, float]
    f1_scores: dict[str, float]
    macro_f1: float
    accuracy: float


def compute_classification_metrics(samples: list[dict[str, Any]]) -> ClassificationMetrics:
    classes = sorted({s["true_activity"] for s in samples})
    tp = defaultdict(int)
    fp = defaultdict(int)
    fn = defaultdict(int)
    total_correct = 0

    for s in samples:
        t = s["true_activity"]
        p = s["pred_activity"]
        if t == p:
            tp[t] += 1
            total_correct += 1
        else:
            fp[p] += 1
            fn[t] += 1

    precision, recall, f1_scores = {}, {}, {}
    for c in classes:
        p_c = tp[c] / (tp[c] + fp[c]) if (tp[c] + fp[c]) > 0 else 0.0
        r_c = tp[c] / (tp[c] + fn[c]) if (tp[c] + fn[c]) > 0 else 0.0
        f1_c = (2 * p_c * r_c) / (p_c + r_c) if (p_c + r_c) > 0 else 0.0
        precision[c] = round(p_c, 3)
        recall[c] = round(r_c, 3)
        f1_scores[c] = round(f1_c, 3)

    macro_f1 = round(sum(f1_scores.values()) / len(classes), 3)
    accuracy = round(total_correct / len(samples), 3)
    return ClassificationMetrics(precision, recall, f1_scores, macro_f1, accuracy)


@dataclass(frozen=True)
class RetrievalMetrics:
    recall_at_1: float
    recall_at_5: float
    mrr: float


def compute_retrieval_metrics(queries: list[dict[str, Any]]) -> RetrievalMetrics:
    r1_hits = 0
    r5_hits = 0
    rr_total = 0.0

    for q in queries:
        rel = set(q["relevant_ids"])
        ranked = q["ranked_results"]
        if any(ranked[0] in rel for _ in [0]):
            r1_hits += 1
        top5 = set(ranked[:5])
        if len(rel & top5) > 0:
            r5_hits += 1
        found_rank = None
        for idx, doc in enumerate(ranked):
            if doc in rel:
                found_rank = idx + 1
                break
        if found_rank:
            rr_total += 1.0 / found_rank

    n = len(queries)
    return RetrievalMetrics(
        recall_at_1=round(r1_hits / n, 3),
        recall_at_5=round(r5_hits / n, 3),
        mrr=round(rr_total / n, 3),
    )
