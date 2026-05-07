"""
Orchestrator v2.0 — cœur de cagoule-bench.

Nouveautés v2.0 :
  - Lecture de BenchConfig (cagoule_bench.toml / pyproject.toml)
  - Sauvegarde automatique dans HistoryDB SQLite
  - Détection backend CAGOULE v2.2.0 (backend_info, AVX2)
  - Détection régression via historique (N derniers runs) en plus du baseline JSON
  - Durée totale du run exposée au reporter
  - Suite "avx2" auto-ajoutée si CAGOULE v2.2.0 détecté et --avx2 passé
"""

from __future__ import annotations

import json
import platform
import time
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from bench.db.history import HistoryDB
from bench.reporters import (
    ConsoleReporter,
    CsvReporter,
    HtmlReporter,
    JsonReporter,
    MarkdownReporter,
)
from bench.suites import ALL_SUITES
from bench.suites.base import BenchmarkResult

console = Console()

REGRESSION_THRESHOLD_PCT = -5.0

# Tenter de récupérer la version CAGOULE
try:
    import cagoule as _cag

    CAGOULE_VERSION = getattr(_cag, "__version__", "unknown")
    try:
        from cagoule import backend_info as _CAGOULE_BACKEND
    except ImportError:
        _CAGOULE_BACKEND = {}
except ImportError:
    CAGOULE_VERSION = "not-installed"
    _CAGOULE_BACKEND = {}


class BenchmarkError(Exception):
    pass


class Orchestrator:
    """
    Point d'entrée central pour l'exécution des benchmarks.

    Usage:
        orch = Orchestrator(suites=["encryption", "avx2"], iterations=500)
        results = orch.run()
        orch.report(results, formats=["console", "json", "html"])
    """

    def __init__(
        self,
        suites: list[str] | None = None,
        iterations: int = 500,
        warmup: int = 10,
        sizes: list[int] | None = None,
        parallel_workers: list[int] | None = None,
        db_path: str | Path | None = None,
        tag: str = "default",
    ):
        self.suite_names = suites or list(ALL_SUITES.keys())
        self.iterations = iterations
        self.warmup = warmup
        self.sizes = sizes
        self.parallel_workers = parallel_workers
        self.db_path = db_path
        self.tag = tag
        self._run_id: str | None = None
        self._duration_s: float = 0.0

        unknown = [s for s in self.suite_names if s not in ALL_SUITES]
        if unknown:
            raise BenchmarkError(
                f"Suites inconnues : {unknown}. Disponibles : {list(ALL_SUITES.keys())}"
            )

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self, progress_callback: Callable[[str], None] | None = None) -> list[BenchmarkResult]:
        all_results: list[BenchmarkResult] = []
        t_start = time.perf_counter()

        # ── Header ────────────────────────────────────────────────────
        matrix_be = _CAGOULE_BACKEND.get("matrix_backend", "?")
        omega_be = _CAGOULE_BACKEND.get("omega_backend", "?")
        be_color = "green" if matrix_be == "avx2" else "yellow"

        console.print()
        console.rule("[bold blue]cagoule-bench v2.0.0[/bold blue]")
        console.print(
            f"  [dim]Platform:[/dim] [cyan]{platform.machine()}[/cyan]  "
            f"[dim]Python:[/dim] [cyan]{platform.python_version()}[/cyan]  "
            f"[dim]CAGOULE:[/dim] [cyan]{CAGOULE_VERSION}[/cyan]  "
            f"[dim]matrix:[/dim] [{be_color}]{matrix_be}[/{be_color}]  "
            f"[dim]omega:[/dim] [cyan]{omega_be}[/cyan]"
        )
        console.print(
            f"  [dim]Suites:[/dim] [cyan]{', '.join(self.suite_names)}[/cyan]  "
            f"[dim]Iterations:[/dim] [yellow]{self.iterations}[/yellow]  "
            f"[dim]Warmup:[/dim] [yellow]{self.warmup}[/yellow]  "
            f"[dim]Tag:[/dim] [dim]{self.tag}[/dim]"
        )
        console.print()

        for suite_name in self.suite_names:
            suite_cls = ALL_SUITES[suite_name]
            kwargs: dict = {"iterations": self.iterations, "warmup": self.warmup}

            if suite_name == "encryption" and self.sizes:
                kwargs["sizes"] = self.sizes
            if suite_name == "avx2" and self.sizes:
                kwargs["sizes"] = self.sizes
            if suite_name == "streaming" and self.sizes:
                kwargs["sizes"] = self.sizes
            if suite_name == "parallel" and self.parallel_workers:
                kwargs["worker_counts"] = self.parallel_workers

            # Réduction itérations pour suites lentes
            if suite_name == "kdf":
                kwargs["iterations"] = min(self.iterations, 5)
                kwargs["warmup"] = 1
            if suite_name in ("memory", "parallel", "streaming"):
                kwargs["iterations"] = min(self.iterations, 3)
                kwargs["warmup"] = 1
            if suite_name == "avx2":
                kwargs["iterations"] = min(self.iterations, 200)
                kwargs["warmup"] = 10

            suite = suite_cls(**kwargs)

            with Progress(
                SpinnerColumn(),
                TextColumn(f"[bold cyan]{suite_name}[/bold cyan] [dim]{suite.DESCRIPTION}[/dim]"),
                TimeElapsedColumn(),
                console=console,
                transient=True,
            ) as progress:
                task = progress.add_task("running", total=None)
                try:
                    results = suite.run()
                    progress.update(task, completed=True)
                except Exception as exc:
                    console.print(f"[red]✗ Suite '{suite_name}' a échoué : {exc}[/red]")
                    raise BenchmarkError(f"Suite '{suite_name}' failed: {exc}") from exc

            all_results.extend(results)
            console.print(
                f"  [green]✓[/green] [bold]{suite_name}[/bold] — {len(results)} benchmarks"
            )

            if progress_callback:
                progress_callback(suite_name)

        self._duration_s = time.perf_counter() - t_start
        console.print()
        console.rule(
            f"[green]Terminé en {self._duration_s:.1f}s — {len(all_results)} résultats[/green]"
        )
        console.print()

        # BUG3 FIX: NE PAS sauvegarder ici.
        # save_history() est appelé explicitement depuis le CLI APRÈS
        # check_regression_db(), garantissant que le run courant n'est
        # pas inclus dans son propre baseline de comparaison.

        return all_results

    def save_history(self, results: list[BenchmarkResult]) -> str | None:
        """
        Sauvegarde le run dans HistoryDB.

        Séparé de run() pour permettre d'appeler check_regression_db()
        AVANT la sauvegarde, évitant que le run courant soit inclus dans
        son propre baseline (BUG3 de v2.0.0).
        """
        if not self.db_path:
            return None
        try:
            with HistoryDB(self.db_path) as db:
                self._run_id = db.save_run(
                    results,
                    tag=self.tag,
                    duration_s=self._duration_s,
                    cagoule_version=CAGOULE_VERSION,
                )
            console.print(
                f"  [dim]→ Historique : run_id={self._run_id[:8]}... sauvegardé dans {self.db_path}[/dim]"
            )
            return self._run_id
        except Exception as e:
            console.print(f"  [yellow]⚠ Historique non sauvegardé : {e}[/yellow]")
            return None

    # ── Report ────────────────────────────────────────────────────────────────

    def report(
        self,
        results: list[BenchmarkResult],
        formats: list[str] | None = None,
        output_dir: str | Path = "./benchmark_results",
    ) -> dict[str, Path]:
        if not formats:
            formats = ["console"]

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        generated: dict[str, Path] = {}

        for fmt in formats:
            if fmt == "console":
                ConsoleReporter().report(results)
                generated["console"] = Path("<stdout>")
            elif fmt == "json":
                path = output_dir / f"bench_{ts}.json"
                JsonReporter().report(results, path)
                generated["json"] = path
                console.print(f"  [dim]→ JSON :[/dim] {path}")
            elif fmt == "csv":
                path = output_dir / f"bench_{ts}.csv"
                CsvReporter().report(results, path)
                generated["csv"] = path
                console.print(f"  [dim]→ CSV  :[/dim] {path}")
            elif fmt in ("md", "markdown"):
                path = output_dir / f"bench_{ts}.md"
                MarkdownReporter().report(results, path)
                generated["markdown"] = path
                console.print(f"  [dim]→ MD   :[/dim] {path}")
            elif fmt == "html":
                path = output_dir / f"bench_{ts}.html"
                HtmlReporter().report(results, path)
                generated["html"] = path
                console.print(f"  [dim]→ HTML :[/dim] {path}")
            else:
                console.print(f"[yellow]Format inconnu : {fmt} — ignoré[/yellow]")

        return generated

    # ── Regression (baseline JSON) ────────────────────────────────────────────

    def check_regression(
        self,
        results: list[BenchmarkResult],
        baseline_path: str | Path,
        threshold_pct: float = REGRESSION_THRESHOLD_PCT,
    ) -> tuple[bool, list[str]]:
        baseline_path = Path(baseline_path)
        if not baseline_path.exists():
            return True, ["Pas de baseline — premier run."]

        raw = json.loads(baseline_path.read_text())
        # BUG4 FIX: JsonReporter peut sauvegarder une liste plate OU {"results": [...]}
        # L'ancien code ne gérait que le format dict → baseline silencieusement vide
        if isinstance(raw, list):
            baseline_results = raw
        else:
            baseline_results = raw.get("results", [])

        baseline_by_key = {
            f"{r['suite']}/{r['name']}/{r['algorithm']}": r for r in baseline_results
        }

        regressions: list[str] = []
        ok_count = 0

        for r in results:
            key = f"{r.suite}/{r.name}/{r.algorithm}"
            baseline = baseline_by_key.get(key)
            if not baseline or r.throughput_mbps == 0:
                continue
            baseline_tp = baseline.get("throughput_mbps", 0)
            if baseline_tp == 0:
                continue
            delta_pct = (r.throughput_mbps - baseline_tp) / baseline_tp * 100
            if delta_pct < threshold_pct:
                regressions.append(
                    f"RÉGRESSION {key}: {baseline_tp:.1f} → {r.throughput_mbps:.1f} MB/s "
                    f"({delta_pct:+.1f}% < {threshold_pct:+.0f}%)"
                )
            else:
                ok_count += 1

        passed = len(regressions) == 0
        return passed, ([f"{ok_count} benchmarks OK."] if passed else regressions)

    # ── Regression (DB historique) ────────────────────────────────────────────

    def check_regression_db(
        self,
        results: list[BenchmarkResult],
        n_baseline: int = 5,
        threshold_pct: float = REGRESSION_THRESHOLD_PCT,
        tag: str | None = None,
    ) -> tuple[bool, list[str]]:
        if not self.db_path:
            return True, ["Pas de DB configurée — skip détection DB."]
        with HistoryDB(self.db_path) as db:
            return db.detect_regression(
                results, n_baseline=n_baseline, threshold_pct=threshold_pct, tag=tag
            )
