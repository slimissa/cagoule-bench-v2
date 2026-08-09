"""
bench/config.py — Config file loader pour cagoule-bench v2.0.

Cherche la configuration dans (ordre de priorité) :
  1. cagoule_bench.toml dans le cwd ou parents
  2. [tool.cagoule-bench] dans pyproject.toml
  3. Valeurs par défaut

Usage:
    cfg = BenchConfig.load()
    print(cfg.iterations, cfg.output_dir)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            tomllib = None  # type: ignore[assignment]


# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "iterations": 500,
    "warmup": 10,
    "suites": None,  # None = all
    "output_dir": "./benchmark_results",
    "regression_threshold": -5.0,
    "db_path": ".cagoule_bench/history.db",
    "formats": ["console"],
    "sizes": None,  # None = DEFAULT_SIZES
    "parallel_workers": None,
    "kdf_time_costs": None,
    "kdf_memory_costs": None,
    "kdf_parallelism": None,
}


@dataclass
class BenchConfig:
    iterations: int = 500
    warmup: int = 10
    suites: list[str] | None = None
    output_dir: str = "./benchmark_results"
    regression_threshold: float = -5.0
    db_path: str = ".cagoule_bench/history.db"
    formats: list[str] = field(default_factory=lambda: ["console"])
    sizes: list[int] | None = None
    parallel_workers: list[int] | None = None
    kdf_time_costs: list[int] | None = None
    kdf_memory_costs: list[int] | None = None
    kdf_parallelism: list[int] | None = None

    # Source tracking
    _source: str = field(default="defaults", repr=False)

    @classmethod
    def load(cls, start_dir: Path | None = None) -> "BenchConfig":
        """
        Charge la config depuis le filesystem.
        Remonte depuis start_dir (ou cwd) jusqu'à trouver un fichier config.
        """
        if tomllib is None:
            return cls()

        start = Path(start_dir or ".").resolve()

        # 1. Chercher cagoule_bench.toml
        for parent in [start, *start.parents]:
            cfg_file = parent / "cagoule_bench.toml"
            if cfg_file.exists():
                try:
                    data = tomllib.loads(cfg_file.read_text())
                    return cls._from_dict(data, source=str(cfg_file))
                except Exception:
                    pass

        # 2. Chercher [tool.cagoule-bench] dans pyproject.toml
        for parent in [start, *start.parents]:
            ppt = parent / "pyproject.toml"
            if ppt.exists():
                try:
                    data = tomllib.loads(ppt.read_text())
                    section = data.get("tool", {}).get("cagoule-bench", {})
                    if section:
                        return cls._from_dict(section, source=str(ppt))
                except Exception:
                    pass

        return cls()

    @classmethod
    def _from_dict(cls, d: dict, source: str = "file") -> "BenchConfig":
        def _get(key: str):
            return d.get(key, DEFAULTS[key])

        return cls(
            iterations=int(_get("iterations")),
            warmup=int(_get("warmup")),
            suites=_get("suites"),
            output_dir=str(_get("output_dir")),
            regression_threshold=float(_get("regression_threshold")),
            db_path=str(_get("db_path")),
            formats=list(_get("formats") or ["console"]),
            sizes=_get("sizes"),
            parallel_workers=_get("parallel_workers"),
            kdf_time_costs=_get("kdf_time_costs"),
            kdf_memory_costs=_get("kdf_memory_costs"),
            kdf_parallelism=_get("kdf_parallelism"),
            _source=source,
        )

    def to_dict(self) -> dict:
        return {
            "iterations": self.iterations,
            "warmup": self.warmup,
            "suites": self.suites,
            "output_dir": self.output_dir,
            "regression_threshold": self.regression_threshold,
            "db_path": self.db_path,
            "formats": self.formats,
            "sizes": self.sizes,
            "parallel_workers": self.parallel_workers,
        }
