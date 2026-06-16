#!/usr/bin/env python3
"""Prepare a PerfTools LightGBM_model/1.0 NCU input CSV.

BenchKit's NCU profiler archive stores Nsight Compute raw CSV in the wide
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

from prepare_gpu_mlp_ncu_input import (
    build_wide_ncu_csv,
    extract_padata,
    read_clean_raw_csv,
    strip_ncu_log_preamble,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--padata", help="BenchKit padata*.tgz archive")
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
        print(f"wrote {out_csv}: {len(raw_df)} kernels")
    finally:
        if work_dir_owned and not args.keep_work:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
