"""
HtmlReporter — dashboard HTML interactif via Jinja2 + Chart.js.

Génère un fichier HTML auto-contenu (zéro dépendance externe runtime)
publiable directement sur GitHub Pages.
"""

import json
import platform
import time
from pathlib import Path

from jinja2 import Template

from bench.suites.base import BenchmarkResult

_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>cagoule-bench — Rapport de Performance</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {
    --navy: #1A2F4F; --blue: #2E75B6; --cyan: #00A9CE;
    --green: #1E7145; --gray: #595959; --light: #f8f9fa;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', Arial, sans-serif; background: var(--light); color: #222; }

  header {
    background: var(--navy); color: white; padding: 1.5rem 2rem;
    display: flex; justify-content: space-between; align-items: center;
  }
  header h1 { font-size: 1.8rem; }
  header .meta { font-size: 0.85rem; opacity: 0.7; text-align: right; }

  nav { background: var(--blue); padding: 0 2rem; display: flex; gap: 0; }
  nav a {
    color: white; text-decoration: none; padding: 0.75rem 1.25rem;
    font-size: 0.9rem; border-bottom: 3px solid transparent;
    transition: border-color 0.2s;
  }
  nav a:hover, nav a.active { border-color: var(--cyan); }

  main { max-width: 1200px; margin: 0 auto; padding: 2rem; }
  section { display: none; }
  section.active { display: block; }

  .card { background: white; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); padding: 1.5rem; margin-bottom: 1.5rem; }
  .card h2 { font-size: 1.1rem; color: var(--navy); margin-bottom: 1rem; padding-bottom: 0.5rem; border-bottom: 2px solid var(--cyan); }

  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
  .stat-box { background: white; border-radius: 8px; padding: 1rem; text-align: center; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }
  .stat-box .value { font-size: 1.8rem; font-weight: bold; color: var(--blue); }
  .stat-box .label { font-size: 0.8rem; color: var(--gray); margin-top: 0.25rem; }

  table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
  th { background: var(--navy); color: white; padding: 0.6rem 0.8rem; text-align: left; }
  td { padding: 0.55rem 0.8rem; border-bottom: 1px solid #eee; }
  tr:hover td { background: #f0f7ff; }
  .algo-cagoule { color: var(--green); font-weight: bold; }
  .overhead-neg { color: #c0392b; }
  .overhead-pos { color: var(--green); }

  .chart-container { position: relative; height: 320px; }
  .chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }

  footer { text-align: center; color: var(--gray); font-size: 0.8rem; padding: 2rem; }
  .badge { display: inline-block; background: var(--blue); color: white; padding: 0.2rem 0.6rem; border-radius: 4px; font-size: 0.75rem; }
</style>
</head>
<body>

<header>
  <div>
    <h1>🔬 cagoule-bench</h1>
    <div style="opacity:0.7;font-size:0.9rem">Suite de Benchmarking Cryptographique</div>
  </div>
  <div class="meta">
    {{ platform_info }}<br>
    Python {{ python_version }}<br>
    {{ generated_at }}
  </div>
</header>

<nav>
  <a href="#" class="active" onclick="showSection('overview',this)">Vue d'ensemble</a>
  {% if has_encryption %}<a href="#" onclick="showSection('encryption',this)">Chiffrement</a>{% endif %}
  {% if has_kdf %}<a href="#" onclick="showSection('kdf',this)">KDF</a>{% endif %}
  {% if has_memory %}<a href="#" onclick="showSection('memory',this)">Mémoire</a>{% endif %}
  {% if has_parallel %}<a href="#" onclick="showSection('parallel',this)">Parallélisme</a>{% endif %}
</nav>

<main>

<!-- OVERVIEW -->
<section id="overview" class="active">
  <div class="stats-grid">
    <div class="stat-box"><div class="value">{{ total_benchmarks }}</div><div class="label">Benchmarks</div></div>
    <div class="stat-box"><div class="value">{{ total_suites }}</div><div class="label">Suites</div></div>
    <div class="stat-box"><div class="value">{{ best_cagoule_tp }} MB/s</div><div class="label">CAGOULE Peak</div></div>
    <div class="stat-box"><div class="value">{{ cagoule_overhead_vs_aes }}</div><div class="label">vs AES-256-GCM</div></div>
  </div>

  {% if has_encryption %}
  <div class="card">
    <h2>📊 Throughput Comparatif (tous tests de chiffrement)</h2>
    <div class="chart-container"><canvas id="overviewChart"></canvas></div>
  </div>
  {% endif %}
</section>

<!-- ENCRYPTION -->
{% if has_encryption %}
<section id="encryption">
  <div class="card">
    <h2>⚡ Throughput par Algorithme et Taille</h2>
    <div class="chart-container"><canvas id="encChart"></canvas></div>
  </div>
  <div class="card">
    <h2>📋 Tableau Détaillé</h2>
    <table>
      <tr><th>Test</th><th>Algorithm</th><th>Throughput</th><th>Mean (ms)</th><th>±Stddev</th><th>p95</th><th>Peak RAM</th><th>vs AES</th></tr>
      {% for r in enc_rows %}
      <tr>
        <td>{{ r.name }}</td>
        <td class="{{ 'algo-cagoule' if r.algorithm == 'CAGOULE' else '' }}">{{ r.algorithm }}</td>
        <td>{{ r.throughput_mbps|round(1) }} MB/s</td>
        <td>{{ r.mean_ms|round(3) }}</td>
        <td>±{{ r.stddev_ms|round(3) }}</td>
        <td>{{ r.p95_ms|round(3) }}</td>
        <td>{{ r.peak_mb|round(2) }} MB</td>
        <td class="{{ 'overhead-neg' if r.overhead_vs_aes < 0 else 'overhead-pos' }}">
          {{ '%+.1f'|format(r.overhead_vs_aes) }}%
        </td>
      </tr>
      {% endfor %}
    </table>
  </div>
</section>
{% endif %}

<!-- KDF -->
{% if has_kdf %}
<section id="kdf">
  <div class="card">
    <h2>🔑 Argon2id — Grille de Paramètres</h2>
    <div class="chart-grid">
      <div class="chart-container"><canvas id="kdfTimeChart"></canvas></div>
      <div class="chart-container"><canvas id="kdfMemChart"></canvas></div>
    </div>
  </div>
  <div class="card">
    <h2>📋 Tableau Argon2id</h2>
    <table>
      <tr><th>t_cost</th><th>m_cost</th><th>p</th><th>Mean (ms)</th><th>±Stddev</th><th>Peak RAM</th><th>Score Sécurité</th></tr>
      {% for r in kdf_rows %}
      <tr>
        <td>{{ r.extra.t_cost }}</td>
        <td>{{ r.extra.m_cost_mb }} MB</td>
        <td>{{ r.extra.parallelism }}</td>
        <td>{{ r.mean_ms|round(1) }}</td>
        <td>±{{ r.stddev_ms|round(1) }}</td>
        <td>{{ r.peak_mb|round(1) }} MB</td>
        <td><span class="badge">{{ r.extra.security_score }}</span></td>
      </tr>
      {% endfor %}
    </table>
  </div>
</section>
{% endif %}

<!-- MEMORY -->
{% if has_memory %}
<section id="memory">
  <div class="card">
    <h2>💾 Empreinte Mémoire — Scalabilité Vault</h2>
    <div class="chart-container"><canvas id="memChart"></canvas></div>
  </div>
  <div class="card">
    <h2>📋 Tableau Mémoire</h2>
    <table>
      <tr><th>Vault Size</th><th>Peak RAM</th><th>MB/entry</th><th>Build Time</th><th>Entries/s</th><th>Fragmentation</th></tr>
      {% for r in mem_rows %}
      <tr>
        <td>{{ r.extra.entry_count|int }} entrées</td>
        <td>{{ r.peak_mb|round(2) }} MB</td>
        <td>{{ r.extra.mb_per_entry }}</td>
        <td>{{ r.mean_ms|round(1) }} ms</td>
        <td>{{ r.extra.entries_per_sec|int }}</td>
        <td>{{ r.extra.fragmentation_pct }}%</td>
      </tr>
      {% endfor %}
    </table>
  </div>
</section>
{% endif %}

<!-- PARALLEL -->
{% if has_parallel %}
<section id="parallel">
  <div class="card">
    <h2>⚡ Scalabilité Parallèle (ProcessPoolExecutor)</h2>
    <div class="chart-grid">
      <div class="chart-container"><canvas id="parTpChart"></canvas></div>
      <div class="chart-container"><canvas id="parSpeedChart"></canvas></div>
    </div>
  </div>
  <div class="card">
    <h2>📋 Tableau Parallélisme</h2>
    <table>
      <tr><th>Workers</th><th>Throughput</th><th>Ops/s</th><th>Speedup</th><th>Efficacité</th><th>CPU Mean</th><th>CPU Peak</th></tr>
      {% for r in par_rows %}
      <tr>
        <td>{{ r.extra.workers }}</td>
        <td>{{ r.throughput_mbps|round(1) }} MB/s</td>
        <td>{{ r.extra.ops_per_sec|int }}</td>
        <td>{{ r.extra.speedup_ratio }}x</td>
        <td>{{ r.extra.parallel_efficiency_pct }}%</td>
        <td>{{ r.cpu_mean_pct|round(1) }}%</td>
        <td>{{ r.cpu_peak_pct|round(1) }}%</td>
      </tr>
      {% endfor %}
    </table>
    <p style="margin-top:0.75rem;font-size:0.8rem;color:var(--gray)">
      Note : ProcessPoolExecutor exclusivement — chiffrement CPU-bound, GIL non-impactant.
    </p>
  </div>
</section>
{% endif %}

</main>

<footer>
  <p>cagoule-bench v2.0.0 — <a href="https://github.com/slimissa/cagoule-bench">github.com/slimissa/cagoule-bench</a></p>
</footer>

<script>
const DATA = {{ chart_data_json }};

function showSection(id, el) {
  document.querySelectorAll('section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('nav a').forEach(a => a.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  if (el) el.classList.add('active');
  return false;
}

const COLORS = {
  CAGOULE: 'rgba(30,113,69,0.85)',
  'AES-256-GCM': 'rgba(46,117,182,0.85)',
  'ChaCha20-Poly1305': 'rgba(0,169,206,0.85)',
  'Argon2id': 'rgba(127,96,0,0.85)',
  'PBKDF2-SHA256': 'rgba(89,89,89,0.7)',
};
const COLORS_BORDER = {
  CAGOULE: '#1E7145', 'AES-256-GCM': '#2E75B6',
  'ChaCha20-Poly1305': '#00A9CE', 'Argon2id': '#7F6000', 'PBKDF2-SHA256': '#595959',
};

function mkChart(id, type, labels, datasets, opts={}) {
  const el = document.getElementById(id);
  if (!el) return;
  new Chart(el, { type, data: { labels, datasets }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'top' } }, ...opts } });
}

// Overview bar
if (DATA.enc_labels) {
  const overviewDS = Object.entries(DATA.enc_by_algo).map(([algo, vals]) => ({
    label: algo, data: vals,
    backgroundColor: COLORS[algo] || 'rgba(100,100,100,0.7)',
    borderColor: COLORS_BORDER[algo] || '#666', borderWidth: 1,
  }));
  mkChart('overviewChart', 'bar', DATA.enc_labels, overviewDS, {
    scales: { y: { title: { display: true, text: 'Throughput (MB/s)' } } }
  });
  mkChart('encChart', 'bar', DATA.enc_labels, overviewDS, {
    scales: { y: { title: { display: true, text: 'Throughput (MB/s)' } } }
  });
}

// KDF
if (DATA.kdf_labels) {
  mkChart('kdfTimeChart', 'bar', DATA.kdf_labels, [{
    label: 'Argon2id Mean (ms)', data: DATA.kdf_times,
    backgroundColor: COLORS['Argon2id'], borderColor: COLORS_BORDER['Argon2id'], borderWidth: 1,
  }], { scales: { y: { title: { display: true, text: 'Latence (ms)' } } } });
  mkChart('kdfMemChart', 'bar', DATA.kdf_labels, [{
    label: 'Peak RAM (MB)', data: DATA.kdf_mem,
    backgroundColor: 'rgba(231,76,60,0.7)', borderColor: '#c0392b', borderWidth: 1,
  }], { scales: { y: { title: { display: true, text: 'RAM (MB)' } } } });
}

// Memory
if (DATA.mem_labels) {
  mkChart('memChart', 'line', DATA.mem_labels, [{
    label: 'Peak RAM (MB)', data: DATA.mem_peaks,
    borderColor: '#2E75B6', backgroundColor: 'rgba(46,117,182,0.15)',
    tension: 0.3, fill: true, pointRadius: 5,
  }], { scales: { y: { title: { display: true, text: 'Peak RAM (MB)' } } } });
}

// Parallel
if (DATA.par_labels) {
  mkChart('parTpChart', 'line', DATA.par_labels, [{
    label: 'Throughput (MB/s)', data: DATA.par_tp,
    borderColor: '#1E7145', backgroundColor: 'rgba(30,113,69,0.15)',
    tension: 0.3, fill: true, pointRadius: 5,
  }], { scales: { y: { title: { display: true, text: 'MB/s' } } } });
  mkChart('parSpeedChart', 'line', DATA.par_labels, [
    { label: 'Speedup réel', data: DATA.par_speedup, borderColor: '#2E75B6', tension: 0.3, pointRadius: 5 },
    { label: 'Speedup idéal', data: DATA.par_ideal, borderColor: '#aaa', borderDash: [5,5], tension: 0 },
  ], { scales: { y: { title: { display: true, text: 'Speedup (x)' } } } });
}
</script>
</body>
</html>
"""


class HtmlReporter:
    def report(self, results: list[BenchmarkResult], output_path: str | Path) -> None:
        enc = [r for r in results if r.suite == "encryption"]
        kdf = [r for r in results if r.suite == "kdf" and r.algorithm == "Argon2id"]
        mem = [r for r in results if r.suite == "memory" and "entries" in r.name]
        par = [r for r in results if r.suite == "parallel"]

        # Build chart data
        chart_data: dict = {}

        if enc:
            by_test: dict[str, dict] = {}
            for r in enc:
                by_test.setdefault(r.name, {})[r.algorithm] = r.throughput_mbps
            test_names = sorted(by_test.keys())
            algos = ["CAGOULE", "AES-256-GCM", "ChaCha20-Poly1305"]
            chart_data["enc_labels"] = test_names
            chart_data["enc_by_algo"] = {
                algo: [round(by_test[t].get(algo, 0), 2) for t in test_names]
                for algo in algos
            }

        if kdf:
            chart_data["kdf_labels"] = [r.name.replace("argon2id-", "") for r in kdf]
            chart_data["kdf_times"] = [round(r.mean_ms, 1) for r in kdf]
            chart_data["kdf_mem"] = [round(r.peak_mb, 1) for r in kdf]

        if mem:
            chart_data["mem_labels"] = [f"{r.extra['entry_count']} entries" for r in mem]
            chart_data["mem_peaks"] = [round(r.peak_mb, 3) for r in mem]

        if par:
            workers = [r.extra.get("workers", 0) for r in par]
            chart_data["par_labels"] = [f"{w}w" for w in workers]
            chart_data["par_tp"] = [round(r.throughput_mbps, 1) for r in par]
            chart_data["par_speedup"] = [round(r.extra.get("speedup_ratio", 1.0), 2) for r in par]
            chart_data["par_ideal"] = [round(w, 1) for w in workers]

        # Overhead vs AES for enc table
        aes_by_name = {r.name: r.throughput_mbps for r in enc if r.algorithm == "AES-256-GCM"}

        class _R:
            def __init__(self, r):
                self.__dict__ = r.to_dict().copy()
                self.__dict__.update(r.__dict__)
                self.overhead_vs_aes = r.overhead_vs(type("X", (), {"throughput_mbps": aes_by_name.get(r.name, 0)})()) if aes_by_name.get(r.name) else 0.0

        # Summary stats
        cagoule_enc = [r for r in enc if r.algorithm == "CAGOULE"]
        aes_enc = [r for r in enc if r.algorithm == "AES-256-GCM"]
        best_cag = round(max((r.throughput_mbps for r in cagoule_enc), default=0), 1)
        if cagoule_enc and aes_enc:
            cag_mean = sum(r.throughput_mbps for r in cagoule_enc) / len(cagoule_enc)
            aes_mean = sum(r.throughput_mbps for r in aes_enc) / len(aes_enc)
            overhead = (cag_mean - aes_mean) / aes_mean * 100 if aes_mean else 0
            overhead_str = f"{overhead:+.1f}%"
        else:
            overhead_str = "N/A"

        template = Template(_TEMPLATE)
        html = template.render(
            generated_at=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
            platform_info=f"{platform.system()} {platform.machine()}",
            python_version=platform.python_version(),
            total_benchmarks=len(results),
            total_suites=len({r.suite for r in results}),
            best_cagoule_tp=best_cag,
            cagoule_overhead_vs_aes=overhead_str,
            has_encryption=bool(enc),
            has_kdf=bool(kdf),
            has_memory=bool(mem),
            has_parallel=bool(par),
            enc_rows=[_R(r) for r in enc],
            kdf_rows=kdf,
            mem_rows=mem,
            par_rows=par,
            chart_data_json=json.dumps(chart_data),
        )
        Path(output_path).write_text(html, encoding="utf-8")
