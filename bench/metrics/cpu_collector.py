"""
CpuCollector — suivi CPU via psutil.

Mesure CPU%, RAM système, context switches pendant l'exécution
d'une callable. Particulièrement utile pour la suite parallèle.
"""

import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import psutil


@dataclass
class CpuResult:
    cpu_samples: list[float]
    rss_mb_before: float
    rss_mb_after: float
    duration_s: float
    ctx_switches_voluntary: int
    ctx_switches_involuntary: int
    label: str = ""

    @property
    def cpu_mean_pct(self) -> float:
        return sum(self.cpu_samples) / len(self.cpu_samples) if self.cpu_samples else 0.0

    @property
    def cpu_peak_pct(self) -> float:
        return max(self.cpu_samples) if self.cpu_samples else 0.0

    @property
    def rss_delta_mb(self) -> float:
        return self.rss_mb_after - self.rss_mb_before

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "cpu_mean_pct": round(self.cpu_mean_pct, 2),
            "cpu_peak_pct": round(self.cpu_peak_pct, 2),
            "rss_mb_before": round(self.rss_mb_before, 2),
            "rss_mb_after": round(self.rss_mb_after, 2),
            "rss_delta_mb": round(self.rss_delta_mb, 2),
            "duration_s": round(self.duration_s, 4),
            "ctx_switches_voluntary": self.ctx_switches_voluntary,
            "ctx_switches_involuntary": self.ctx_switches_involuntary,
        }


class CpuCollector:
    """
    Monitore le CPU et la RAM système pendant l'exécution d'une callable.

    Utilise un thread de polling psutil à intervalle régulier.
    Calcule CPU moyen, CPU peak, delta RSS.

    Usage:
        collector = CpuCollector()
        result_value, cpu = collector.measure(lambda: parallel_encrypt(data, workers=4))
        print(cpu.cpu_mean_pct, cpu.rss_delta_mb)
    """

    def __init__(self, poll_interval_s: float = 0.05):
        self.poll_interval_s = poll_interval_s
        self.proc = psutil.Process(os.getpid())

    def measure(self, fn: Callable, label: str = "") -> tuple[Any, CpuResult]:
        cpu_samples: list[float] = []
        stop_event = threading.Event()

        def _poll():
            # Premier appel psutil.cpu_percent() initialise le compteur
            self.proc.cpu_percent(interval=None)
            while not stop_event.is_set():
                cpu_samples.append(self.proc.cpu_percent(interval=None))
                time.sleep(self.poll_interval_s)

        rss_before = self.proc.memory_info().rss / 1_048_576
        try:
            ctx_before = self.proc.num_ctx_switches()
            _ctx_ok = True
        except NotImplementedError:
            ctx_before = None
            _ctx_ok = False

        poller = threading.Thread(target=_poll, daemon=True)
        poller.start()

        t0 = time.perf_counter()
        return_value = fn()
        duration = time.perf_counter() - t0

        stop_event.set()
        poller.join()

        rss_after = self.proc.memory_info().rss / 1_048_576
        if _ctx_ok and ctx_before is not None:
            try:
                ctx_after = self.proc.num_ctx_switches()
                _ctx_vol   = ctx_after.voluntary   - ctx_before.voluntary
                _ctx_invol = ctx_after.involuntary - ctx_before.involuntary
            except NotImplementedError:
                _ctx_vol = _ctx_invol = -1
        else:
            _ctx_vol = _ctx_invol = -1   # -1 = non disponible (kernel < 2.6.23)

        result = CpuResult(
            cpu_samples=cpu_samples or [0.0],
            rss_mb_before=rss_before,
            rss_mb_after=rss_after,
            duration_s=duration,
            ctx_switches_voluntary=_ctx_vol,
            ctx_switches_involuntary=_ctx_invol,
            label=label,
        )
        return return_value, result
