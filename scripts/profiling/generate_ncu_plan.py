#!/usr/bin/env python3
"""Generate an Nsight Compute sampling plan from an Nsight Systems summary.

This helper intentionally does not run ``nsys`` or ``ncu``.  It converts a
lightweight CUDA kernel summary, typically exported from
``nsys stats --report cuda_gpu_kern_sum --format csv``, into two JSON files:

* a normalized kernel-discovery summary
* a compact NCU profile plan for the most important kernels

The generated plan lets application wrappers avoid hand-maintaining kernel
regular expressions, launch-skip values, and launch counts.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1


@dataclass
class KernelSummary:
    name: str
    total_time_ns: float
    instances: int
    avg_time_ns: float | None = None
    time_pct: float | None = None
    min_time_ns: float | None = None
    max_time_ns: float | None = None
    stddev_time_ns: float | None = None

    def to_json(self, rank: int, total_gpu_time_ns: float) -> dict[str, Any]:
        pct = self.time_pct
        if pct is None and total_gpu_time_ns > 0:
            pct = self.total_time_ns / total_gpu_time_ns * 100.0
        return {
            "rank": rank,
            "name": self.name,
            "total_time_ns": self.total_time_ns,
            "time_pct": pct,
            "instances": self.instances,
            "avg_time_ns": self.avg_time_ns,
            "min_time_ns": self.min_time_ns,
            "max_time_ns": self.max_time_ns,
            "stddev_time_ns": self.stddev_time_ns,
        }


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _parse_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"-", "N/A", "n/a", "nan", "NaN"}:
        return None
    text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_int(value: Any) -> int:
    parsed = _parse_number(value)
    if parsed is None:
        return 0
    return int(parsed)


def _time_unit_multiplier_ns(header: str) -> float:
    normalized = _normalize_header(header)
    if normalized.endswith("_ns") or normalized.endswith("_nsec"):
        return 1.0
    if normalized.endswith("_us") or normalized.endswith("_usec"):
        return 1_000.0
    if normalized.endswith("_ms") or normalized.endswith("_msec"):
        return 1_000_000.0
    if normalized.endswith("_s") or normalized.endswith("_sec"):
        return 1_000_000_000.0
    # Nsight Systems usually writes "Total Time (ns)" or "Avg (ns)"; if the
    # unit is omitted in a fixture, keep the value as nanoseconds.
    return 1.0


def _pick(row: dict[str, str], aliases: Iterable[str]) -> tuple[str, str] | None:
    normalized = {_normalize_header(key): key for key in row}
    for alias in aliases:
        key = normalized.get(alias)
        if key is not None:
            return key, row[key]
    return None


def parse_nsys_kernel_csv(csv_path: Path) -> list[KernelSummary]:
    """Parse an Nsight Systems CUDA kernel summary CSV.

    The parser accepts the common ``cuda_gpu_kern_sum`` spelling and a small
    set of alias headers so that checked-in fixtures remain readable.
    """

    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        lines = [line for line in handle if line.strip()]

    header_index = 0
    for index, line in enumerate(lines):
        try:
            candidate = next(csv.reader([line]))
        except csv.Error:
            continue
        normalized = {_normalize_header(item) for item in candidate}
        has_name = bool(normalized & {"name", "kernel_name", "demangled_name"})
        has_total = bool(
            normalized
            & {
                "total_time_ns",
                "total_time_nsec",
                "total_time",
                "time_ns",
                "total_ns",
            }
        )
        if has_name and has_total:
            header_index = index
            break

    rows = list(csv.DictReader(lines[header_index:]))

    kernels: list[KernelSummary] = []
    for row in rows:
        name_item = _pick(row, ["name", "kernel_name", "demangled_name"])
        total_item = _pick(
            row,
            [
                "total_time_ns",
                "total_time_nsec",
                "total_time",
                "time_ns",
                "total_ns",
            ],
        )
        if name_item is None or total_item is None:
            continue

        total_value = _parse_number(total_item[1])
        if total_value is None:
            continue
        total_time_ns = total_value * _time_unit_multiplier_ns(total_item[0])

        instances_item = _pick(row, ["instances", "calls", "count"])
        avg_item = _pick(row, ["avg_ns", "avg_nsec", "avg_time_ns", "avg", "average_ns"])
        pct_item = _pick(row, ["time", "time_pct", "total_time_pct", "percent", "time_percent"])
        min_item = _pick(row, ["min_ns", "min_nsec", "min"])
        max_item = _pick(row, ["max_ns", "max_nsec", "max"])
        std_item = _pick(row, ["stddev_ns", "std_dev_ns", "stddev", "stdev_ns"])

        def time_or_none(item: tuple[str, str] | None) -> float | None:
            if item is None:
                return None
            parsed = _parse_number(item[1])
            if parsed is None:
                return None
            return parsed * _time_unit_multiplier_ns(item[0])

        kernels.append(
            KernelSummary(
                name=name_item[1].strip(),
                total_time_ns=total_time_ns,
                instances=_parse_int(instances_item[1]) if instances_item else 0,
                avg_time_ns=time_or_none(avg_item),
                time_pct=_parse_number(pct_item[1]) if pct_item else None,
                min_time_ns=time_or_none(min_item),
                max_time_ns=time_or_none(max_item),
                stddev_time_ns=time_or_none(std_item),
            )
        )

    kernels.sort(key=lambda item: item.total_time_ns, reverse=True)
    return kernels


def _regex_exact_kernel_name(kernel_name: str) -> str:
    return f"regex:^{re.escape(kernel_name)}$"


def _slugify_kernel_name(kernel_name: str, index: int) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", kernel_name).strip("_").lower()
    slug = re.sub(r"_+", "_", slug)
    if not slug:
        slug = "kernel"
    return f"k{index:03d}_{slug[:48]}"


def _launch_skip(instances: int, warmup_fraction: float, max_skip: int) -> int:
    if instances <= 1:
        return 0
    skip = int(instances * warmup_fraction)
    skip = min(skip, max_skip)
    return min(skip, instances - 1)


def _launch_count(instances: int, skip: int, requested: int) -> int:
    remaining = max(instances - skip, 1)
    return max(1, min(requested, remaining))


def select_kernels(
    kernels: list[KernelSummary],
    *,
    top_k: int,
    min_total_time_pct: float,
    min_instances: int,
) -> list[KernelSummary]:
    total = sum(item.total_time_ns for item in kernels)
    selected: list[KernelSummary] = []
    for item in kernels:
        pct = item.time_pct
        if pct is None and total > 0:
            pct = item.total_time_ns / total * 100.0
        if item.instances < min_instances:
            continue
        if pct is not None and pct < min_total_time_pct:
            continue
        selected.append(item)
        if len(selected) >= top_k:
            break
    return selected


def build_discovery_json(csv_path: Path, kernels: list[KernelSummary]) -> dict[str, Any]:
    total_gpu_time_ns = sum(item.total_time_ns for item in kernels)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "tool": "nsys",
            "report": "cuda_gpu_kern_sum",
            "path": str(csv_path),
        },
        "summary": {
            "kernel_count": len(kernels),
            "total_gpu_time_ns": total_gpu_time_ns,
        },
        "kernels": [
            item.to_json(rank=index, total_gpu_time_ns=total_gpu_time_ns)
            for index, item in enumerate(kernels, start=1)
        ],
    }


def build_ncu_plan_json(
    *,
    discovery_path: Path | None,
    selected: list[KernelSummary],
    all_kernels: list[KernelSummary],
    metric_set: str,
    launch_count: int,
    warmup_fraction: float,
    max_launch_skip: int,
    archive_ncu_report: bool,
) -> dict[str, Any]:
    total_gpu_time_ns = sum(item.total_time_ns for item in all_kernels)
    profiles = []
    for index, item in enumerate(selected, start=1):
        skip = _launch_skip(item.instances, warmup_fraction, max_launch_skip)
        count = _launch_count(item.instances, skip, launch_count)
        pct = item.time_pct
        if pct is None and total_gpu_time_ns > 0:
            pct = item.total_time_ns / total_gpu_time_ns * 100.0
        profiles.append(
            {
                "name": _slugify_kernel_name(item.name, index),
                "section": None,
                "kernel_name": item.name,
                "kernel_match": {
                    "name_base": "demangled",
                    "mode": "regex",
                    "pattern": _regex_exact_kernel_name(item.name),
                },
                "launch_skip": skip,
                "launch_count": count,
                "metric_set": metric_set,
                "archive_ncu_report": archive_ncu_report,
                "selection": {
                    "rank": index,
                    "total_time_ns": item.total_time_ns,
                    "time_pct": pct,
                    "instances": item.instances,
                    "avg_time_ns": item.avg_time_ns,
                },
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "discovery_path": str(discovery_path) if discovery_path else None,
            "tool": "nsys",
            "report": "cuda_gpu_kern_sum",
        },
        "policy": {
            "metric_set": metric_set,
            "requested_launch_count": launch_count,
            "warmup_fraction": warmup_fraction,
            "max_launch_skip": max_launch_skip,
            "archive_ncu_report": archive_ncu_report,
        },
        "profiles": profiles,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nsys-csv", required=True, type=Path, help="nsys cuda_gpu_kern_sum CSV")
    parser.add_argument("--out-discovery", type=Path, help="output kernel discovery JSON")
    parser.add_argument("--out-plan", type=Path, help="output NCU plan JSON")
    parser.add_argument("--top-k", type=int, default=5, help="maximum selected kernels")
    parser.add_argument("--min-total-time-pct", type=float, default=3.0, help="minimum GPU time percentage")
    parser.add_argument("--min-instances", type=int, default=1, help="minimum launch count")
    parser.add_argument("--launch-count", type=int, default=10, help="requested NCU launches per kernel")
    parser.add_argument("--warmup-fraction", type=float, default=0.10, help="fraction of launches to skip")
    parser.add_argument("--max-launch-skip", type=int, default=100, help="maximum generated launch skip")
    parser.add_argument("--metric-set", default="gpu_kernel_estimation", help="NCU metric-set label")
    parser.add_argument("--archive-ncu-report", action="store_true", help="request .ncu-rep archive retention")
    parser.add_argument("--print-plan", action="store_true", help="print generated plan to stdout")
    args = parser.parse_args(argv)

    if args.top_k < 1:
        parser.error("--top-k must be >= 1")
    if args.launch_count < 1:
        parser.error("--launch-count must be >= 1")
    if args.warmup_fraction < 0:
        parser.error("--warmup-fraction must be >= 0")
    if args.max_launch_skip < 0:
        parser.error("--max-launch-skip must be >= 0")

    kernels = parse_nsys_kernel_csv(args.nsys_csv)
    if not kernels:
        print(f"No CUDA kernels parsed from {args.nsys_csv}", file=sys.stderr)
        return 1

    selected = select_kernels(
        kernels,
        top_k=args.top_k,
        min_total_time_pct=args.min_total_time_pct,
        min_instances=args.min_instances,
    )
    if not selected:
        print("No CUDA kernels matched the selection policy", file=sys.stderr)
        return 1

    discovery = build_discovery_json(args.nsys_csv, kernels)
    plan = build_ncu_plan_json(
        discovery_path=args.out_discovery,
        selected=selected,
        all_kernels=kernels,
        metric_set=args.metric_set,
        launch_count=args.launch_count,
        warmup_fraction=args.warmup_fraction,
        max_launch_skip=args.max_launch_skip,
        archive_ncu_report=args.archive_ncu_report,
    )

    if args.out_discovery:
        write_json(args.out_discovery, discovery)
    if args.out_plan:
        write_json(args.out_plan, plan)
    if args.print_plan or not args.out_plan:
        print(json.dumps(plan, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
