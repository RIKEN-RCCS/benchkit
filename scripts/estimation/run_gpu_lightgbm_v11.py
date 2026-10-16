#!/usr/bin/env python3
"""Run PerfTools 1.1 and preserve its grouped features alongside predictions.

This adapter does not supply missing GPU specifications or replace NaN values.
The upstream CLI must run in a private model copy (it writes fixed filenames).
"""
from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

ALIASES = {
    "Achieved Occupancy [%]": "Achieved Occupancy",
    "Warp Cycles Per Executed Instruction [cycle]": "Warp Cycles Per Executed Instruction [cycle/inst]",
}
SOURCE_SPECS = [
    "GPU Maximum Warps Per Scheduler [warp]", "Theoretical Active Warps Per Scheduler [warp]",
    "Theoretical Active Warps per SM [warp]", "Block Limit Warps [block]",
    "Block Limit Barriers [block]", "Max Cluster Size [block]",
    "Shared Memory Configuration Size [byte]",
]
METRICS = {
    "O-Memory Throughput [%]": "I-wl::Memory Throughput [%]",
    "O-Achieved Occupancy": "I-wl::Achieved Occupancy",
    "O-breakdown_memory": "I-wl::src_brk_memory",
    "O-breakdown_pipeline_contention": "I-wl::src_brk_pipeline_contention",
    "O-breakdown_sync": "I-wl::src_brk_sync",
    "O-breakdown_scheduling_overhead": "I-wl::src_brk_scheduling_overhead",
}


class DataOnly(pickle.Unpickler):
    def find_class(self, module, name):
        raise ValueError("Unexpected executable feature metadata")


def normalize(frame):
    """Prefer an observed canonical value; use an alias only where it is absent."""
    frame = frame.copy()
    notes = []
    for alias, canonical in ALIASES.items():
        if alias not in frame:
            continue
        if canonical in frame:
            left = pd.to_numeric(frame[canonical], errors="coerce")
            right = pd.to_numeric(frame[alias], errors="coerce")
            conflicts = left.notna() & right.notna() & ~np.isclose(left, right)
            notes.append({"alias": alias, "canonical": canonical,
                          "conflicting_rows": int(conflicts.sum()), "canonical_preferred": True})
            frame[canonical] = left.combine_first(right)
        else:
            frame[canonical] = frame[alias]
        frame = frame.drop(columns=[alias])
    return frame, notes


def align(features, prediction):
    """Both files come from the same upstream invocation and retain its row order."""
    keys = ["meta-kernel", "meta-src_gpu", "meta-tgt_gpu"]
    if len(features) != len(prediction) or not features[keys].equals(prediction[keys]):
        raise ValueError("Upstream prediction rows do not match their inference features")
    times = pd.to_numeric(features["I-derived::src_raw_exec_time_ns"], errors="coerce")
    if not (np.isfinite(times) & (times > 0)).all():
        raise ValueError("Missing or invalid grouped source execution time")
    predicted = pd.to_numeric(prediction["O-Execution Time"], errors="coerce")
    if not (np.isfinite(predicted) & (predicted >= 0)).all():
        raise ValueError("Missing or invalid predicted execution time")
    prediction = prediction.copy()
    prediction["benchkit-source-time-ns"] = times
    for source, target in [("I-kcfg::Grid Size", "benchkit-grid-size"),
                           ("I-kcfg::Block Size", "benchkit-block-size")]:
        if source not in features or features[source].isna().any():
            raise ValueError("Configuration columns are required for grouped inference")
        prediction[target] = features[source]
    for target, source in METRICS.items():
        if source in features:
            prediction["benchkit-source::" + target] = features[source]
    return prediction


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ["model-dir", "src_gpu", "tgt_gpu", "ncu_csv", "out", "log"]:
        parser.add_argument("--" + arg, required=True)
    args = parser.parse_args()
    model = Path(args.model_dir).resolve()
    output = Path(args.out).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # An unsuccessful attempt must never leave an older aligned prediction usable.
    output.unlink(missing_ok=True)
    frame = pd.read_csv(args.ncu_csv)
    if "Kernel Name" not in frame or "Metric Name" in frame:
        raise ValueError("The v1.1 adapter requires a wide NCU CSV")
    normalized, aliases = normalize(frame)
    input_path = Path(str(output) + ".input.csv")
    normalized.to_csv(input_path, index=False)
    raw_prediction = model / "benchkit_prediction.csv"
    subprocess.run([sys.executable, str(model / "AI_model/run_inference.py"),
                    "--src_gpu", args.src_gpu, "--tgt_gpu", args.tgt_gpu,
                    "--ncu_csv", str(input_path), "--out", str(raw_prediction),
                    "--log", str(Path(args.log).resolve()), "--group_by_config"],
                   cwd=model, check=True)
    features = pd.read_csv(model / "extracted_features.csv")
    features.to_csv(str(output) + ".features.csv", index=False)
    with (model / "AI_model/model/feature_names.pkl").open("rb") as stream:
        expected = DataOnly(stream).load()
    with (model / "AI_model/model/clean_map.pkl").open("rb") as stream:
        reverse = {value: key for key, value in DataOnly(stream).load().items()}
    columns = [reverse.get(key, key) for key in expected]
    validation = {
        "model_version": "1.1", "group_by_config": True, "input_rows": len(frame),
        "aggregation": "mean_per_kernel_grid_block", "launch_weighting": "not_applied",
        "configuration_rows": len(features), "aliases": aliases,
        "missing_model_columns": [c for c in columns if c not in features],
        "nan_model_columns": {c: int(features[c].isna().sum()) for c in columns
                              if c in features and features[c].isna().any()},
        "upstream_defaulted_source_columns": [c for c in SOURCE_SPECS if c not in normalized],
    }
    Path(str(output) + ".validation.json").write_text(json.dumps(validation, indent=2) + "\n")
    aligned = align(features, pd.read_csv(raw_prediction))
    aligned.to_csv(output, index=False)


if __name__ == "__main__":
    main()
