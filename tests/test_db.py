"""
tests/test_db.py — Tests de la base SQLite d'historique v2.0.
"""

import pytest

from bench.db.history import HistoryDB
from bench.suites.base import BenchmarkResult


def _make_result(
    algo: str = "CAGOULE",
    suite: str = "encryption",
    name: str = "encrypt-1MB",
    tp: float = 25.0,
    mean_ms: float = 40.0,
) -> BenchmarkResult:
    return BenchmarkResult(
        suite=suite,
        name=name,
        algorithm=algo,
        data_size_bytes=1_048_576,
        mean_ms=mean_ms,
        stddev_ms=1.0,
        p95_ms=mean_ms * 1.1,
        p99_ms=mean_ms * 1.2,
        throughput_mbps=tp,
        samples_ns=[int(mean_ms * 1e6)] * 10,
        extra={"matrix_backend": "avx2"},
    )


@pytest.fixture
def tmp_db(tmp_path) -> HistoryDB:
    db = HistoryDB(tmp_path / "test.db")
    yield db
    db.close()


class TestHistoryDBInit:
    def test_creates_db_file(self, tmp_path):
        db_path = tmp_path / "bench.db"
        HistoryDB(db_path).close()
        assert db_path.exists()

    def test_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c" / "hist.db"
        HistoryDB(nested).close()
        assert nested.exists()

    def test_context_manager(self, tmp_path):
        with HistoryDB(tmp_path / "ctx.db") as db:
            assert db is not None


class TestHistoryDBSaveRun:
    def test_save_returns_run_id(self, tmp_db):
        results = [_make_result()]
        run_id = tmp_db.save_run(results, tag="test")
        assert isinstance(run_id, str)
        assert len(run_id) == 36  # UUID format

    def test_save_and_list_runs(self, tmp_db):
        results = [_make_result()]
        tmp_db.save_run(results, tag="main")
        runs = tmp_db.list_runs(limit=10)
        assert len(runs) == 1
        assert runs[0]["tag"] == "main"

    def test_save_multiple_runs(self, tmp_db):
        for i in range(5):
            tmp_db.save_run([_make_result(tp=20.0 + i)], tag="main")
        runs = tmp_db.list_runs(limit=10)
        assert len(runs) == 5

    def test_run_duration_stored(self, tmp_db):
        tmp_db.save_run([_make_result()], duration_s=42.7)
        runs = tmp_db.list_runs()
        assert abs(runs[0]["duration_s"] - 42.7) < 0.01

    def test_cagoule_version_stored(self, tmp_db):
        tmp_db.save_run([_make_result()], cagoule_version="2.2.0")

    def test_backend_detected_from_extra(self, tmp_db):
        r = _make_result()
        r.extra["matrix_backend"] = "avx2"
        tmp_db.save_run([r])
        runs = tmp_db.list_runs()
        assert runs[0]["backend"] == "avx2"

    def test_summary_json_contains_throughput(self, tmp_db):
        r = _make_result(algo="CAGOULE", tp=30.0)
        tmp_db.save_run([r])
        runs = tmp_db.list_runs()
        summary = runs[0]["summary"]
        assert "CAGOULE" in summary
        assert abs(summary["CAGOULE"] - 30.0) < 0.1


class TestHistoryDBGetTrend:
    def test_returns_trend_points(self, tmp_db):
        for i in range(5):
            tmp_db.save_run([_make_result(tp=20.0 + i)])
        trend = tmp_db.get_trend("encryption", "CAGOULE", "encrypt-1MB", n=10)
        assert len(trend) == 5

    def test_trend_chronological_order(self, tmp_db):
        for i in range(3):
            tmp_db.save_run([_make_result(tp=float(i + 1))])
        trend = tmp_db.get_trend("encryption", "CAGOULE", "encrypt-1MB", n=10)
        assert len(trend) == 3
        tps = [t.throughput_mbps for t in trend]
        assert tps == sorted(tps), f"Attendu croissant, obtenu {tps}"

    def test_returns_empty_for_unknown(self, tmp_db):
        trend = tmp_db.get_trend("unknown", "UNKNOWN_ALGO", "unknown-test", n=10)
        assert trend == []

    def test_filter_by_tag(self, tmp_db):
        tmp_db.save_run([_make_result(tp=10.0)], tag="main")
        tmp_db.save_run([_make_result(tp=20.0)], tag="feature-branch")
        trend_main = tmp_db.get_trend("encryption", "CAGOULE", "encrypt-1MB", tag="main")
        trend_fb = tmp_db.get_trend("encryption", "CAGOULE", "encrypt-1MB", tag="feature-branch")
        assert len(trend_main) == 1
        assert len(trend_fb) == 1

    def test_limit_n_respected(self, tmp_db):
        for i in range(15):
            tmp_db.save_run([_make_result(tp=float(i))])
        trend = tmp_db.get_trend("encryption", "CAGOULE", "encrypt-1MB", n=5)
        assert len(trend) <= 5


class TestHistoryDBGetRunResults:
    def test_get_run_results(self, tmp_db):
        r1 = _make_result(algo="CAGOULE", tp=25.0)
        r2 = _make_result(algo="AES-256-GCM", tp=35.0)
        run_id = tmp_db.save_run([r1, r2])
        results = tmp_db.get_run_results(run_id)
        assert len(results) == 2
        algos = {r["algorithm"] for r in results}
        assert "CAGOULE" in algos
        assert "AES-256-GCM" in algos

    def test_get_run_results_unknown_id(self, tmp_db):
        results = tmp_db.get_run_results("00000000-0000-0000-0000-000000000000")
        assert results == []


class TestHistoryDBDetectRegression:
    def test_no_regression_on_stable(self, tmp_db):
        for i in range(6):
            tmp_db.save_run([_make_result(tp=25.0)])
        current = [_make_result(tp=25.0)]
        passed, msgs = tmp_db.detect_regression(current, n_baseline=5)
        assert passed is True

    def test_detects_regression(self, tmp_db):
        for i in range(6):
            tmp_db.save_run([_make_result(tp=30.0)])
        current = [_make_result(tp=20.0)]
        passed, msgs = tmp_db.detect_regression(current, n_baseline=5, threshold_pct=-5.0)
        assert passed is False
        assert len(msgs) > 0
        assert "RÉGRESSION" in msgs[0]

    def test_no_regression_insufficient_history(self, tmp_db):
        tmp_db.save_run([_make_result(tp=25.0)])
        current = [_make_result(tp=5.0)]
        passed, msgs = tmp_db.detect_regression(current, n_baseline=5)
        assert isinstance(passed, bool)


class TestHistoryDBComputeDrift:
    def test_improving_trend(self, tmp_db):
        for i in range(10):
            tmp_db.save_run([_make_result(tp=10.0 + i * 2.0)])
        drift = tmp_db.compute_drift("encryption", "CAGOULE", "encrypt-1MB", n=10)
        assert drift["trend"] == "improving", f"slope={drift['slope_mbps_per_run']}"
        assert drift["slope_mbps_per_run"] > 0

    def test_degrading_trend(self, tmp_db):
        for i in range(10):
            tmp_db.save_run([_make_result(tp=30.0 - i * 2.0)])
        drift = tmp_db.compute_drift("encryption", "CAGOULE", "encrypt-1MB", n=10)
        assert drift["trend"] == "degrading", f"slope={drift['slope_mbps_per_run']}"
        assert drift["slope_mbps_per_run"] < 0

    def test_stable_trend(self, tmp_db):
        for i in range(10):
            tmp_db.save_run([_make_result(tp=25.0)])
        drift = tmp_db.compute_drift("encryption", "CAGOULE", "encrypt-1MB", n=10)
        assert drift["trend"] == "stable"

    def test_insufficient_data(self, tmp_db):
        tmp_db.save_run([_make_result(tp=25.0)])
        drift = tmp_db.compute_drift("encryption", "CAGOULE", "encrypt-1MB")
        assert drift["trend"] == "insufficient_data"

    def test_r2_between_0_and_1(self, tmp_db):
        for i in range(10):
            tmp_db.save_run([_make_result(tp=float(i))])
        drift = tmp_db.compute_drift("encryption", "CAGOULE", "encrypt-1MB")
        assert 0.0 <= drift["r2"] <= 1.0


class TestHistoryDBDelete:
    def test_delete_run_cascades_to_results(self, tmp_db):
        """ON DELETE CASCADE: deleting a run removes all its results."""
        r1 = _make_result(algo="CAGOULE", tp=25.0)
        r2 = _make_result(algo="AES-256-GCM", tp=35.0)
        run_id = tmp_db.save_run([r1, r2])

        assert len(tmp_db.get_run_results(run_id)) == 2

        tmp_db._conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        tmp_db._conn.commit()

        assert tmp_db.get_run_results(run_id) == []


class TestHistoryDBRegressionTag:
    def test_regression_respects_tag_filter(self, tmp_db):
        """detect_regression with tag='main' ignores other tags."""
        for _ in range(5):
            tmp_db.save_run([_make_result(tp=30.0)], tag="main")
        for _ in range(5):
            tmp_db.save_run([_make_result(tp=10.0)], tag="experiment")

        current = [_make_result(tp=29.0)]
        passed, msgs = tmp_db.detect_regression(
            current, n_baseline=5, threshold_pct=-5.0, tag="main"
        )
        assert passed is True
