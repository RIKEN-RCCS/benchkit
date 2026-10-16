"""CPU-only tests for the opt-in PerfTools bridge; no model download required."""
import importlib.util
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")
spec = importlib.util.spec_from_file_location(
    "lightgbm_v11_adapter", Path(__file__).resolve().parents[2] / "scripts/estimation/run_gpu_lightgbm_v11.py")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def test_alias_collision_preserves_canonical_and_fills_partial_values():
    frame = pd.DataFrame({"Achieved Occupancy": [12., np.nan, 30.],
                          "Achieved Occupancy [%]": [12., 20., 99.]})
    output, notes = adapter.normalize(frame)
    assert output.columns.tolist() == ["Achieved Occupancy"]
    assert output.iloc[:, 0].tolist() == [12., 20., 30.]
    assert notes[0]["conflicting_rows"] == 1
    assert frame["Achieved Occupancy"].isna().sum() == 1


def evidence():
    features = pd.DataFrame({"meta-kernel": ["same", "same"], "meta-src_gpu": ["GB200"] * 2,
                             "meta-tgt_gpu": ["H100"] * 2,
                             "I-derived::src_raw_exec_time_ns": [200., 900.],
                             "I-kcfg::Grid Size": [10, 20], "I-kcfg::Block Size": [128, 256],
                             "I-wl::Achieved Occupancy": [30., 40.]})
    predictions = features[["meta-kernel", "meta-src_gpu", "meta-tgt_gpu"]].copy()
    predictions["O-Execution Time"] = [400., 2700.]
    return features, predictions


def test_grouped_times_and_configuration_are_kept_with_prediction():
    features, predictions = evidence()
    result = adapter.align(features, predictions)
    assert result["benchkit-source-time-ns"].tolist() == [200., 900.]
    assert result["benchkit-block-size"].tolist() == [128, 256]
    assert result["benchkit-source::O-Achieved Occupancy"].tolist() == [30., 40.]


@pytest.mark.parametrize("value", [np.nan, np.inf, 0., -1.])
def test_invalid_source_time_rejected(value):
    features, predictions = evidence()
    features.loc[0, "I-derived::src_raw_exec_time_ns"] = value
    with pytest.raises(ValueError, match="source execution time"):
        adapter.align(features, predictions)


@pytest.mark.parametrize("kind", ["row_count", "identity", "configuration", "prediction"])
def test_incomplete_or_mismatched_evidence_rejected(kind):
    features, predictions = evidence()
    if kind == "row_count":
        predictions = predictions.iloc[:1]
    elif kind == "identity":
        predictions.loc[0, "meta-kernel"] = "different"
    elif kind == "configuration":
        features.loc[0, "I-kcfg::Grid Size"] = np.nan
    else:
        predictions.loc[0, "O-Execution Time"] = np.nan
    with pytest.raises(ValueError):
        adapter.align(features, predictions)


def test_failed_attempt_discards_previous_aligned_prediction(tmp_path, monkeypatch):
    source = tmp_path / 'long.csv'
    pd.DataFrame({'Kernel Name': ['kernel'], 'Metric Name': ['Duration']}).to_csv(source, index=False)
    output = tmp_path / 'prediction.csv'
    output.write_text('stale successful prediction')
    monkeypatch.setattr(adapter.sys, 'argv', ['adapter', '--model-dir', str(tmp_path),
                        '--src_gpu', 'GB200', '--tgt_gpu', 'H100', '--ncu_csv', str(source),
                        '--out', str(output), '--log', str(tmp_path / 'log')])
    with pytest.raises(ValueError, match='wide NCU CSV'):
        adapter.main()
    assert not output.exists()
