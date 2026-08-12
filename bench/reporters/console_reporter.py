"""
ConsoleReporter v2.2 — affichage rich dans le terminal.

Nouveautés v2.2 :
  - Suite CTR : tableaux CTR vs CBC, symétrie, migration, bulk KDF
  - Header enrichi : backend CAGOULE (avx2/scalar), backend omega
  - Suite AVX2 : tableau comparatif AVX2 vs scalaire + gain %
  - Suite KDF : colonne scrypt ajoutée
  - Suite streaming : débit par algo
  - Statistiques Mann-Whitney si samples disponibles
"""

import platform
import time

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from bench.suites.base import BenchmarkResult

console = Console()


def _overhead_str(a_tp: float, b_tp: float) -> str:
    if b_tp == 0:
        return "[dim]N/A[/dim]"
    pct = (a_tp - b_tp) / b_tp * 100
    sign = "+" if pct > 0 else ""
    color = "green" if pct >= 0 else "red"
    return f"[{color}]{sign}{pct:.1f}%[/{color}]"


def _detect_cagoule_backend(
    results: list[BenchmarkResult],
    backend_info: dict | None = None,
) -> tuple[str, str]:
    """
    Résout matrix_backend et omega_backend pour l'affichage.

    CORRECTIF (v2.3.0) : dépendait EXCLUSIVEMENT de la présence d'un champ
    matrix_backend dans les extras du PREMIER résultat -- seules
    avx2_suite.py et encryption_suite.py posent ce champ. ctr_suite.py,
    streaming_suite.py et parallel_suite.py ne le posent jamais (leurs
    extras portent d'autres métadonnées : kdf_calls, mode, workers...),
    donc le panneau de fin de run affichait "matrix: ?  omega: ?" pour
    CES suites précises, alors même que l'en-tête de DÉBUT de run
    (imprimé par orchestrator.py, source différente) affichait déjà la
    bonne valeur. Confirmé en confrontant un run réel : "matrix: avx2
    omega: C" dans l'en-tête, "matrix: ?  omega: ?" dans le panneau de
    fin, pour le même run, sur les suites ctr/streaming/parallel.

    Fix : accepter backend_info (dict get_backend_info_v310()/v300(),
    même source que l'en-tête de orchestrator.py) en priorité -- ne
    retomber sur le scavenging des extras que si l'appelant ne fournit
    rien (ex. un appel direct à ConsoleReporter().report(results) hors
    orchestrator, comme dans certains tests).
    """
    if backend_info:
        return (
            backend_info.get("matrix_backend", "?"),
            backend_info.get("omega_backend", "?"),
        )
    for r in results:
        if "matrix_backend" in r.extra:
            return (
                r.extra.get("matrix_backend", "?"),
                r.extra.get("omega_backend", "?"),
            )
    return "?", "?"


class ConsoleReporter:
    def report(
        self,
        results: list[BenchmarkResult],
        suite_name: str = "",
        backend_info: dict | None = None,
        bench_version: str | None = None,
    ) -> None:
        matrix_backend, omega_backend = _detect_cagoule_backend(results, backend_info)
        # v3.1.0 : "neon" est un backend actif valide au même titre que
        # "avx2" -- ne pas l'afficher en jaune comme un backend dégradé.
        backend_color = "green" if matrix_backend in ("avx2", "neon") else "yellow"

        if bench_version is None:
            # Import différé (pas au niveau module) : console_reporter.py
            # est importé PAR bench/__init__.py -- un `from bench import
            # __version__` au niveau module ici serait un import circulaire
            # fragile. Au moment où report() est réellement APPELÉE,
            # bench/__init__.py a fini de s'exécuter depuis longtemps ;
            # cet import différé est donc sûr. orchestrator.py passe déjà
            # bench_version explicitement -- ce repli ne sert qu'aux
            # appels directs de ConsoleReporter().report(results) hors
            # orchestrator (tests, usage bibliothèque).
            from bench import __version__ as bench_version

        console.print()
        console.print(
            Panel(
                Text.assemble(
                    ("cagoule-bench ", "bold cyan"),
                    (f"v{bench_version}", "bold white"),
                    ("  |  ", "dim"),
                    (platform.machine(), "yellow"),
                    ("  |  ", "dim"),
                    (platform.python_version(), "yellow"),
                    ("  |  ", "dim"),
                    ("matrix: ", "dim"),
                    (matrix_backend, backend_color + " bold"),
                    ("  omega: ", "dim"),
                    (omega_backend, "cyan"),
                    ("  |  ", "dim"),
                    (time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "dim"),
                ),
                title=f"[bold blue]CAGOULE-BENCH v{bench_version}[/bold blue]",
                border_style="blue",
            )
        )

        if not results:
            console.print("[yellow]Aucun résultat à afficher.[/yellow]")
            return

        suites = {r.suite for r in results}
        for suite in sorted(suites):
            suite_results = [r for r in results if r.suite == suite]
            self._render_suite(suite, suite_results)

    def _render_suite(self, suite: str, results: list[BenchmarkResult]) -> None:
        console.print(f"\n[bold cyan]{'━' * 72}[/bold cyan]")
        console.print(f"[bold white]  {suite.upper()} SUITE[/bold white]")
        console.print(f"[bold cyan]{'━' * 72}[/bold cyan]")

        dispatch = {
            "encryption": self._render_encryption,
            "ctr": self._render_ctr,
            "kdf": self._render_kdf,
            "memory": self._render_memory,
            "parallel": self._render_parallel,
            "streaming": self._render_streaming,
            "avx2": self._render_avx2,
        }
        dispatch.get(suite, self._render_generic)(results)

    # ── Encryption ────────────────────────────────────────────────────────────

    def _render_encryption(self, results: list[BenchmarkResult]) -> None:
        t = Table(box=box.ROUNDED, border_style="blue", header_style="bold blue on black")
        t.add_column("Test", style="white", min_width=18)
        t.add_column("Algorithm", style="cyan", min_width=18)
        t.add_column("Throughput", justify="right", style="green")
        t.add_column("Mean (ms)", justify="right")
        t.add_column("±Stddev", justify="right", style="dim")
        t.add_column("p95 (ms)", justify="right", style="dim")
        t.add_column("CV%", justify="right", style="dim")
        t.add_column("Mem Peak", justify="right", style="yellow")

        for r in results:
            alg_style = "bold green" if "CAGOULE" in r.algorithm else "white"
            cv_color = "green" if r.cv_percent < 5 else ("yellow" if r.cv_percent < 10 else "red")
            t.add_row(
                r.name,
                f"[{alg_style}]{r.algorithm}[/{alg_style}]",
                f"{r.throughput_mbps:.1f} MB/s",
                f"{r.mean_ms:.3f}",
                f"±{r.stddev_ms:.3f}",
                f"{r.p95_ms:.3f}",
                f"[{cv_color}]{r.cv_percent:.1f}%[/{cv_color}]",
                f"{r.peak_mb:.2f} MB",
            )
        console.print(t)

        by_test: dict[str, dict] = {}
        for r in results:
            if r.throughput_mbps > 0:
                by_test.setdefault(r.name, {})[r.algorithm] = r.throughput_mbps

        console.print("\n[bold]Overhead — CAGOULE vs standards[/bold]")
        ot = Table(box=box.SIMPLE, border_style="dim")
        ot.add_column("Test", style="white")
        ot.add_column("vs AES-256-GCM", justify="right")
        ot.add_column("vs ChaCha20-Poly1305", justify="right")

        for name, algos in sorted(by_test.items()):
            cag = algos.get("CAGOULE", algos.get("CAGOULE-CBC", algos.get("CAGOULE-CTR", 0)))
            aes = algos.get("AES-256-GCM", 0)
            cha = algos.get("ChaCha20-Poly1305", 0)
            ot.add_row(name, _overhead_str(cag, aes), _overhead_str(cag, cha))
        console.print(ot)

    # ── CTR (v2.2 new) ────────────────────────────────────────────────────────

    def _render_ctr(self, results: list[BenchmarkResult]) -> None:
        # ── Section 1: CTR vs CBC ──────────────────────────────────────
        ctr_vs = [r for r in results if "ctr-encrypt" in r.name or "cbc-encrypt" in r.name]
        if ctr_vs:
            console.print("\n[bold green]CTR vs CBC — Throughput Comparison[/bold green]")
            t = Table(box=box.ROUNDED, border_style="green", header_style="bold green on black")
            t.add_column("Size", style="white")
            t.add_column("CTR (MB/s)", justify="right", style="bold green")
            t.add_column("CBC (MB/s)", justify="right", style="blue")
            t.add_column("Speedup", justify="right", style="cyan")
            t.add_column("CTR ms", justify="right", style="dim")

            cbc_by_name = {}
            ctr_by_name = {}
            for r in ctr_vs:
                if "ctr-encrypt" in r.name:
                    ctr_by_name[r.name.replace("ctr-encrypt-", "")] = r
                elif "cbc-encrypt" in r.name:
                    cbc_by_name[r.name.replace("cbc-encrypt-", "")] = r

            for size_label in sorted(ctr_by_name.keys()):
                r_ctr = ctr_by_name.get(size_label)
                r_cbc = cbc_by_name.get(size_label)
                if r_ctr and r_cbc:
                    speedup = r_ctr.throughput_mbps / r_cbc.throughput_mbps if r_cbc.throughput_mbps > 0 else 1.0
                    spd_c = "green" if speedup >= 3.0 else ("yellow" if speedup >= 1.5 else "red")
                    t.add_row(
                        size_label,
                        f"{r_ctr.throughput_mbps:.1f}",
                        f"{r_cbc.throughput_mbps:.1f}",
                        f"[{spd_c}]×{speedup:.1f}[/{spd_c}]",
                        f"{r_ctr.mean_ms:.2f}",
                    )
            console.print(t)
            console.print("[dim]CTR target: >15 MB/s Python e2e[/dim]")

        # ── Section 2: 4x Pipeline ─────────────────────────────────────
        auto = [r for r in results if "ctr-auto" in r.name]
        if auto:
            console.print("\n[bold cyan]CTR Pipeline 4x — Auto-dispatch[/bold cyan]")
            t2 = Table(box=box.SIMPLE, border_style="dim")
            t2.add_column("Size")
            t2.add_column("Throughput", justify="right")
            t2.add_column("Mean (ms)", justify="right")
            for r in sorted(auto, key=lambda x: x.data_size_bytes):
                above = r.extra.get("above_4x_threshold", False)
                label = f"{r.name.replace('ctr-auto-', '')} {'[green]4x[/green]' if above else '[dim]1x[/dim]'}"
                t2.add_row(label, f"{r.throughput_mbps:.1f} MB/s", f"{r.mean_ms:.2f}")
            console.print(t2)
            console.print("[dim]4x pipeline activates for messages ≥ 128 bytes (8 blocks)[/dim]")

        # ── Section 3: Symmetry ─────────────────────────────────────────
        sym = [r for r in results if "sym-encrypt" in r.name or "sym-decrypt" in r.name]
        if sym:
            console.print("\n[bold cyan]CTR Symmetry — encrypt = decrypt[/bold cyan]")
            t3 = Table(box=box.SIMPLE, border_style="dim")
            t3.add_column("Size")
            t3.add_column("Encrypt (MB/s)", justify="right")
            t3.add_column("Decrypt (MB/s)", justify="right")
            t3.add_column("Ratio", justify="right")
            for r in sym:
                if "encrypt" in r.name:
                    ratio = r.extra.get("symmetry_ratio_dec_enc", 0)
                    ratio_c = "green" if 0.95 <= ratio <= 1.05 else "red"
                    dec = next((x for x in sym if x.name == r.name.replace("encrypt", "decrypt")), None)
                    if dec:
                        t3.add_row(
                            r.name.replace("ctr-sym-encrypt-", ""),
                            f"{r.throughput_mbps:.1f}",
                            f"{dec.throughput_mbps:.1f}",
                            f"[{ratio_c}]{ratio:.2f}×[/{ratio_c}]",
                        )
            console.print(t3)

        # ── Section 4: Migration ────────────────────────────────────────
        mig = [r for r in results if "migrate" in r.name]
        if mig:
            console.print("\n[bold yellow]CBC → CTR Migration Cost[/bold yellow]")
            t4 = Table(box=box.SIMPLE, border_style="dim")
            t4.add_column("Size")
            t4.add_column("Time (ms)", justify="right")
            t4.add_column("Throughput", justify="right")
            for r in mig:
                t4.add_row(
                    r.name.replace("migrate-cbc-ctr-", ""),
                    f"{r.mean_ms:.1f}",
                    f"{r.throughput_mbps:.1f} MB/s",
                )
            console.print(t4)

        # ── Section 5: Bulk CTR ─────────────────────────────────────────
        bulk = [r for r in results if "bulk-ctr" in r.name]
        indiv = [r for r in results if "individual-ctr" in r.name]
        if bulk and indiv:
            console.print("\n[bold green]Bulk CTR — KDF Amortization[/bold green]")
            t5 = Table(box=box.ROUNDED, border_style="green", header_style="bold green on black")
            t5.add_column("Messages", justify="right")
            t5.add_column("Bulk (ms)", justify="right", style="green")
            t5.add_column("Individual (ms)", justify="right", style="yellow")
            t5.add_column("Gain", justify="right", style="cyan")
            t5.add_column("KDF calls", justify="center", style="dim")

            bulk_by_n = {}
            for r in bulk:
                n = r.extra.get("n_messages", 0)
                bulk_by_n[n] = r
            indiv_by_n = {}
            for r in indiv:
                n = r.extra.get("n_messages", 0)
                indiv_by_n[n] = r

            for n in sorted(bulk_by_n.keys()):
                r_b = bulk_by_n.get(n)
                r_i = indiv_by_n.get(n)
                if r_b and r_i:
                    gain = r_i.mean_ms / r_b.mean_ms if r_b.mean_ms > 0 else 1.0
                    gain_c = "green" if gain > 1.0 else "dim"
                    t5.add_row(
                        str(n),
                        f"{r_b.mean_ms:.1f}",
                        f"{r_i.mean_ms:.1f}",
                        f"[{gain_c}]{gain:.2f}×[/{gain_c}]",
                        f"1 vs {n}",
                    )
            console.print(t5)
            console.print("[dim]Bulk: 1 Argon2id derivation shared across N messages[/dim]")

    # ── KDF ───────────────────────────────────────────────────────────────────

    def _render_kdf(self, results: list[BenchmarkResult]) -> None:
        argon = [r for r in results if r.algorithm == "Argon2id"]
        pbkdf2 = [r for r in results if r.algorithm == "PBKDF2-SHA256"]
        scrypt_ = [r for r in results if r.algorithm == "scrypt"]

        if argon:
            console.print("\n[bold cyan]Argon2id — Grille de paramètres[/bold cyan]")
            t = Table(box=box.ROUNDED, border_style="blue", header_style="bold blue on black")
            t.add_column("t", justify="center")
            t.add_column("m_cost", justify="center")
            t.add_column("p", justify="center")
            t.add_column("Mean (ms)", justify="right", style="green")
            t.add_column("±Stddev", justify="right", style="dim")
            t.add_column("Peak RAM", justify="right", style="yellow")
            t.add_column("Score", justify="center")
            t.add_column("GPU-resist", justify="center")
            t.add_column("OWASP", justify="center")
            for r in argon:
                ex = r.extra
                score = ex.get("security_score", 0)
                score_c = "green" if score > 20 else ("yellow" if score > 16 else "red")
                gpu = ex.get("gpu_resistance", 0)
                owasp = "✓" if ex.get("owasp_compliant") else "✗"
                owasp_c = "green" if ex.get("owasp_compliant") else "red"
                t.add_row(
                    str(ex.get("t_cost")),
                    f"{ex.get('m_cost_mb')} MB",
                    str(ex.get("parallelism")),
                    f"{r.mean_ms:.1f}",
                    f"±{r.stddev_ms:.1f}",
                    f"{r.peak_mb:.1f} MB",
                    f"[{score_c}]{score}[/{score_c}]",
                    str(gpu),
                    f"[{owasp_c}]{owasp}[/{owasp_c}]",
                )
            console.print(t)

        if scrypt_:
            console.print("\n[bold cyan]scrypt[/bold cyan]")
            t2 = Table(box=box.ROUNDED, border_style="cyan", header_style="bold cyan on black")
            t2.add_column("N", justify="right")
            t2.add_column("r", justify="center")
            t2.add_column("p", justify="center")
            t2.add_column("Mean (ms)", justify="right")
            t2.add_column("Théorique RAM", justify="right", style="yellow")
            t2.add_column("Score", justify="center")
            t2.add_column("OWASP", justify="center")
            for r in scrypt_:
                ex = r.extra
                owasp = "✓" if ex.get("owasp_compliant") else "✗"
                owasp_c = "green" if ex.get("owasp_compliant") else "red"
                t2.add_row(
                    f"{ex.get('N'):,}",
                    str(ex.get("r")),
                    str(ex.get("p")),
                    f"{r.mean_ms:.1f}",
                    f"{ex.get('memory_mb_theoretical', 0):.1f} MB",
                    str(ex.get("security_score", 0)),
                    f"[{owasp_c}]{owasp}[/{owasp_c}]",
                )
            console.print(t2)

        if pbkdf2:
            console.print("\n[bold dim]PBKDF2-SHA256 (référence)[/bold dim]")
            t3 = Table(box=box.SIMPLE, border_style="dim", header_style="bold dim")
            t3.add_column("Iterations", justify="right")
            t3.add_column("Mean (ms)", justify="right")
            t3.add_column("Score", justify="center")
            t3.add_column("OWASP", justify="center")
            for r in pbkdf2:
                ex = r.extra
                owasp = "✓" if ex.get("owasp_compliant") else "✗"
                owasp_c = "green" if ex.get("owasp_compliant") else "dim red"
                t3.add_row(
                    f"{ex.get('iterations', 0):,}",
                    f"{r.mean_ms:.1f}",
                    str(ex.get("security_score", 0)),
                    f"[{owasp_c}]{owasp}[/{owasp_c}]",
                )
            console.print(t3)

    # ── Memory ────────────────────────────────────────────────────────────────

    def _render_memory(self, results: list[BenchmarkResult]) -> None:
        vault = [r for r in results if "entries" in r.name]
        cache = [r for r in results if "cache" in r.name]
        if vault:
            t = Table(box=box.ROUNDED, border_style="blue", header_style="bold blue on black")
            t.add_column("Vault Size", justify="right")
            t.add_column("Peak RAM", justify="right", style="yellow")
            t.add_column("MB/entry", justify="right")
            t.add_column("Build (ms)", justify="right", style="green")
            t.add_column("Entries/s", justify="right")
            t.add_column("Fragm.", justify="right", style="dim")
            for r in vault:
                ex = r.extra
                t.add_row(
                    f"{ex.get('entry_count', 0):,} entries",
                    f"{r.peak_mb:.2f} MB",
                    f"{ex.get('mb_per_entry', 0):.5f}",
                    f"{r.mean_ms:.1f}",
                    f"{ex.get('entries_per_sec', 0):.0f}",
                    f"{ex.get('fragmentation_pct', 0):.1f}%",
                )
            console.print(t)
        for r in cache:
            ex = r.extra
            console.print(
                f"\n[bold]Cache Analysis[/bold]  "
                f"Cold: [red]{ex.get('cold_ms', 0):.3f}ms[/red]  "
                f"Hot: [green]{ex.get('hot_ms', 0):.3f}ms[/green]  "
                f"Speedup: [bold cyan]{ex.get('cache_speedup', 0):.1f}x[/bold cyan]"
            )

    # ── Parallel ──────────────────────────────────────────────────────────────

    def _render_parallel(self, results: list[BenchmarkResult]) -> None:
        real = [r for r in results if r.extra.get("workers") is not None]
        t = Table(box=box.ROUNDED, border_style="blue", header_style="bold blue on black")
        t.add_column("Workers", justify="center")
        t.add_column("Throughput", justify="right", style="green")
        t.add_column("Speedup", justify="right", style="cyan")
        t.add_column("Efficiency", justify="right")
        t.add_column("CPU Mean", justify="right", style="yellow")
        for r in real:
            ex = r.extra
            speedup = ex.get("speedup_ratio", 1.0)
            eff = ex.get("parallel_efficiency_pct", 0)
            eff_c = "green" if eff > 70 else ("yellow" if eff > 40 else "red")
            t.add_row(
                str(ex.get("workers")),
                f"{r.throughput_mbps:.1f} MB/s",
                f"{speedup:.2f}x",
                f"[{eff_c}]{eff:.1f}%[/{eff_c}]",
                f"{r.cpu_mean_pct:.1f}%",
            )
        console.print(t)
        console.print(
            "[dim]ProcessPoolExecutor — GIL non-impactant pour chiffrement CPU-bound[/dim]"
        )

    # ── Streaming (v2.0 new) ──────────────────────────────────────────────────

    def _render_streaming(self, results: list[BenchmarkResult]) -> None:
        t = Table(box=box.ROUNDED, border_style="cyan", header_style="bold cyan on black")
        t.add_column("Test", style="white", min_width=22)
        t.add_column("Algorithm", style="cyan")
        t.add_column("Throughput", justify="right", style="green")
        t.add_column("Mean (ms)", justify="right")
        t.add_column("Chunk", justify="right", style="dim")
        t.add_column("RAM eff.", justify="right", style="yellow")
        for r in results:
            ex = r.extra
            ram_eff = ex.get("ram_efficiency", "?")
            ram_c = "green" if ram_eff == "O(chunk)" else "yellow"
            t.add_row(
                r.name,
                r.algorithm,
                f"{r.throughput_mbps:.1f} MB/s",
                f"{r.mean_ms:.0f}",
                f"{ex.get('chunk_size_kb', 0)} KB",
                f"[{ram_c}]{ram_eff}[/{ram_c}]",
            )
        console.print(t)
        console.print(
            "[dim]Streaming: lecture chunked → chiffrement → sortie — RAM = O(chunk) idéalement[/dim]"
        )

    # ── AVX2 delta (v2.0 new) ────────────────────────────────────────────────

    def _render_avx2(self, results: list[BenchmarkResult]) -> None:
        avx2_results = [r for r in results if r.algorithm == "CAGOULE-AVX2"]
        scalar_results = [r for r in results if r.algorithm == "CAGOULE-Scalar"]
        # v2.3.0 : nouvelle section CTR-lazy-path, distincte de la
        # comparaison CBC ci-dessous -- voir _render_ctr_lazy() plus bas.
        ctr_lazy_results = [r for r in results if r.algorithm == "CAGOULE-CTR-AVX2-lazy"]

        if not avx2_results:
            console.print("[yellow]Backend AVX2 CAGOULE non disponible — skip section CBC AVX2 vs Scalar[/yellow]")
        else:
            console.print("\n[bold green]CAGOULE — CBC : Vectorisation AVX2 vs Scalaire[/bold green]")
            console.print(
                "  [dim](chemin cagoule_matrix_mul_avx2, réduction complète, inchangé depuis v3.0.0 --"
                " voir la section CTR-lazy-path ci-dessous pour le fix de perf v3.1.0)[/dim]"
            )

        is_avx2 = avx2_results[0].extra.get("avx2_available", False) if avx2_results else False
        matrix_be = avx2_results[0].extra.get("matrix_backend", "?") if avx2_results else "?"
        omega_be = avx2_results[0].extra.get("omega_backend", "?") if avx2_results else "?"
        if avx2_results:
            console.print(
                f"  [dim]matrix_backend:[/dim] [bold {'green' if is_avx2 else 'yellow'}]{matrix_be}[/bold {'green' if is_avx2 else 'yellow'}]"
                f"  [dim]omega_backend:[/dim] [cyan]{omega_be}[/cyan]"
                f"  [dim]AVX2 actif:[/dim] [{'green' if is_avx2 else 'red'}]{'✓ OUI' if is_avx2 else '✗ NON (fallback scalaire)'}[/{'green' if is_avx2 else 'red'}]"
            )

        t = Table(box=box.ROUNDED, border_style="green", header_style="bold green on black")
        t.add_column("Taille", style="white", justify="right")
        t.add_column("AVX2 (MB/s)", justify="right", style="bold green")
        t.add_column("Scalar (MB/s)", justify="right", style="yellow")
        t.add_column("Speedup", justify="right", style="cyan")
        t.add_column("Gain", justify="right", style="green")
        t.add_column("AVX2 ms", justify="right", style="dim")
        t.add_column("Scalar ms", justify="right", style="dim")

        scalar_by_name = {r.name: r for r in scalar_results}

        for r_avx2 in avx2_results:
            r_sc = scalar_by_name.get(r_avx2.name)
            if not r_sc:
                continue
            speedup = r_sc.mean_ms / r_avx2.mean_ms if r_avx2.mean_ms > 0 else 1.0
            gain_pct = r_sc.extra.get(
                "avx2_gain_pct",
                (r_sc.mean_ms - r_avx2.mean_ms) / r_sc.mean_ms * 100 if r_sc.mean_ms > 0 else 0,
            )
            gain_c = "green" if gain_pct > 10 else ("yellow" if gain_pct > 0 else "dim")
            t.add_row(
                r_avx2.name.replace("encrypt-", ""),
                f"{r_avx2.throughput_mbps:.1f}",
                f"{r_sc.throughput_mbps:.1f}",
                f"{speedup:.2f}x",
                f"[{gain_c}]+{gain_pct:.1f}%[/{gain_c}]",
                f"{r_avx2.mean_ms:.2f}",
                f"{r_sc.mean_ms:.2f}",
            )
        console.print(t)

        if avx2_results:
            avg_gain = sum(r_sc.extra.get("avx2_gain_pct", 0) for r_sc in scalar_results) / max(
                len(scalar_results), 1
            )
            target = 25.0
            status_c = "green" if avg_gain >= target else ("yellow" if avg_gain >= 10 else "red")
            console.print(
                f"\n  [bold]Gain moyen AVX2 (CBC) :[/bold] [{status_c}]{avg_gain:.1f}%[/{status_c}]  "
                f"[dim](cible historique ≥ +25% -- comparaison CBC uniquement, ne reflète PAS"
                f" le fix de perf v3.1.0 : voir CTR-lazy-path ci-dessous)[/dim]"
            )
        console.print(
            "[dim]Note: CAGOULE_FORCE_SCALAR=1 utilisé pour mesurer le chemin scalaire[/dim]"
        )

        if ctr_lazy_results:
            self._render_ctr_lazy(ctr_lazy_results)

    def _render_ctr_lazy(self, results: list[BenchmarkResult]) -> None:
        """
        v2.3.0 : rendu de la section CTR-lazy-path (cagoule_matrix_mul_avx2_lazy)
        -- le VRAI chemin changé par le fix de perf v3.1.0, distinct de la
        comparaison CBC ci-dessus (cagoule_matrix_mul_avx2, inchangée).
        """
        console.print("\n[bold green]CAGOULE — CTR-lazy-path (fix de perf v3.1.0)[/bold green]")
        console.print(
            "  [dim](cagoule_matrix_mul_avx2_lazy, via encrypt_ctr/decrypt_ctr --"
            " ~2x le débit CTR C-layer vs avant le fix)[/dim]"
        )

        r0 = results[0]
        ctr_backend = r0.extra.get("ctr_backend", "?")
        ctr_4x = r0.extra.get("ctr_4x_available", False)
        console.print(
            f"  [dim]ctr_backend:[/dim] [bold {'green' if ctr_backend == 'C' else 'yellow'}]{ctr_backend}[/bold {'green' if ctr_backend == 'C' else 'yellow'}]"
            f"  [dim]ctr_4x_available:[/dim] [{'green' if ctr_4x else 'yellow'}]{ctr_4x}[/{'green' if ctr_4x else 'yellow'}]"
        )

        t = Table(box=box.ROUNDED, border_style="green", header_style="bold green on black")
        t.add_column("Opération", style="white")
        t.add_column("Taille", justify="right")
        t.add_column("Débit (MB/s)", justify="right", style="bold green")
        t.add_column("Mean (ms)", justify="right", style="dim")

        for r in results:
            op = "encrypt" if "encrypt" in r.name else "decrypt"
            size_label = r.extra.get("size_label", "?")
            t.add_row(op, size_label, f"{r.throughput_mbps:.1f}", f"{r.mean_ms:.3f}")
        console.print(t)

    # ── Generic ───────────────────────────────────────────────────────────────

    def _render_generic(self, results: list[BenchmarkResult]) -> None:
        t = Table(box=box.ROUNDED, border_style="blue", header_style="bold blue on black")
        t.add_column("Name")
        t.add_column("Algorithm")
        t.add_column("Mean (ms)", justify="right")
        t.add_column("Throughput", justify="right")
        for r in results:
            t.add_row(r.name, r.algorithm, f"{r.mean_ms:.3f}", f"{r.throughput_mbps:.1f} MB/s")
        console.print(t)