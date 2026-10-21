#!/usr/bin/env python3
"""Project a measured GPU section with the current PerfTools neural models.

One invocation per observed launch preserves configurations which the upstream
input generator would otherwise collapse by kernel name. All outputs stay in a
private attempt directory; the external model checkout is read-only.
"""
from __future__ import annotations

import argparse
import csv
import io
from importlib.metadata import version as distribution_version
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile

from perftools_provenance import digest, make_manifest

MODELS = {
    "mlp455": ("MLP_NN", "mlp-nn.py", "v4.55", "gpu_kernel_mlp_v455", "MLP-NN"),
    "pinn325": ("PINN", "pinn.py", "v3.25", "gpu_kernel_pinn_v325", "PINN"),
}
RATIO_BASIS = "predicted_target_over_predicted_source"
METRICS = ["Memory Throughput [%]", "Achieved Occupancy", "brk_memory",
           "brk_pipeline_contention", "brk_sync", "brk_scheduling_overhead",
           "running_cycles", "issue_limited", "trust_w"]


def positive(value, label):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be finite and positive")
    return number


def read_archive(path, out, source_gpu):
    import pandas as pd
    from prepare_gpu_mlp_ncu_input import build_wide_ncu_csv
    # Read just a regular CSV member, without extracting paths or links.
    with tarfile.open(path, "r:gz") as archive:
        members = [m for m in archive.getmembers()
                   if m.isfile() and Path(m.name).name == "profile_raw.csv"]
        if len(members) != 1:
            raise ValueError("NCU archive must contain exactly one profile_raw.csv")
        with archive.extractfile(members[0]) as stream:
            lines = stream.read().decode("utf-8-sig", errors="replace").splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith('"ID","Process ID"')), None)
    if start is None:
        raise ValueError("NCU raw CSV header is missing")
    raw = pd.read_csv(io.StringIO("\n".join(lines[start:])), low_memory=False)
    raw = raw.loc[raw["Kernel Name"].notna()].copy()
    build_wide_ncu_csv(raw, out, source_gpu)
    return pd.read_csv(out, low_memory=False)


def normalize(frame):
    from prepare_gpu_lightgbm_ncu_input import normalize_lightgbm_columns
    from prepare_gpu_mlp_ncu_input import observed_numeric
    from run_gpu_lightgbm_v11 import normalize as normalize_aliases
    frame, _ = normalize_aliases(normalize_lightgbm_columns(frame))
    for label, raw in [("L1/TEX Hit Rate [%]", "l1tex__t_sector_hit_rate.pct"),
                       ("L2 Hit Rate [%]", "lts__t_sector_hit_rate.pct"),
                       ("Issued Instructions [inst]", "smsp__inst_issued.sum"),
                       ("Executed Instructions [inst]", "smsp__inst_executed.sum")]:
        frame[label] = observed_numeric(frame, label, raw)
    return frame


def choose_kernels(frame, item, name="", regex=""):
    if not name and not regex:
        name = item.get("kernel_name", item.get("gpu_kernel_name", ""))
        regex = item.get("kernel_regex", item.get("gpu_kernel_regex", ""))
    if regex:
        frame = frame.loc[frame["Kernel Name"].astype(str).map(lambda x: re.search(regex, x) is not None)]
    elif name:
        frame = frame.loc[frame["Kernel Name"] == name]
    if frame.empty or frame["Kernel Name"].nunique() != 1:
        raise ValueError("A section requires one selected kernel name (with any launch configurations)")
    return frame


def prediction_pair(rows, kernel, source, target):
    """Match identities within a single-launch invocation, never by output order."""
    expected = {source, target}
    identities = [(r["kernel_name"], r["src_gpu"], r["tgt_gpu"]) for r in rows]
    if len(rows) != len(expected) or len(set(identities)) != len(rows):
        raise ValueError("Duplicate or missing self/target prediction rows")
    if any(r["kernel_name"] != kernel or r["src_gpu"] != source for r in rows):
        raise ValueError("Prediction identity does not match the observed launch")
    if {r["tgt_gpu"] for r in rows} != expected:
        raise ValueError("Prediction GPU identities do not match the requested pair")
    return {r["tgt_gpu"]: r for r in rows}


def aggregate(rows):
    observed = sum(r["source_time_ns"] for r in rows)
    self_time = sum(r["self_predicted_time_ns"] for r in rows)
    target = sum(r["predicted_time_ns"] for r in rows)
    return {"total_source_time_ns": observed, "total_source_time": observed / 1e9,
            "total_self_predicted_time_ns": self_time, "total_predicted_time_ns": target,
            "time_ratio_basis": RATIO_BASIS,
            "time_ratio_predicted_over_source": target / self_time,
            "time_ratio_predicted_over_observed_source": target / observed,
            "self_prediction_over_observed_source": self_time / observed,
            "self_prediction_error_percent": (self_time / observed - 1) * 100}


def group_samples(rows):
    """Use configuration means/counts for cross-package diagnostic alignment."""
    groups = {}
    for row in rows:
        config = row["configuration"]
        groups.setdefault((row["name"], config["grid_size"], config["block_size"]), []).append(row)
    output = []
    for key, samples in sorted(groups.items()):
        n = len(samples)
        observed = sum(r["source_time_ns"] for r in samples) / n
        self_time = sum(r["self_predicted_time_ns"] for r in samples) / n
        target = sum(r["predicted_time_ns"] for r in samples) / n
        values = {k: [r["metrics"][k] for r in samples if k in r["metrics"]] for k in METRICS}
        output.append({"name": key[0], "configuration": {"grid_size": key[1], "block_size": key[2]},
                       "sample_count": n, "source_gpu": samples[0]["source_gpu"],
                       "target_gpu": samples[0]["target_gpu"],
                       "profile_process_id": samples[0]["profile_process_id"], "mpi_rank": None,
                       "source_time_ns": observed, "source_time": observed / 1e9,
                       "self_predicted_time_ns": self_time, "predicted_time_ns": target,
                       "predicted_time": target / 1e9, "time_ratio_basis": RATIO_BASIS,
                       "time_ratio_predicted_over_source": target / self_time,
                       "time_ratio_predicted_over_observed_source": target / observed,
                       "self_prediction_over_observed_source": self_time / observed,
                       "metrics": {k: sum(v) / len(v) for k, v in values.items() if v}})
    return output


def invoke(argv, root, env, log):
    with log.open("a") as stream:
        subprocess.run([sys.executable, *map(str, argv)], cwd=root, env=env,
                       stdout=stream, stderr=subprocess.STDOUT, check=True)


def run(args, item):
    import pandas as pd
    from run_gpu_lightgbm_v11 import select_process
    family, entry, release, package, label = MODELS[args.model]
    root = Path(args.root).resolve()
    section_time = positive(item.get("time", item.get("bench_time")), "source section time")
    base = Path(args.output_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=base))
    log = attempt / "inference.log"
    if args.padata:
        frame = read_archive(args.padata, attempt / "converted.csv", args.source_gpu)
        mode, original = "ncu_archive", Path(args.padata)
    else:
        frame = pd.read_csv(args.wide_csv, low_memory=False)
        mode, original = "wide_ncu_csv", Path(args.wide_csv)
    if "Kernel Name" not in frame or "Metric Name" in frame:
        raise ValueError("A wide per-launch NCU CSV is required")
    selected, sampling = select_process(frame, args.profile_process_id)
    selected = choose_kernels(normalize(selected), item, args.kernel_name, args.kernel_regex)
    for column in ["Grid Size", "Block Size", "Duration [ns]"]:
        selected[column] = [positive(v, column) for v in selected[column]]
    selected_path = attempt / "selected.csv"
    selected.to_csv(selected_path, index=False)
    sampling.update({"selected_rows": len(selected), "scope": "representative_process_sample",
                     "launch_weighting": "observed_sample_count", "representativeness_verified": False})
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
               GPU_SPEC_SHEET=str(root / "data/v4/gpu_microarch_specs.csv"))
    # Both invocations use the same model release and its runtime inputs.
    rows, files = [], []
    for ordinal, (_, row) in enumerate(selected.iterrows()):
        launch = attempt / f"launch-{ordinal}"
        launch.mkdir()
        wide, prepared, prediction = [launch / n for n in ("observed.csv", "input.csv", "prediction.csv")]
        pd.DataFrame([row]).to_csv(wide, index=False)
        invoke([root / "examples/kernel_inputs/prepare_data.py", "--ncu", wide,
                "--src", args.source_gpu, "--tgt", ",".join(dict.fromkeys([args.target_gpu, args.source_gpu])),
                "--model-dir", root / family, "--weights-dir", root / family / release,
                "--out", prepared], root, env, log)
        inp = pd.read_csv(prepared)
        if (len(inp) != len({args.source_gpu, args.target_gpu})
                or not inp["src_gpu"].eq(args.source_gpu).all()
                or set(inp["tgt_gpu"]) != {args.source_gpu, args.target_gpu}
                or not inp["Kernel Name"].eq(row["Kernel Name"]).all()
                or not inp["Grid Size"].eq(row["Grid Size"]).all()
                or not inp["Block Size"].eq(row["Block Size"]).all()
                or not inp["Execution Time"].eq(row["Duration [ns]"]).all()):
            raise ValueError("Generated model inputs do not match the observed launch")
        invoke([root / family / entry, "--artifact", root / family / release,
                "--csv", prepared, "--row", "all", "--no-comments", "--out", prediction], root, env, log)
        with prediction.open(newline="") as stream:
            pair = prediction_pair(list(csv.DictReader(stream)), str(row["Kernel Name"]), args.source_gpu, args.target_gpu)
        target = positive(pair[args.target_gpu]["Execution Time [ns]"], "target prediction")
        self_time = positive(pair[args.source_gpu]["Execution Time [ns]"], "self prediction")
        observed = positive(row["Duration [ns]"], "observed time")
        metrics = {k: float(pair[args.target_gpu][k]) for k in METRICS
                   if k in pair[args.target_gpu] and pair[args.target_gpu][k] not in ("", None)
                   and math.isfinite(float(pair[args.target_gpu][k]))}
        rows.append({"name": str(row["Kernel Name"]), "sample_ordinal": ordinal,
                     "profile_launch_id": str(row.get("ID", ordinal)),
                     "profile_process_id": sampling["process_id"], "mpi_rank": None,
                     "configuration": {"grid_size": float(row["Grid Size"]), "block_size": float(row["Block Size"])},
                     "source_gpu": args.source_gpu, "target_gpu": args.target_gpu,
                     "source_time_ns": observed, "source_time": observed / 1e9,
                     "self_predicted_time_ns": self_time, "predicted_time_ns": target,
                     "predicted_time": target / 1e9, "time_ratio_basis": RATIO_BASIS,
                     "time_ratio_predicted_over_source": target / self_time,
                     "time_ratio_predicted_over_observed_source": target / observed,
                     "self_prediction_over_observed_source": self_time / observed, "metrics": metrics})
        for role, path in [("observed_launch", wide), ("prepared_input", prepared), ("prediction", prediction)]:
            files.append({"role": role, "sample_ordinal": ordinal, "path": str(path), "sha256": digest(path),
                          **({"missing_generated_columns": inp.columns[inp.isna().any()].tolist()}
                             if role == "prepared_input" else {})})
    metrics = aggregate(rows)
    grouped = group_samples(rows)
    metrics.update({"kernel_count": len(grouped), "unique_kernel_count": 1,
                    "kernel_names": [rows[0]["name"]], "matched_kernels": grouped, "kernels": grouped,
                    "observed_launches": rows,
                    "source_gpus": [args.source_gpu], "target_gpus": [args.target_gpu], "sampling": sampling,
                    "configuration_count": len(selected[["Kernel Name", "Grid Size", "Block Size"]].drop_duplicates()),
                    "sample_predicted_time": metrics["total_predicted_time_ns"] / 1e9,
                    "section_time_ratio_predicted_over_source": metrics["time_ratio_predicted_over_source"]})
    result_file = attempt / "sample-summary.json"
    result_file.write_text(json.dumps(metrics, indent=2, allow_nan=False) + "\n")
    manifest = make_manifest(str(root), args.model, entry, mode, str(selected_path), str(result_file),
                             args.requested_ref, args.pin, args.source_gpu, args.target_gpu)
    manifest["inputs"].append({"role": "source_artifact", "sha256": digest(original)})
    manifest["inputs"].extend(files)
    manifest["adapter"] = {"path": "scripts/estimation/run_gpu_neural.py", "sha256": digest(Path(__file__)),
                           "sampling": sampling, "aggregation": RATIO_BASIS,
                           "input_generation": "one_observed_launch_per_invocation"}
    manifest["model"] = {"family": label, "requested_version": release, "applied_version": release,
                         "weights_directory": f"{family}/{release}"}
    # Record only model tuning variables, never arbitrary environment contents.
    tuning = ["ET_INPUT", "SCALE_INVARIANT", "COMP_CAP", "AT_BUSY_SMS", "AXIS_TRANSPORT", "TRUST_Z", "TRUST_MODE",
              "TRUST_CAP_MARGIN", "TRUST_CAP_AXES", "AT_REFCAP", "AT_HELDOUT_REF", "AT_HELDOUT_CAP", "AT_MEM",
              "AT_COMP_SAT", "AT_CLAMP", "ISSUE_FLOOR", "BUSY_FEAT_CLIP", "BUSY_FEAT_FLOOR", "LAT_CLOCK"]
    manifest["runtime_versions"] = {"python": sys.version.split()[0],
                                    **{name: distribution_version(name) for name in ("numpy", "pandas", "torch")}}
    manifest["model_environment_overrides"] = {k: os.environ[k] for k in tuning if k in os.environ}
    contents = json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n"
    manifest_path = attempt / "provenance.json"
    manifest_path.write_text(contents)
    provenance = {"manifest": str(manifest_path), "sha256": digest(manifest_path), "input_mode": mode,
                  "external_commit": manifest["external_inference"]["resolved_commit"]}
    metrics["app_gpu_section_time"] = section_time
    item = dict(item, time=section_time * metrics["time_ratio_predicted_over_source"], bench_time=section_time,
                estimation_package=package, scaling_method=f"gpu-kernel-{args.model}-self-normalized", metrics=metrics,
                package_applicability={"status": "applicable", "missing_inputs": []},
                model={"type": "cross_gpu_kernel_prediction_model", "name": f"PerfTools {label}",
                       "version": release, "requested_version": release, "applied_version": release,
                       "provenance": provenance})
    # A previous attempt's fallback is not evidence about this successful run.
    item.pop("fallback_used", None)
    item["artifacts"] = [*item.get("artifacts", []),
                         {"kind": "external_model_provenance", "path": str(manifest_path)},
                         {"kind": "gpu_neural_sample_summary", "path": str(result_file)},
                         {"kind": "gpu_neural_input_csv", "path": str(selected_path)},
                         {"kind": "gpu_neural_log", "path": str(log)},
                         *[{"kind": "gpu_neural_" + f["role"], "path": f["path"]} for f in files]]
    return item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ["root", "source-gpu", "target-gpu", "output-dir"]:
        parser.add_argument("--" + arg, required=True)
    parser.add_argument("--model", choices=MODELS, required=True)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--padata")
    inputs.add_argument("--wide-csv")
    for arg in ["profile-process-id", "kernel-name", "kernel-regex", "requested-ref", "pin"]:
        parser.add_argument("--" + arg, default="")
    args = parser.parse_args()
    print(json.dumps(run(args, json.load(sys.stdin)), allow_nan=False))


if __name__ == "__main__":
    main()
