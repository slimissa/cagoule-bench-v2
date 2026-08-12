"""
cagoule-bench v2.3.0 — Suite de benchmarking académique pour CAGOULE.

Nouveautés v2.0 :
  - Config file support (cagoule_bench.toml / pyproject.toml)
  - SQLite history database + trend detection
  - Statistical comparison (Mann-Whitney U + effect size)
  - StreamingSuite — large-file streaming benchmarks
  - scrypt dans KdfSuite
  - Notebook reporter (Jupyter .ipynb)
  - CLI : history, profile, compare-history
  - HTML dashboard : dark mode, filtres, delta vs baseline
  - CAGOULE v2.1 API compatibility

Nouveautés v2.3.0 (CAGOULE v3.1.0 release audit) :
  - HistoryDB : régression filtrée par cagoule_version (plus de mélange
    v3.0.x/v3.1.0 dans le baseline -- fix de correction, pas cosmétique)
  - _find_lib() : divergence entre copies de libcagoule.so détectée et
    propagée sur chaque BenchmarkResult (lib_divergence_warning), n'
    interrompt plus jamais le run
  - AVX2Suite : nouvelle section CTR-lazy-path (cagoule_matrix_mul_avx2_lazy)
    -- l'ancienne section ne testait que le chemin CBC inchangé
  - CTRSuite : nouvelle cible encrypt_v3/decrypt_v3 (API C unifiée)
  - NEON : détection runtime (get_backend_info_v310, neon_backend) --
    aucune implémentation NEON du S-box n'existe, seul le backend
    matrice en a une ; sbox_backend ne rapporte jamais "neon"
  - Cibles de débit relevées pour CAGOULE v3.1.0 (fix AVX2 lazy-reduction,
    ~2x débit CTR C-layer) : CTR e2e 15→30 MB/s, bulk 20 cœurs 80→120 MB/s,
    streaming CTR 18→30 MB/s
  - Correctif : chaîne de version cohérente dans tout le paquet (une
    seule source, bench.__version__) -- plusieurs bannières et
    `cagoule-bench --version` affichaient encore "2.0.0" alors que le
    paquet installé était 2.2.0
  - Correctif : panneau de fin de run affichant "matrix: ?  omega: ?"
    pour les suites ctr/streaming/parallel (dépendait d'un champ extra
    absent de leurs résultats ; utilise maintenant la même source que
    l'en-tête de début de run)
"""

__version__ = "2.3.0"

from bench.db.history import HistoryDB, RunRecord
from bench.metrics import CpuCollector, MemoryCollector, TimeCollector
from bench.metrics.stats import MannWhitneyResult, StatComparison
from bench.reporters import (
    ConsoleReporter,
    CsvReporter,
    HtmlReporter,
    JsonReporter,
    MarkdownReporter,
)
from bench.suites import (
    ALL_SUITES,
    BaseSuite,
    BenchmarkResult,
    EncryptionSuite,
    KdfSuite,
    MemorySuite,
    ParallelSuite,
    StreamingSuite,
)

__all__ = [
    # Version
    "__version__",
    # Metrics
    "TimeCollector",
    "MemoryCollector",
    "CpuCollector",
    "StatComparison",
    "MannWhitneyResult",
    # Suites
    "BaseSuite",
    "BenchmarkResult",
    "EncryptionSuite",
    "KdfSuite",
    "MemorySuite",
    "ParallelSuite",
    "StreamingSuite",
    "ALL_SUITES",
    # Reporters
    "ConsoleReporter",
    "JsonReporter",
    "CsvReporter",
    "MarkdownReporter",
    "HtmlReporter",
    # DB
    "HistoryDB",
    "RunRecord",
]
