"""
bench/db/history.py — Historique SQLite des benchmarks.

Stocke chaque run dans une base SQLite locale pour :
  - Suivi de tendance (trend detection sur N derniers runs)
  - Comparaison automatique avec le dernier run en CI
  - Génération de graphiques de progression
  - Détecter les régressions progressives (drift silencieux)

La base est initialisée automatiquement à l'instanciation.
Aucune dépendance externe : stdlib sqlite3 uniquement.

Usage:
    db = HistoryDB(".cagoule_bench/history.db")
    db.save_run(results, tag="main")
    trend = db.get_trend("encryption", "CAGOULE", "encrypt-1MB", n=10)
"""

from __future__ import annotations

import json
import platform
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bench.suites.base import BenchmarkResult

# Schema version — bump when changing the DB structure
SCHEMA_VERSION = 2


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class RunRecord:
    """Enregistrement d'un run complet dans l'historique."""
    run_id: str
    tag: str          # ex: "main", "avx2-branch", "pr-42"
    timestamp: str
    platform: str
    arch: str
    python_version: str
    cagoule_version: str
    cagoule_backend: str   # "avx2" | "scalar" | "mock"
    result_count: int
    duration_s: float
    summary_json: str      # JSON summary des throughputs


@dataclass
class TrendPoint:
    """Point de tendance pour un benchmark spécifique."""
    run_id: str
    timestamp: str
    tag: str
    mean_ms: float
    throughput_mbps: float
    stddev_ms: float
    p95_ms: float


# ── HistoryDB ─────────────────────────────────────────────────────────────────

class HistoryDB:
    """
    Base SQLite locale pour l'historique des benchmarks.

    Usage typique :
        db = HistoryDB(".cagoule_bench/history.db")
        run_id = db.save_run(results, tag="main", duration_s=45.2)
        trend = db.get_trend("encryption", "CAGOULE", "encrypt-1MB", n=20)
        regression = db.detect_regression(results, n_baseline=5, threshold_pct=-5.0)
    """

    def __init__(self, db_path: str | Path = ".cagoule_bench/history.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        c = self._conn.cursor()
        c.executescript(f"""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runs (
                run_id        TEXT PRIMARY KEY,
                tag           TEXT NOT NULL DEFAULT 'default',
                timestamp     TEXT NOT NULL,
                platform      TEXT,
                arch          TEXT,
                python_version TEXT,
                cagoule_version TEXT,
                cagoule_backend TEXT,
                result_count  INTEGER,
                duration_s    REAL,
                summary_json  TEXT
            );

            CREATE TABLE IF NOT EXISTS results (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id        TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                suite         TEXT NOT NULL,
                name          TEXT NOT NULL,
                algorithm     TEXT NOT NULL,
                data_size_bytes INTEGER,
                mean_ms       REAL,
                stddev_ms     REAL,
                p95_ms        REAL,
                p99_ms        REAL,
                cv_percent    REAL,
                throughput_mbps REAL,
                peak_mb       REAL,
                cpu_mean_pct  REAL,
                extra_json    TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_results_suite_name_algo
                ON results(suite, name, algorithm);
            CREATE INDEX IF NOT EXISTS idx_runs_timestamp
                ON runs(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_runs_tag
                ON runs(tag);
        """)
        self._conn.commit()

    # ── Write ─────────────────────────────────────────────────────────────────

    def save_run(
        self,
        results: list[BenchmarkResult],
        tag: str = "default",
        duration_s: float = 0.0,
        cagoule_version: str = "unknown",
    ) -> str:
        """
        Sauvegarde un run complet dans la DB.

        Returns:
            run_id (UUID string) pour référence future
        """
        run_id = str(uuid.uuid4())
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Détection backend CAGOULE
        backend = "mock"
        for r in results:
            if "matrix_backend" in r.extra:
                backend = r.extra["matrix_backend"]
                break

        # Summary: throughput moyen par algorithme
        by_algo: dict[str, list[float]] = {}
        for r in results:
            if r.throughput_mbps > 0:
                by_algo.setdefault(r.algorithm, []).append(r.throughput_mbps)
        summary = {
            algo: round(sum(tps) / len(tps), 2)
            for algo, tps in by_algo.items()
        }

        c = self._conn.cursor()
        c.execute("""
            INSERT INTO runs
              (run_id, tag, timestamp, platform, arch, python_version,
               cagoule_version, cagoule_backend, result_count, duration_s, summary_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id, tag, ts,
            platform.system() + "/" + platform.machine(),
            platform.machine(),
            platform.python_version(),
            cagoule_version,
            backend,
            len(results),
            round(duration_s, 3),
            json.dumps(summary),
        ))

        c.executemany("""
            INSERT INTO results
              (run_id, suite, name, algorithm, data_size_bytes,
               mean_ms, stddev_ms, p95_ms, p99_ms, cv_percent,
               throughput_mbps, peak_mb, cpu_mean_pct, extra_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                run_id,
                r.suite, r.name, r.algorithm, r.data_size_bytes,
                round(r.mean_ms, 4), round(r.stddev_ms, 4),
                round(r.p95_ms, 4), round(r.p99_ms, 4), round(r.cv_percent, 2),
                round(r.throughput_mbps, 3), round(r.peak_mb, 4),
                round(r.cpu_mean_pct, 2),
                json.dumps(r.extra),
            )
            for r in results
        ])
        self._conn.commit()
        return run_id

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_trend(
        self,
        suite: str,
        algorithm: str,
        name: str,
        n: int = 20,
        tag: str | None = None,
    ) -> list[TrendPoint]:
        """
        Récupère les N derniers points d'un benchmark spécifique.

        Args:
            suite, algorithm, name: identifiant du benchmark
            n: nombre de points (défaut: 20)
            tag: filtrer par tag Git/branch (None = tous)

        Returns:
            list[TrendPoint] du plus ancien au plus récent
        """
        c = self._conn.cursor()
        if tag:
            rows = c.execute("""
                SELECT r.run_id, r.timestamp, r.tag,
                       res.mean_ms, res.throughput_mbps, res.stddev_ms, res.p95_ms
                FROM results res
                JOIN runs r USING (run_id)
                WHERE res.suite = ? AND res.algorithm = ? AND res.name = ?
                  AND r.tag = ?
                ORDER BY r.timestamp DESC, r.rowid DESC
                LIMIT ?
            """, (suite, algorithm, name, tag, n)).fetchall()
        else:
            rows = c.execute("""
                SELECT r.run_id, r.timestamp, r.tag,
                       res.mean_ms, res.throughput_mbps, res.stddev_ms, res.p95_ms
                FROM results res
                JOIN runs r USING (run_id)
                WHERE res.suite = ? AND res.algorithm = ? AND res.name = ?
                ORDER BY r.timestamp DESC, r.rowid DESC
                LIMIT ?
            """, (suite, algorithm, name, n)).fetchall()

        return [
            TrendPoint(
                run_id=row["run_id"],
                timestamp=row["timestamp"],
                tag=row["tag"],
                mean_ms=row["mean_ms"],
                throughput_mbps=row["throughput_mbps"],
                stddev_ms=row["stddev_ms"],
                p95_ms=row["p95_ms"],
            )
            for row in reversed(rows)  # chronologique
        ]

    def list_runs(self, limit: int = 20, tag: str | None = None) -> list[dict]:
        """Liste les N derniers runs (métadonnées uniquement)."""
        c = self._conn.cursor()
        if tag:
            rows = c.execute("""
                SELECT run_id, tag, timestamp, arch, cagoule_backend,
                       result_count, duration_s, summary_json
                FROM runs WHERE tag = ?
                ORDER BY timestamp DESC LIMIT ?
            """, (tag, limit)).fetchall()
        else:
            rows = c.execute("""
                SELECT run_id, tag, timestamp, arch, cagoule_backend,
                       result_count, duration_s, summary_json
                FROM runs
                ORDER BY timestamp DESC LIMIT ?
            """, (limit,)).fetchall()

        return [
            {
                "run_id": r["run_id"],
                "tag": r["tag"],
                "timestamp": r["timestamp"],
                "arch": r["arch"],
                "backend": r["cagoule_backend"],
                "results": r["result_count"],
                "duration_s": r["duration_s"],
                "summary": json.loads(r["summary_json"] or "{}"),
            }
            for r in rows
        ]

    def get_run_results(self, run_id: str) -> list[dict]:
        """Récupère tous les résultats d'un run spécifique."""
        c = self._conn.cursor()
        rows = c.execute("""
            SELECT suite, name, algorithm, data_size_bytes,
                   mean_ms, stddev_ms, p95_ms, p99_ms, cv_percent,
                   throughput_mbps, peak_mb, cpu_mean_pct, extra_json
            FROM results WHERE run_id = ?
            ORDER BY suite, name, algorithm
        """, (run_id,)).fetchall()

        return [
            {
                "suite": r["suite"],
                "name": r["name"],
                "algorithm": r["algorithm"],
                "data_size_bytes": r["data_size_bytes"],
                "mean_ms": r["mean_ms"],
                "stddev_ms": r["stddev_ms"],
                "p95_ms": r["p95_ms"],
                "throughput_mbps": r["throughput_mbps"],
                "peak_mb": r["peak_mb"],
                "extra": json.loads(r["extra_json"] or "{}"),
            }
            for r in rows
        ]

    # ── Trend analysis ────────────────────────────────────────────────────────

    def detect_regression(
        self,
        results: list[BenchmarkResult],
        n_baseline: int = 5,
        threshold_pct: float = -5.0,
        tag: str | None = None,
    ) -> tuple[bool, list[str]]:
        """
        Compare les résultats actuels avec la moyenne des N derniers runs.

        Plus robuste que la comparaison baseline-unique : immune aux one-off anomalies.

        Returns:
            (passed: bool, messages: list[str])
        """
        regressions: list[str] = []
        ok_count = 0

        for r in results:
            if r.throughput_mbps == 0:
                continue
            trend = self.get_trend(r.suite, r.algorithm, r.name, n=n_baseline, tag=tag)
            if len(trend) < 2:
                continue  # pas assez d'historique

            baseline_tp = sum(t.throughput_mbps for t in trend) / len(trend)
            if baseline_tp == 0:
                continue

            delta_pct = (r.throughput_mbps - baseline_tp) / baseline_tp * 100
            key = f"{r.suite}/{r.name}/{r.algorithm}"

            if delta_pct < threshold_pct:
                regressions.append(
                    f"RÉGRESSION {key}: baseline_avg={baseline_tp:.1f} → current={r.throughput_mbps:.1f} MB/s "
                    f"({delta_pct:+.1f}% < seuil {threshold_pct:+.0f}%) [N={len(trend)}]"
                )
            else:
                ok_count += 1

        passed = len(regressions) == 0
        if passed:
            return True, [f"{ok_count} benchmarks OK vs historique (N≥{n_baseline})."]
        return False, regressions

    def compute_drift(
        self,
        suite: str,
        algorithm: str,
        name: str,
        n: int = 20,
    ) -> dict[str, float]:
        """
        Calcule la dérive de performance sur N runs.

        Returns dict avec slope (MB/s par run), r² (qualité de fit), trend_direction.
        """
        trend = self.get_trend(suite, algorithm, name, n=n)
        if len(trend) < 3:
            return {"slope": 0.0, "r2": 0.0, "trend": "insufficient_data"}

        vals = [t.throughput_mbps for t in trend]
        n_pts = len(vals)
        xs = list(range(n_pts))
        mean_x = sum(xs) / n_pts
        mean_y = sum(vals) / n_pts

        # Linear regression
        ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, vals))
        ss_xx = sum((x - mean_x) ** 2 for x in xs)
        slope = ss_xy / ss_xx if ss_xx > 0 else 0.0

        # R²
        y_pred = [mean_y + slope * (x - mean_x) for x in xs]
        ss_res = sum((y - yp) ** 2 for y, yp in zip(vals, y_pred))
        ss_tot = sum((y - mean_y) ** 2 for y in vals)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

        direction = "stable" if abs(slope) < 0.1 else ("improving" if slope > 0 else "degrading")

        return {
            "slope_mbps_per_run": round(slope, 4),
            "r2": round(r2, 4),
            "trend": direction,
            "first_tp": round(vals[0], 2),
            "last_tp": round(vals[-1], 2),
            "n_runs": n_pts,
        }

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
