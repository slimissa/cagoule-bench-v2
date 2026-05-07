"""
bench/cli.py — CLI cagoule-bench v2.0.0

Commandes :
  run             Lance les benchmarks (suites, itérations, formats)
  compare         Compare deux fichiers JSON de résultats
  history         Affiche l'historique SQLite
  compare-history Compare le run actuel avec l'historique
  profile         Lance une suite unique et affiche le détail complet
  list-suites     Liste toutes les suites disponibles
  info            Affiche les informations sur l'environnement CAGOULE

Usage :
  cagoule-bench run --suite encryption avx2 --format console json html
  cagoule-bench run --avx2 --tag main --db .cagoule_bench/history.db
  cagoule-bench history --db .cagoule_bench/history.db --limit 10
  cagoule-bench compare baseline.json current.json
  cagoule-bench info
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import click
from rich import box
from rich.console import Console
from rich.table import Table

from bench.config import BenchConfig
from bench.orchestrator import _CAGOULE_BACKEND, CAGOULE_VERSION, BenchmarkError, Orchestrator
from bench.suites import ALL_SUITES

console = Console()

# ── Helpers ───────────────────────────────────────────────────────────────────


def _resolve_suites(suites: tuple[str, ...], avx2: bool) -> list[str]:
    """Résout la liste des suites à lancer, avec injection auto de 'avx2'."""
    if suites:
        suite_list = list(suites)
    else:
        suite_list = [s for s in ALL_SUITES if s != "avx2"]  # avx2 opt-in
    if avx2 and "avx2" not in suite_list:
        suite_list.append("avx2")
    return suite_list


def _load_json_results(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text())
    # Support format flat list ou dict {"results": [...]}
    if isinstance(data, list):
        return data
    return data.get("results", [])


# ── CLI entrypoint ─────────────────────────────────────────────────────────────


@click.group()
@click.version_option("2.0.0", prog_name="cagoule-bench")
def main():
    """
    cagoule-bench v2.0.0 — Suite de benchmarking cryptographique pour CAGOULE.

    \b
    Exemples rapides :
      cagoule-bench run                          # toutes les suites, console
      cagoule-bench run --suite encryption avx2  # suites ciblées
      cagoule-bench run --avx2 --format json html
      cagoule-bench history                      # 10 derniers runs
      cagoule-bench info                         # environnement CAGOULE
    """


# ── run ───────────────────────────────────────────────────────────────────────


@main.command()
@click.option(
    "--suite",
    "-s",
    multiple=True,
    type=click.Choice(list(ALL_SUITES.keys()), case_sensitive=False),
    help="Suite(s) à lancer (répétable). Défaut : toutes sauf avx2.",
)
@click.option(
    "--avx2", is_flag=True, default=False, help="Ajoute la suite avx2 (CAGOULE v2.2.0 requis)."
)
@click.option("--avx2-only", is_flag=True, default=False, help="Lance uniquement la suite avx2.")
@click.option(
    "--format",
    "-f",
    "formats",
    multiple=True,
    type=click.Choice(["console", "json", "csv", "md", "html"], case_sensitive=False),
    default=("console",),
    show_default=True,
    help="Format(s) de sortie (répétable).",
)
@click.option(
    "--output",
    "-o",
    default="./benchmark_results",
    show_default=True,
    help="Dossier de sortie pour les fichiers.",
)
@click.option(
    "--iterations", "-n", default=None, type=int, help="Nombre d'itérations (écrase la config)."
)
@click.option("--warmup", "-w", default=None, type=int, help="Nombre de warmup (écrase la config).")
@click.option(
    "--size",
    multiple=True,
    type=int,
    help="Tailles de données en bytes (ex: --size 1024 --size 1048576).",
)
@click.option("--db", default=None, help="Chemin vers la base SQLite d'historique.")
@click.option(
    "--tag",
    default="default",
    show_default=True,
    help="Tag/branche pour l'historique (ex: main, pr-42).",
)
@click.option(
    "--baseline", default=None, help="Fichier JSON baseline pour détecter les régressions."
)
@click.option(
    "--threshold",
    default=-5.0,
    show_default=True,
    type=float,
    help="Seuil de régression en % (ex: -5.0).",
)
@click.option(
    "--config",
    default=None,
    type=click.Path(exists=True),
    help="Fichier cagoule_bench.toml explicite.",
)
@click.option(
    "--no-db-regression",
    is_flag=True,
    default=False,
    help="Désactive la vérification de régression via l'historique DB.",
)
def run(
    suite,
    avx2,
    avx2_only,
    formats,
    output,
    iterations,
    warmup,
    size,
    db,
    tag,
    baseline,
    threshold,
    config,
    no_db_regression,
):
    """Lance les benchmarks et génère les rapports."""

    # Charger config fichier
    cfg = BenchConfig.load(Path(config).parent if config else None)
    if cfg._source != "defaults":
        console.print(f"  [dim]→ Config chargée depuis : {cfg._source}[/dim]")

    # Résolution des paramètres (CLI > config > defaults)
    final_iterations = iterations or cfg.iterations
    final_warmup = warmup or cfg.warmup
    final_sizes = list(size) or cfg.sizes or None
    final_db = db or cfg.db_path or None
    final_formats = list(formats) or cfg.formats
    final_threshold = threshold or cfg.regression_threshold

    if avx2_only:
        suite_list = ["avx2"]
    else:
        suite_list = _resolve_suites(suite, avx2)
        if cfg.suites and not suite:
            suite_list = cfg.suites
            if avx2 and "avx2" not in suite_list:
                suite_list.append("avx2")

    try:
        orch = Orchestrator(
            suites=suite_list,
            iterations=final_iterations,
            warmup=final_warmup,
            sizes=final_sizes,
            db_path=final_db,
            tag=tag,
        )
        results = orch.run()
        orch.report(results, formats=final_formats, output_dir=output)

        # BUG3 FIX: vérification régression DB AVANT save_history
        # pour éviter que le run courant soit dans son propre baseline
        passed_db = True  # défaut si pas de DB
        if final_db and not no_db_regression:
            passed_db, msgs_db = orch.check_regression_db(
                results, threshold_pct=final_threshold, tag=tag
            )
            _print_regression_report(passed_db, msgs_db, f"historique DB (tag: {tag})")

        # Sauvegarde APRÈS la vérification (BUG3 FIX)
        orch.save_history(results)

        # Vérification régression baseline JSON (fichier statique)
        if baseline:
            passed, messages = orch.check_regression(
                results, baseline, threshold_pct=final_threshold
            )
            _print_regression_report(passed, messages, "baseline JSON")

        if not passed_db:
            sys.exit(1)

    except BenchmarkError as e:
        console.print(f"[red]Erreur : {e}[/red]")
        sys.exit(1)


def _print_regression_report(passed: bool, messages: list[str], source: str) -> None:
    if passed:
        console.print(f"\n[green]✓ Pas de régression [{source}][/green]")
        for m in messages:
            console.print(f"  [dim]{m}[/dim]")
    else:
        console.print(f"\n[red]✗ RÉGRESSION DÉTECTÉE [{source}][/red]")
        for m in messages:
            console.print(f"  [red]  {m}[/red]")


# ── compare ───────────────────────────────────────────────────────────────────


@main.command()
@click.argument("baseline_file", type=click.Path(exists=True))
@click.argument("current_file", type=click.Path(exists=True))
@click.option(
    "--threshold", default=-5.0, type=float, show_default=True, help="Seuil de régression en %."
)
@click.option("--suite", "-s", default=None, help="Filtrer par suite (ex: encryption).")
def compare(baseline_file, current_file, threshold, suite):
    """Compare deux fichiers JSON de benchmarks."""
    baseline = _load_json_results(baseline_file)
    current = _load_json_results(current_file)

    if suite:
        baseline = [r for r in baseline if r.get("suite") == suite]
        current = [r for r in current if r.get("suite") == suite]

    b_by_key = {f"{r['suite']}/{r['name']}/{r['algorithm']}": r for r in baseline}
    c_by_key = {f"{r['suite']}/{r['name']}/{r['algorithm']}": r for r in current}

    t = Table(
        title="Comparaison baseline → current",
        box=box.ROUNDED,
        border_style="blue",
        header_style="bold blue on black",
    )
    t.add_column("Benchmark", style="white", min_width=32)
    t.add_column("Baseline (MB/s)", justify="right")
    t.add_column("Current (MB/s)", justify="right")
    t.add_column("Delta", justify="right")
    t.add_column("Statut", justify="center")

    regressions = 0
    improvements = 0

    all_keys = sorted(set(b_by_key) | set(c_by_key))
    for key in all_keys:
        b = b_by_key.get(key)
        c = c_by_key.get(key)
        if not b or not c:
            t.add_row(
                key, "[dim]—[/dim]", "[dim]—[/dim]", "[dim]N/A[/dim]", "[dim]NEW/REMOVED[/dim]"
            )
            continue

        b_tp = b.get("throughput_mbps", 0)
        c_tp = c.get("throughput_mbps", 0)
        if b_tp == 0:
            continue

        delta = (c_tp - b_tp) / b_tp * 100
        delta_s = f"{delta:+.1f}%"
        if delta < threshold:
            status = "[red]✗ RÉGRESSION[/red]"
            delta_s = f"[red]{delta_s}[/red]"
            regressions += 1
        elif delta > 5:
            status = "[green]↑ AMÉLIORATION[/green]"
            delta_s = f"[green]{delta_s}[/green]"
            improvements += 1
        else:
            status = "[dim]→ stable[/dim]"
            delta_s = f"[dim]{delta_s}[/dim]"

        t.add_row(key, f"{b_tp:.1f}", f"{c_tp:.1f}", delta_s, status)

    console.print(t)
    console.print(
        f"\n  Régressions : [red]{regressions}[/red]  "
        f"Améliorations : [green]{improvements}[/green]  "
        f"Seuil : [dim]{threshold:+.1f}%[/dim]"
    )
    if regressions > 0:
        sys.exit(1)


# ── history ───────────────────────────────────────────────────────────────────


@main.command()
@click.option("--db", default=".cagoule_bench/history.db", show_default=True)
@click.option("--limit", "-n", default=10, show_default=True, type=int)
@click.option("--tag", default=None, help="Filtrer par tag.")
@click.option("--detail", "-d", default=None, help="Afficher le détail d'un run_id.")
def history(db, limit, tag, detail):
    """Affiche l'historique des benchmarks depuis la base SQLite."""
    from bench.db.history import HistoryDB

    db_path = Path(db)
    if not db_path.exists():
        console.print(f"[yellow]Pas d'historique trouvé : {db}[/yellow]")
        return

    with HistoryDB(db_path) as hdb:
        if detail:
            runs = hdb.get_run_results(detail)
            if not runs:
                console.print(f"[red]run_id {detail!r} introuvable.[/red]")
                return
            t = Table(
                title=f"Résultats run {detail[:8]}...",
                box=box.ROUNDED,
                border_style="blue",
                header_style="bold blue on black",
            )
            t.add_column("Suite")
            t.add_column("Name")
            t.add_column("Algorithm")
            t.add_column("Throughput", justify="right")
            t.add_column("Mean (ms)", justify="right")
            t.add_column("p95 (ms)", justify="right")
            for r in runs:
                t.add_row(
                    r["suite"],
                    r["name"],
                    r["algorithm"],
                    f"{r['throughput_mbps']:.1f} MB/s",
                    f"{r['mean_ms']:.3f}",
                    f"{r['p95_ms']:.3f}",
                )
            console.print(t)
            return

        runs = hdb.list_runs(limit=limit, tag=tag)
        if not runs:
            console.print(f"[dim]Historique vide (DB: {db})[/dim]")
            return

        t = Table(
            title=f"Historique — {len(runs)} runs (DB: {db})",
            box=box.ROUNDED,
            border_style="blue",
            header_style="bold blue on black",
        )
        t.add_column("run_id", style="dim", min_width=10)
        t.add_column("Timestamp")
        t.add_column("Tag", style="cyan")
        t.add_column("Backend", style="yellow")
        t.add_column("Results", justify="right")
        t.add_column("Duration", justify="right")
        t.add_column("CAGOULE MB/s", justify="right", style="green")

        for r in runs:
            run_id_short = r["run_id"][:8] + "..."
            summary = r.get("summary", {})
            cagoule_tp = summary.get("CAGOULE", summary.get("CAGOULE-AVX2", 0))
            tp_str = f"{cagoule_tp:.1f}" if cagoule_tp else "[dim]—[/dim]"
            be = r.get("backend", "?")
            be_c = "green" if be == "avx2" else "yellow"
            t.add_row(
                run_id_short,
                r["timestamp"],
                r["tag"],
                f"[{be_c}]{be}[/{be_c}]",
                str(r["results"]),
                f"{r['duration_s']:.1f}s",
                tp_str,
            )
        console.print(t)
        console.print(
            "\n[dim]Pour voir le détail d'un run : cagoule-bench history --detail <run_id>[/dim]"
        )


# ── compare-history ───────────────────────────────────────────────────────────


@main.command("compare-history")
@click.option("--db", default=".cagoule_bench/history.db", show_default=True)
@click.option("--suite", "-s", default="encryption")
@click.option("--algo", default="CAGOULE")
@click.option("--name", "-n", default="encrypt-1MB", help="Nom du benchmark à tracer.")
@click.option("--n-runs", default=20, type=int, show_default=True)
@click.option("--tag", default=None)
def compare_history(db, suite, algo, name, n_runs, tag):
    """Affiche la tendance d'un benchmark sur les N derniers runs."""
    from bench.db.history import HistoryDB

    db_path = Path(db)
    if not db_path.exists():
        console.print(f"[yellow]Pas d'historique : {db}[/yellow]")
        return

    with HistoryDB(db_path) as hdb:
        trend = hdb.get_trend(suite, algo, name, n=n_runs, tag=tag)
        if not trend:
            console.print(f"[dim]Aucun point de tendance pour {suite}/{algo}/{name}[/dim]")
            return

        drift = hdb.compute_drift(suite, algo, name, n=n_runs)

        t = Table(
            title=f"Tendance : {suite}/{algo}/{name} (N={len(trend)})",
            box=box.ROUNDED,
            border_style="blue",
            header_style="bold blue on black",
        )
        t.add_column("#", justify="right", style="dim")
        t.add_column("Timestamp")
        t.add_column("Tag", style="cyan")
        t.add_column("Throughput", justify="right", style="green")
        t.add_column("Mean (ms)", justify="right")
        t.add_column("p95 (ms)", justify="right", style="dim")

        tps = [p.throughput_mbps for p in trend if p.throughput_mbps > 0]
        avg_tp = sum(tps) / len(tps) if tps else 0.0

        for i, pt in enumerate(trend):
            tp_c = "green" if pt.throughput_mbps >= avg_tp else "red"
            t.add_row(
                str(i + 1),
                pt.timestamp,
                pt.tag,
                f"[{tp_c}]{pt.throughput_mbps:.1f} MB/s[/{tp_c}]",
                f"{pt.mean_ms:.3f}",
                f"{pt.p95_ms:.3f}",
            )
        console.print(t)

        drift_c = (
            "green"
            if drift["trend"] == "improving"
            else ("yellow" if drift["trend"] == "stable" else "red")
        )
        console.print(
            f"\n  Drift : [{drift_c}]{drift['trend']}[/{drift_c}]  "
            f"slope={drift['slope_mbps_per_run']:+.3f} MB/s·run⁻¹  "
            f"R²={drift['r2']:.3f}  "
            f"[dim]({drift['first_tp']:.1f} → {drift['last_tp']:.1f} MB/s)[/dim]"
        )


# ── profile ───────────────────────────────────────────────────────────────────


@main.command()
@click.argument("suite_name", type=click.Choice(list(ALL_SUITES.keys())))
@click.option("--iterations", "-n", default=1000, show_default=True)
@click.option("--warmup", "-w", default=20, show_default=True)
@click.option(
    "--size", default=1_048_576, show_default=True, type=int, help="Taille du message en bytes."
)
def profile(suite_name, iterations, warmup, size):
    """Lance une suite unique en mode profiling haute précision."""
    console.print(f"\n[bold cyan]PROFILE MODE — {suite_name.upper()}[/bold cyan]")
    console.print(
        f"[dim]iterations={iterations}  warmup={warmup}  "
        f"size={size:,} bytes ({size / 1_048_576:.2f} MB)[/dim]\n"
    )

    suite_cls = ALL_SUITES[suite_name]
    kwargs = {"iterations": iterations, "warmup": warmup}
    if suite_name in ("encryption", "avx2", "streaming"):
        kwargs["sizes"] = [size]

    t_start = time.perf_counter()
    results = suite_cls(**kwargs).run()
    duration = time.perf_counter() - t_start

    from bench.reporters import ConsoleReporter

    ConsoleReporter().report(results, suite_name=suite_name)

    console.print(f"\n  [dim]Durée profiling : {duration:.2f}s — {len(results)} benchmarks[/dim]")


# ── info ──────────────────────────────────────────────────────────────────────


@main.command()
def info():
    """Affiche les informations sur l'environnement CAGOULE et le système."""
    import os as _os
    import platform as pl

    console.print()
    console.rule("[bold blue]cagoule-bench v2.0.0 — Environment Info[/bold blue]")

    # Système
    t_sys = Table(box=box.SIMPLE, border_style="dim", header_style="bold dim")
    t_sys.add_column("Key", style="cyan")
    t_sys.add_column("Value", style="white")
    t_sys.add_row("Platform", pl.platform())
    t_sys.add_row("Machine", pl.machine())
    t_sys.add_row("Python", pl.python_version())
    # BUG7 FIX: pl.os.cpu_count() est une API interne CPython non-publique → os.cpu_count()
    t_sys.add_row("CPU count", str(_os.cpu_count() or "?"))

    # AVX2 detection
    try:
        # BUG6 FIX également ici: with + encoding
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            cpuinfo = f.read()
        has_aes_ni = "aes" in cpuinfo
        has_avx2 = "avx2" in cpuinfo
    except Exception:
        has_aes_ni = False
        has_avx2 = False

    t_sys.add_row("AES-NI", "[green]✓[/green]" if has_aes_ni else "[yellow]✗[/yellow]")
    t_sys.add_row("AVX2", "[green]✓[/green]" if has_avx2 else "[yellow]✗[/yellow]")
    console.print("\n[bold]Système[/bold]")
    console.print(t_sys)

    # CAGOULE
    t_cag = Table(box=box.SIMPLE, border_style="dim", header_style="bold dim")
    t_cag.add_column("Key", style="cyan")
    t_cag.add_column("Value", style="white")
    t_cag.add_row("cagoule version", CAGOULE_VERSION)

    backend = _CAGOULE_BACKEND
    matrix_be = backend.get("matrix_backend", "N/A")
    omega_be = backend.get("omega_backend", "N/A")
    be_c = "green" if matrix_be == "avx2" else "yellow"
    t_cag.add_row("matrix_backend", f"[{be_c}]{matrix_be}[/{be_c}]")
    t_cag.add_row("omega_backend", f"[cyan]{omega_be}[/cyan]")
    t_cag.add_row(
        "CGL1 format",
        (
            "[green]inchangé (v2.2.0 rétrocompat)[/green]"
            if CAGOULE_VERSION != "not-installed"
            else "[dim]N/A[/dim]"
        ),
    )

    console.print("\n[bold]CAGOULE[/bold]")
    console.print(t_cag)

    # Dépendances
    t_dep = Table(box=box.SIMPLE, border_style="dim", header_style="bold dim")
    t_dep.add_column("Package", style="cyan")
    t_dep.add_column("Status", style="white")
    # BUG8 FIX: argon2-cffi s'importe comme "argon2", pas "argon2_cffi"
    IMPORT_MAP = {
        "cryptography": "cryptography",
        "argon2-cffi": "argon2",  # package PyPI argon2-cffi → import argon2
        "psutil": "psutil",
        "rich": "rich",
        "click": "click",
        "jinja2": "jinja2",
    }
    for display_name, import_name in IMPORT_MAP.items():
        try:
            __import__(import_name)
            t_dep.add_row(display_name, "[green]✓ installed[/green]")
        except ImportError:
            t_dep.add_row(display_name, "[red]✗ missing[/red]")
    console.print("\n[bold]Dépendances[/bold]")
    console.print(t_dep)
    console.print()


# ── list-suites ───────────────────────────────────────────────────────────────


@main.command("list-suites")
def list_suites():
    """Liste toutes les suites disponibles."""
    t = Table(
        title="Suites disponibles — cagoule-bench v2.0.0",
        box=box.ROUNDED,
        border_style="blue",
        header_style="bold blue on black",
    )
    t.add_column("Suite", style="cyan bold", min_width=14)
    t.add_column("Description", style="white")
    t.add_column("Opt-in ?", justify="center")

    for name, cls in ALL_SUITES.items():
        opt_in = "[yellow]✓[/yellow]" if name == "avx2" else "[dim]—[/dim]"
        t.add_row(name, cls.DESCRIPTION, opt_in)
    console.print(t)
    console.print(
        "[dim]  --avx2 requis pour la suite avx2. "
        "Toutes les autres sont lancées par défaut.[/dim]"
    )


if __name__ == "__main__":
    main()
