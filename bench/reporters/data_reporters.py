"""
JsonReporter — export JSON machine-readable.
CsvReporter — export CSV (Excel/Google Sheets compatible).
MarkdownReporter — rapport Markdown prêt pour README.
"""

import csv
import io
import json
import platform
import time
from pathlib import Path

from bench.suites.base import BenchmarkResult


# ──────────────────────────────────────────────────────────────
# JSON
# ──────────────────────────────────────────────────────────────
class JsonReporter:
    def report(self, results: list[BenchmarkResult], output_path: str | Path) -> None:
        output = {
            "cagoule_bench_version": "2.0.0",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "platform": {
                "machine": platform.machine(),
                "system": platform.system(),
                "python": platform.python_version(),
                "processor": platform.processor(),
            },
            "results": [r.to_dict() for r in results],
            "summary": self._summarize(results),
        }
        Path(output_path).write_text(json.dumps(output, indent=2, ensure_ascii=False))

    def _summarize(self, results: list[BenchmarkResult]) -> dict:
        by_algo: dict[str, list[float]] = {}
        for r in results:
            if r.throughput_mbps > 0:
                by_algo.setdefault(r.algorithm, []).append(r.throughput_mbps)
        return {
            algo: {
                "mean_throughput_mbps": round(sum(tps) / len(tps), 2),
                "max_throughput_mbps": round(max(tps), 2),
                "sample_count": len(tps),
            }
            for algo, tps in by_algo.items()
        }


# ──────────────────────────────────────────────────────────────
# CSV
# ──────────────────────────────────────────────────────────────
class CsvReporter:
    FIELDS = [
        "suite",
        "name",
        "algorithm",
        "data_size_bytes",
        "throughput_mbps",
        "mean_ms",
        "stddev_ms",
        "p95_ms",
        "p99_ms",
        "cv_percent",
        "peak_mb",
        "delta_mb",
        "cpu_mean_pct",
        "cpu_peak_pct",
        "platform",
        "timestamp",
    ]

    def report(self, results: list[BenchmarkResult], output_path: str | Path) -> None:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=self.FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            d = r.to_dict()
            row = {
                "suite": d["suite"],
                "name": d["name"],
                "algorithm": d["algorithm"],
                "data_size_bytes": d["data_size_bytes"],
                "throughput_mbps": d["throughput_mbps"],
                "mean_ms": d["timing"]["mean_ms"],
                "stddev_ms": d["timing"]["stddev_ms"],
                "p95_ms": d["timing"]["p95_ms"],
                "p99_ms": d["timing"]["p99_ms"],
                "cv_percent": d["timing"]["cv_percent"],
                "peak_mb": d["memory"]["peak_mb"],
                "delta_mb": d["memory"]["delta_mb"],
                "cpu_mean_pct": d["cpu"]["mean_pct"],
                "cpu_peak_pct": d["cpu"]["peak_pct"],
                "platform": d["meta"]["platform"],
                "timestamp": d["meta"]["timestamp"],
            }
            writer.writerow(row)
        Path(output_path).write_text(buf.getvalue(), encoding="utf-8")


# ──────────────────────────────────────────────────────────────
# Markdown
# ──────────────────────────────────────────────────────────────
class MarkdownReporter:
    def report(self, results: list[BenchmarkResult], output_path: str | Path) -> None:
        lines: list[str] = []
        ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

        lines += [
            "# cagoule-bench — Résultats de Performance",
            "",
            f"**Généré le :** {ts}  ",
            f"**Plateforme :** {platform.machine()} / Python {platform.python_version()}  ",
            "**CAGOULE :** v1.2+  ",
            "",
        ]

        suites = dict.fromkeys(r.suite for r in results)
        for suite in suites:
            suite_results = [r for r in results if r.suite == suite]
            lines += [f"## {suite.upper()}", ""]
            lines += self._suite_table(suite_results)
            lines += [""]

        # Overhead summary
        enc = [r for r in results if r.suite == "encryption" and r.throughput_mbps > 0]
        if enc:
            lines += ["## Overhead Summary — CAGOULE vs Standards", ""]
            lines += self._overhead_table(enc)
            lines += [""]

        lines += [
            "---",
            "_Benchmarks générés par [cagoule-bench](https://github.com/slimissa/cagoule-bench) v2.0.0_",
        ]

        Path(output_path).write_text("\n".join(lines), encoding="utf-8")

    def _suite_table(self, results: list[BenchmarkResult]) -> list[str]:
        lines = [
            "| Test | Algorithm | Throughput | Mean (ms) | ±Stddev | p95 (ms) | Peak RAM |",
            "|------|-----------|------------|-----------|---------|----------|----------|",
        ]
        for r in results:
            tp = f"{r.throughput_mbps:.1f} MB/s" if r.throughput_mbps > 0 else "—"
            lines.append(
                f"| {r.name} | **{r.algorithm}** | {tp} "
                f"| {r.mean_ms:.3f} | ±{r.stddev_ms:.3f} "
                f"| {r.p95_ms:.3f} | {r.peak_mb:.2f} MB |"
            )
        return lines

    def _overhead_table(self, results: list[BenchmarkResult]) -> list[str]:
        by_test: dict[str, dict] = {}
        for r in results:
            by_test.setdefault(r.name, {})[r.algorithm] = r.throughput_mbps

        lines = [
            "| Test | CAGOULE | AES-256-GCM | ChaCha20-Poly1305 | vs AES | vs ChaCha20 |",
            "|------|---------|-------------|-------------------|--------|-------------|",
        ]
        for name, algos in sorted(by_test.items()):
            cag = algos.get("CAGOULE", 0)
            aes = algos.get("AES-256-GCM", 0)
            cha = algos.get("ChaCha20-Poly1305", 0)

            def _pct(a, b):
                if b == 0:
                    return "N/A"
                p = (a - b) / b * 100
                return f"{p:+.1f}%"

            lines.append(
                f"| {name} | {cag:.1f} | {aes:.1f} | {cha:.1f} | {_pct(cag, aes)} | {_pct(cag, cha)} |"
            )
        return lines
