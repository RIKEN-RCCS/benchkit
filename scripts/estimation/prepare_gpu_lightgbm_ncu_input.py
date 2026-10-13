#!/usr/bin/env python3
"""Prepare a PerfTools LightGBM_model/1.0 NCU input CSV.

Benchkit's NCU profiler archive stores Nsight Compute raw CSV in the wide
metric layout exported by ``ncu --page raw --csv``.  PerfTools LightGBM can read
wide CSV directly, but it expects a few compatibility columns such as
``Duration [ns]`` to already exist.  This bridge normalizes the archive into
that wide CSV without running the MLP-specific ``prepare_data.py`` step.
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

import pandas as pd

from prepare_gpu_mlp_ncu_input import (
    build_wide_ncu_csv,
    extract_padata,
    read_clean_raw_csv,
    strip_ncu_log_preamble,
    observed_numeric,
)


def normalize_lightgbm_columns(wide: pd.DataFrame) -> pd.DataFrame:
    """Expose observed NCU values under the names expected by LightGBM."""
    wide = wide.copy()
    aliases = {
        "Achieved Occupancy": (
            "Achieved Occupancy [%]", "sm__warps_active.avg.pct_of_peak_sustained_active",
        ),
        "Executed Ipc Active [inst/cycle]": (
            "sm__inst_executed.avg.per_cycle_active",
        ),
        "Max Cluster Size [block]": ("launch__cluster_max_potential_size",),
        "Block Limit Barriers [block]": ("launch__occupancy_limit_barriers",),
    }
    for label, names in aliases.items():
        wide[label] = observed_numeric(wide, label, *names)

    # Issued and executed instructions can differ. Convert the per-issued
    # latency using counts from the same SMSP domain, rather than renaming it.
    issued = observed_numeric(wide, "smsp__inst_issued.sum")
    executed = observed_numeric(wide, "smsp__inst_executed.sum")
    latency = observed_numeric(wide, "smsp__average_warp_latency_per_inst_issued.ratio")
    derived = latency * issued / executed.where(executed > 0)
    label = "Warp Cycles Per Executed Instruction [cycle/inst]"
    observed = observed_numeric(wide, label, "Warp Cycles Per Executed Instruction [cycle]")
    wide[label] = observed.combine_first(derived)
    return wide


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--padata", help="Benchkit padata*.tgz archive")
    input_group.add_argument("--raw-csv", help="Nsight Compute raw wide CSV")
    parser.add_argument("--source-gpu", default="H100")
    parser.add_argument("--out-csv", required=True)
    parser.add_argument("--work-dir")
    parser.add_argument("--keep-work", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_csv = Path(args.out_csv).resolve()
    work_dir_owned = False
    if args.work_dir:
        work_dir = Path(args.work_dir).resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
    else:
        work_dir = Path(tempfile.mkdtemp(prefix="benchkit-gpu-lightgbm-"))
        work_dir_owned = True

    try:
        if args.raw_csv:
            raw_csv = Path(args.raw_csv).resolve()
        else:
            raw_csv = extract_padata(Path(args.padata).resolve(), work_dir / "padata")

        clean_csv = work_dir / "profile_raw_clean.csv"
        strip_ncu_log_preamble(raw_csv, clean_csv)
        raw_df = read_clean_raw_csv(clean_csv)
        if raw_df.empty:
            raise SystemExit(f"no kernel rows found in {raw_csv}")

        build_wide_ncu_csv(raw_df, out_csv, args.source_gpu)
        normalize_lightgbm_columns(pd.read_csv(out_csv, low_memory=False)).to_csv(out_csv, index=False)
        print(f"wrote {out_csv}: {len(raw_df)} kernels")
    finally:
        if work_dir_owned and not args.keep_work:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
