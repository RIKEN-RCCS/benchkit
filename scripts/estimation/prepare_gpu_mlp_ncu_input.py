#!/usr/bin/env python3
"""Prepare a PerfTools MLP_NN input CSV from an Nsight Compute archive.

This is a small compatibility bridge for Benchkit.  It converts the wide
Nsight Compute raw CSV exported from ``profile.ncu-rep`` into the CSV layout
expected by PerfTools' ``MLP_NN/examples/prepare_data.py``, then fills missing target-GPU specification columns. Source-GPU values
come from the collected report and are never replaced with fixed defaults.
"""

from __future__ import annotations

import argparse
import csv
import math
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

import pandas as pd


SPEC_DEFAULTS = {
    "A100": {
        "GPU Maximum Warps Per Scheduler [warp]": 16,
        "Theoretical Active Warps per SM [warp]": 64,
        "Theoretical Active Warps Per Scheduler [warp]": 16,
        "Shared Memory Configuration Size [byte]": 167936,
        "Block Limit Warps [block]": 64,
    },
    "H100": {
        "GPU Maximum Warps Per Scheduler [warp]": 16,
        "Theoretical Active Warps per SM [warp]": 64,
        "Theoretical Active Warps Per Scheduler [warp]": 16,
        "Shared Memory Configuration Size [byte]": 233472,
        "Block Limit Warps [block]": 64,
    },
    "GB200": {
        "GPU Maximum Warps Per Scheduler [warp]": 16,
        "Theoretical Active Warps per SM [warp]": 64,
        "Theoretical Active Warps Per Scheduler [warp]": 16,
        "Shared Memory Configuration Size [byte]": 233472,
        "Block Limit Warps [block]": 64,
    },
    "GB10": {
        "GPU Maximum Warps Per Scheduler [warp]": 16,
        "Theoretical Active Warps per SM [warp]": 64,
        "Theoretical Active Warps Per Scheduler [warp]": 16,
        "Shared Memory Configuration Size [byte]": 101376,
        "Block Limit Warps [block]": 64,
    },
}

SOURCE_SPEC_COLUMNS = tuple(SPEC_DEFAULTS["H100"])


ALLOWED_NAN_COLUMNS = {"Warp Cycles Per Executed Instruction [cycle/inst]"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--padata", help="Benchkit padata*.tgz archive")
    input_group.add_argument("--raw-csv", help="Nsight Compute raw wide CSV")
    parser.add_argument("--perftools-root", required=True)
    parser.add_argument("--source-gpu", default="H100")
    parser.add_argument("--target-gpu", default="")
    parser.add_argument("--kernel-count", type=int, default=20)
    parser.add_argument("--out-csv", required=True)
    parser.add_argument("--work-dir")
    parser.add_argument("--keep-work", action="store_true")
    parser.add_argument(
        "--allow-nan",
        action="append",
        default=[],
        help="Additional prepared-input column allowed to remain NaN",
    )
    return parser.parse_args()


def safe_members(tgz: Path) -> list[tarfile.TarInfo]:
    members: list[tarfile.TarInfo] = []
    with tarfile.open(tgz, "r:gz") as archive:
        for member in archive.getmembers():
            member_path = Path(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise SystemExit(f"unsafe padata member path: {member.name}")
            members.append(member)
    return members


def extract_padata(tgz: Path, dest: Path) -> Path:
    members = safe_members(tgz)
    with tarfile.open(tgz, "r:gz") as archive:
        archive.extractall(dest, members=members)

    candidates = sorted(dest.rglob("profile_raw.csv"))
    if candidates:
        return candidates[0]

    raise SystemExit(
        f"{tgz} does not contain profile_raw.csv; enable BK_PROFILER_NCU_RAW_CSV=true"
    )


def strip_ncu_log_preamble(raw_csv: Path, clean_csv: Path) -> None:
    lines = raw_csv.read_text(errors="replace").splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.startswith('"ID","Process ID"'):
            start = idx
            break
    if start is None:
        raise SystemExit(f"no Nsight Compute CSV header found in {raw_csv}")
    clean_csv.write_text("\n".join(lines[start:]) + "\n")


def read_clean_raw_csv(clean_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(clean_csv, low_memory=False)
    if "Kernel Name" not in df.columns:
        raise SystemExit(f"raw CSV has no Kernel Name column: {clean_csv}")
    return df[df["Kernel Name"].notna()].copy()


def numeric(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series([pd.NA] * len(df), index=df.index)
    return pd.to_numeric(
        df[column].astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    )


def first_numeric(df: pd.DataFrame, *columns: str) -> pd.Series:
    for column in columns:
        series = numeric(df, column)
        if series.notna().any():
            return series
    return pd.Series([pd.NA] * len(df), index=df.index)


def observed_numeric(df: pd.DataFrame, *columns: str) -> pd.Series:
    """Keep observed values, filling only missing rows from alternate names."""
    result = pd.Series(float("nan"), index=df.index)
    for column in columns:
        result = result.combine_first(numeric(df, column))
    return result


def build_wide_ncu_csv(raw_df: pd.DataFrame, out_csv: Path, source_gpu: str) -> None:
    out = raw_df.copy()

    duration_ns = first_numeric(raw_df, "gpu__time_duration.sum")
    dram_bps = first_numeric(raw_df, "dram__bytes.sum.per_second")
    if not dram_bps.notna().any():
        dram_bps = first_numeric(raw_df, "dram__bytes.sum") / (duration_ns * 1e-9)

    values = {
        "Duration [ns]": duration_ns,
        "Block Size": first_numeric(raw_df, "launch__block_size"),
        "Grid Size": first_numeric(raw_df, "launch__grid_size"),
        "Threads": first_numeric(raw_df, "launch__thread_count"),
        "Registers Per Thread [register/thread]": first_numeric(
            raw_df, "launch__registers_per_thread"
        ),
        "Static Shared Memory Per Block [byte/block]": first_numeric(
            raw_df, "launch__shared_mem_per_block_static"
        ),
        "Dynamic Shared Memory Per Block [byte/block]": first_numeric(
            raw_df, "launch__shared_mem_per_block_dynamic"
        ),
        "Shared Memory Per Block [byte/block]": first_numeric(
            raw_df, "launch__shared_mem_per_block"
        ),
        "Memory Throughput [byte/s]": dram_bps,
        "Achieved Occupancy [%]": first_numeric(
            raw_df, "sm__warps_active.avg.pct_of_peak_sustained_active"
        ),
        "Achieved Active Warps Per SM [warp]": first_numeric(
            raw_df, "sm__warps_active.avg.per_cycle_active"
        ),
        "Eligible Warps Per Scheduler [warp]": first_numeric(
            raw_df, "smsp__warps_eligible.avg.per_cycle_active"
        ),
        "Compute (SM) Throughput [%]": first_numeric(
            raw_df, "sm__throughput.avg.pct_of_peak_sustained_elapsed"
        ),
        "Memory Throughput [%]": first_numeric(
            raw_df,
            "gpu__compute_memory_throughput.avg.pct_of_peak_sustained_elapsed",
            "gpu__dram_throughput.avg.pct_of_peak_sustained_elapsed",
            "FBSP.TriageCompute.dramc__throughput.avg.pct_of_peak_sustained_elapsed",
        ),
        "L1/TEX Cache Throughput [%]": first_numeric(
            raw_df,
            "l1tex__throughput.avg.pct_of_peak_sustained_active",
            "l1tex__throughput.avg.pct_of_peak_sustained_elapsed",
            "SM_A.TriageCompute.l1tex__throughput.avg.pct_of_peak_sustained_elapsed",
        ),
        "L2 Cache Throughput [%]": first_numeric(
            raw_df,
            "lts__throughput.avg.pct_of_peak_sustained_elapsed",
            "LTS.TriageCompute.lts__throughput.avg.pct_of_peak_sustained_elapsed",
        ),
        "Waves Per SM": first_numeric(raw_df, "launch__waves_per_multiprocessor"),
        "Elapsed Cycles [cycle]": first_numeric(raw_df, "sm__cycles_elapsed.avg"),
        "GPU Maximum Warps Per Scheduler [warp]": observed_numeric(
            raw_df, "GPU Maximum Warps Per Scheduler [warp]",
            "device__attribute_max_warps_per_scheduler",
        ),
        "Theoretical Active Warps per SM [warp]": observed_numeric(
            raw_df, "Theoretical Active Warps per SM [warp]",
            "sm__maximum_warps_avg_per_active_cycle",
        ),
        "Theoretical Active Warps Per Scheduler [warp]": observed_numeric(
            raw_df, "Theoretical Active Warps Per Scheduler [warp]",
            "Theoretical Warps Per Scheduler [warp]",
            "smsp__maximum_warps_avg_per_active_cycle",
        ),
        "Shared Memory Configuration Size [byte]": observed_numeric(
            raw_df, "Shared Memory Configuration Size [byte]",
            "launch__shared_mem_config_size",
        ),
        "Block Limit Registers [block]": observed_numeric(
            raw_df, "launch__occupancy_limit_registers"
        ),
        "Block Limit Warps [block]": observed_numeric(
            raw_df, "Block Limit Warps [block]", "launch__occupancy_limit_warps"
        ),
        "Block Limit SM [block]": first_numeric(raw_df, "launch__occupancy_limit_blocks"),
        "Block Limit Shared Mem [block]": first_numeric(
            raw_df, "launch__occupancy_limit_shared_mem"
        ),
    }

    for label, raw_name in {
        "Stall Barrier [inst]": "barrier",
        "Stall Branch Resolving [inst]": "branch_resolving",
        "Stall Dispatch Stall [inst]": "dispatch_stall",
        "Stall Drain [inst]": "drain",
        "Stall LG Throttle [inst]": "lg_throttle",
        "Stall Long Scoreboard [inst]": "long_scoreboard",
        "Stall MIO Throttle [inst]": "mio_throttle",
        "Stall Math Pipe Throttle [inst]": "math_pipe_throttle",
        "Stall Membar [inst]": "membar",
        "Stall Misc [inst]": "misc",
        "Stall No Instruction [inst]": "no_instruction",
        "Stall Not Selected [inst]": "not_selected",
        "Stall Short Scoreboard [inst]": "short_scoreboard",
        "Stall Sleeping [inst]": "sleeping",
        "Stall Tex Throttle [inst]": "tex_throttle",
        "Stall Wait [inst]": "wait",
    }.items():
        values[label] = first_numeric(
            raw_df,
            f"smsp__average_warps_issue_stalled_{raw_name}_per_issue_active.ratio",
            f"smsp__pcsamp_warps_issue_stalled_{raw_name}",
        )

    for label, op in {
        "Predicated-On FFMA Operations Per Cycle [inst]": "ffma",
        "Predicated-On FADD Thread Instructions Executed Per Cycle [inst/cycle]": "fadd",
        "Predicated-On FMUL Thread Instructions Executed Per Cycle [inst/cycle]": "fmul",
        "Predicated-On DFMA Operations Per Cycle [inst]": "dfma",
        "Predicated-On DADD Thread Instructions Executed Per Cycle [inst/cycle]": "dadd",
        "Predicated-On DMUL Thread Instructions Executed Per Cycle [inst/cycle]": "dmul",
    }.items():
        values[label] = first_numeric(
            raw_df, f"smsp__sass_thread_inst_executed_op_{op}_pred_on.avg.per_cycle_elapsed"
        )

    for label, series in values.items():
        out[label] = series

    out["SRC GPU"] = source_gpu
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_csv, index=False)


def make_prepare_data_zip(source_gpu: str, wide_csv: Path, out_zip: Path) -> None:
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(wide_csv, f"{source_gpu}/benchkit_ncu.csv")


def run_prepare_data(
    perftools_root: Path,
    raw_zip: Path,
    source_gpu: str,
    kernel_count: int,
    out_csv: Path,
) -> None:
    prepare_data = perftools_root / "MLP_NN" / "examples" / "prepare_data.py"
    if not prepare_data.is_file():
        raise SystemExit(f"PerfTools prepare_data.py not found: {prepare_data}")

    cmd = [
        sys.executable,
        str(prepare_data),
        "--raw",
        str(raw_zip),
        "--src",
        source_gpu,
        "--n",
        str(kernel_count),
        "--out",
        str(out_csv),
    ]
    subprocess.run(cmd, cwd=perftools_root, check=True)


def fill_spec_defaults(df: pd.DataFrame) -> list[dict]:
    applied = []
    # Missing source observations must remain visible; only target defaults
    # are retained until the target-feature policy is resolved separately.
    for role, gpu_col in (("TGT", "tgt_gpu"),):
        if gpu_col not in df.columns:
            continue
        for row_idx, gpu_name in df[gpu_col].astype(str).items():
            defaults = SPEC_DEFAULTS.get(gpu_name.upper())
            if defaults is None:
                continue
            for suffix, value in defaults.items():
                column = f"{role} {suffix}"
                if column in df.columns and is_missing(df.at[row_idx, column]):
                    df.at[row_idx, column] = value
                    applied.append({"row": int(row_idx), "gpu": gpu_name.upper(), "column": column, "value": value})
    return applied


def is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        if isinstance(value, float) and math.isnan(value):
            return True
    except TypeError:
        pass
    return isinstance(value, str) and value.strip() == ""


def finalize_prepared_input(
    prepared_csv: Path,
    raw_df: pd.DataFrame,
    out_csv: Path,
    allowed_nan: set[str],
    target_gpu: str,
    source_wide: pd.DataFrame | None = None,
) -> None:
    df = pd.read_csv(prepared_csv)

    if target_gpu:
        target_columns = [
            col
            for col in ("tgt_gpu", "target_gpu", "TGT GPU", "Target GPU")
            if col in df.columns
        ]
        if not target_columns:
            raise SystemExit(
                "prepared input has no target GPU column; cannot enforce --target-gpu"
            )
        target_column = target_columns[0]
        before_count = len(df)
        df = df[
            df[target_column].astype(str).str.upper() == target_gpu.upper()
        ].copy()
        if df.empty:
            raise SystemExit(
                f"prepared input has no rows for target GPU {target_gpu}; "
                f"available targets: {sorted(pd.read_csv(prepared_csv)[target_column].dropna().astype(str).unique())}"
            )
        if len(df) != before_count:
            print(
                f"filtered prepared input to target GPU {target_gpu}: "
                f"{len(df)}/{before_count} rows",
                file=sys.stderr,
            )

    source_positions = None
    if source_wide is not None:
        # Match the upstream complete-row selection while retaining raw positions
        # for every per-kernel field, including IPC.
        required = ["Execution Time", "Block Size", "Memory Throughput [byte/s]"]
        source_rows = source_wide.rename(columns={"Duration [ns]": "Execution Time"}).reset_index(drop=True)
        complete = pd.concat(
            [pd.to_numeric(source_rows[column], errors="coerce").notna()
             for column in required], axis=1
        ).all(axis=1)
        source_positions = source_rows.index[complete].tolist()
        source_rows = source_rows.loc[complete].reset_index(drop=True)
        if any(index >= len(source_rows) for index in df.index):
            raise SystemExit("prepared input cannot be matched to collected source rows")
        for index in df.index:
            if "Kernel Name" in df.columns and "Kernel Name" in source_rows.columns:
                if str(df.at[index, "Kernel Name"]) != str(source_rows.at[index, "Kernel Name"]):
                    raise SystemExit("prepared input kernel order differs from collected source rows")
            for column in SOURCE_SPEC_COLUMNS:
                output_column = "SRC " + column
                if output_column in df.columns:
                    df.at[index, output_column] = source_rows.at[index, column]

    ipc = observed_numeric(
        raw_df,
        "sm__inst_executed.avg.per_cycle_active",
        "TPC.TriageCompute.sm__inst_executed_realtime.avg.per_cycle_active",
    ).reset_index(drop=True)
    if "Executed Ipc Active [inst/cycle]" in df.columns:
        if source_positions is not None:
            positions = [source_positions[index] for index in df.index]
            if any(position >= len(ipc) for position in positions):
                raise SystemExit("collected IPC rows cannot be matched to prepared input")
            values = ipc.iloc[positions].to_numpy()
        else:
            values = ipc.reindex(df.index).to_numpy()
        df["Executed Ipc Active [inst/cycle]"] = values
        mean_ipc = df["Executed Ipc Active [inst/cycle]"].mean()
        df["Executed Ipc Active [inst/cycle]"] = df[
            "Executed Ipc Active [inst/cycle]"
        ].fillna(mean_ipc)

    applied = fill_spec_defaults(df)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    Path(str(out_csv) + ".preprocessing.json").write_text(json.dumps({"spec_supplements": applied}, sort_keys=True) + "\n")
    df.to_csv(out_csv, index=False, quoting=csv.QUOTE_MINIMAL)

    nan_counts = df.isna().sum()
    bad_columns = sorted(col for col, count in nan_counts.items() if count > 0)
    unexpected = [col for col in bad_columns if col not in allowed_nan]
    if unexpected:
        formatted = "\n".join(f"  {col}: {int(nan_counts[col])}" for col in unexpected)
        raise SystemExit(f"prepared input still has unexpected NaN columns:\n{formatted}")


def main() -> None:
    args = parse_args()
    perftools_root = Path(args.perftools_root).resolve()
    out_csv = Path(args.out_csv).resolve()
    work_dir_owned = False
    if args.work_dir:
        work_dir = Path(args.work_dir).resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
    else:
        work_dir = Path(tempfile.mkdtemp(prefix="benchkit-gpu-mlp-"))
        work_dir_owned = True

    try:
        if args.raw_csv:
            raw_csv = Path(args.raw_csv).resolve()
        else:
            raw_csv = extract_padata(Path(args.padata).resolve(), work_dir / "padata")

        clean_csv = work_dir / "profile_raw_clean.csv"
        wide_csv = work_dir / "wide" / args.source_gpu / "benchkit_ncu.csv"
        raw_zip = work_dir / "benchkit_ncu_wide.zip"
        prepared_csv = work_dir / "perftools_prepared.csv"

        strip_ncu_log_preamble(raw_csv, clean_csv)
        raw_df = read_clean_raw_csv(clean_csv)
        if raw_df.empty:
            raise SystemExit(f"no kernel rows found in {raw_csv}")
        kernel_count = min(max(args.kernel_count, 1), len(raw_df))

        build_wide_ncu_csv(raw_df, wide_csv, args.source_gpu)
        make_prepare_data_zip(args.source_gpu, wide_csv, raw_zip)
        run_prepare_data(perftools_root, raw_zip, args.source_gpu, kernel_count, prepared_csv)
        finalize_prepared_input(
            prepared_csv,
            raw_df,
            out_csv,
            allowed_nan=ALLOWED_NAN_COLUMNS | set(args.allow_nan),
            target_gpu=args.target_gpu,
            source_wide=pd.read_csv(wide_csv),
        )
        sidecar = Path(str(out_csv) + ".preprocessing.json")
        details = json.loads(sidecar.read_text())
        details["parameters"] = {"source_gpu": args.source_gpu, "target_gpu": args.target_gpu,
                                 "kernel_count": kernel_count, "allowed_nan": sorted(ALLOWED_NAN_COLUMNS | set(args.allow_nan))}
        sidecar.write_text(json.dumps(details, sort_keys=True) + "\n")
        final_count = len(pd.read_csv(out_csv))
        print(f"wrote {out_csv}: {final_count} kernels")
    finally:
        if work_dir_owned and not args.keep_work:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
