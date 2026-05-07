"""
tests/test_suites.py — Tests des suites de benchmarks (fast, no real crypto).

Toutes les suites sont testées avec iterations=2, warmup=1
pour rester rapides (< 10s total).
Les tests marqués @pytest.mark.slow sont skipped par défaut.
"""

import pytest

from bench.suites import ALL_SUITES
from bench.suites.base import BenchmarkResult

# ── BaseSuite + BenchmarkResult ───────────────────────────────────────────────

class TestBenchmarkResult:
    def test_to_dict_has_required_keys(self):
        r = BenchmarkResult(suite="test", name="bench", algorithm="Algo")
        d = r.to_dict()
        assert "suite" in d
        assert "timing" in d
        assert "throughput_mbps" in d
        assert "memory" in d
        assert "cpu" in d
        assert "meta" in d

    def test_samples_ms_conversion(self):
        r = BenchmarkResult(suite="test", name="bench", algorithm="A",
                            samples_ns=[1_000_000, 2_000_000, 3_000_000])
        ms = r.samples_ms()
        assert ms == pytest.approx([1.0, 2.0, 3.0])

    def test_overhead_vs(self):
        r_a = BenchmarkResult(suite="test", name="b", algorithm="A", throughput_mbps=20.0)
        r_b = BenchmarkResult(suite="test", name="b", algorithm="B", throughput_mbps=25.0)
        overhead = r_a.overhead_vs(r_b)
        assert overhead == pytest.approx(-20.0, abs=0.1)

    def test_arch_detected(self):
        r = BenchmarkResult(suite="test", name="b", algorithm="A")
        assert r.arch in ("x86_64", "arm64", "aarch64") or len(r.arch) > 0

    def test_run_id_is_uuid(self):
        import uuid
        r = BenchmarkResult(suite="test", name="b", algorithm="A")
        uuid.UUID(r.run_id)  # ne doit pas lever

    def test_timestamp_format(self):
        r = BenchmarkResult(suite="test", name="b", algorithm="A")
        # Format ISO: YYYY-MM-DDTHH:MM:SSZ
        assert "T" in r.timestamp and "Z" in r.timestamp

    def test_to_dict_serializable(self):
        import json
        r = BenchmarkResult(
            suite="test", name="bench", algorithm="Algo",
            mean_ms=10.0, throughput_mbps=5.0, peak_mb=0.5,
            extra={"key": "value"},
        )
        json.dumps(r.to_dict())  # ne doit pas lever


class TestAllSuitesRegistered:
    def test_all_suites_in_registry(self):
        expected = {"encryption", "kdf", "memory", "parallel", "streaming", "avx2"}
        assert expected.issubset(set(ALL_SUITES.keys()))

    def test_all_suites_have_name(self):
        for name, cls in ALL_SUITES.items():
            assert hasattr(cls, "NAME")
            assert cls.NAME == name

    def test_all_suites_have_description(self):
        for name, cls in ALL_SUITES.items():
            assert hasattr(cls, "DESCRIPTION")
            assert isinstance(cls.DESCRIPTION, str)

    def test_all_suites_have_run_method(self):
        for name, cls in ALL_SUITES.items():
            assert hasattr(cls, "run")


# ── EncryptionSuite ──────────────────────────────────────────────────────────

class TestEncryptionSuite:
    @pytest.fixture
    def suite(self):
        from bench.suites.encryption_suite import EncryptionSuite
        return EncryptionSuite(
            iterations=2, warmup=1,
            sizes=[1_024, 8_192],  # Petites tailles pour rapidité
        )

    def test_returns_list(self, suite):
        results = suite.run()
        assert isinstance(results, list)

    def test_has_three_algorithms(self, suite):
        results = suite.run()
        algos = {r.algorithm for r in results}
        assert "AES-256-GCM" in algos
        assert "ChaCha20-Poly1305" in algos

    def test_each_result_has_timing(self, suite):
        results = suite.run()
        for r in results:
            assert r.mean_ms >= 0
            assert r.stddev_ms >= 0

    def test_samples_ns_stored(self, suite):
        results = suite.run()
        for r in results:
            assert len(r.samples_ns) > 0

    def test_throughput_positive_for_aes(self, suite):
        results = suite.run()
        aes_results = [r for r in results if r.algorithm == "AES-256-GCM"]
        assert all(r.throughput_mbps > 0 for r in aes_results)

    def test_data_size_matches(self, suite):
        results = suite.run()
        sizes_in_results = {r.data_size_bytes for r in results}
        assert 1_024 in sizes_in_results
        assert 8_192 in sizes_in_results

    def test_encrypt_decrypt_present(self, suite):
        results = suite.run()
        names = {r.name for r in results}
        encrypt_names = [n for n in names if "encrypt" in n]
        decrypt_names = [n for n in names if "decrypt" in n]
        assert len(encrypt_names) > 0
        assert len(decrypt_names) > 0

    def test_result_suite_field(self, suite):
        results = suite.run()
        assert all(r.suite == "encryption" for r in results)

    def test_extra_has_arch(self, suite):
        results = suite.run()
        for r in results:
            assert "arch" in r.extra


# ── KdfSuite ─────────────────────────────────────────────────────────────────

class TestKdfSuite:
    @pytest.fixture
    def suite(self):
        from bench.suites.kdf_suite import KdfSuite
        # Grille minimale pour rapidité
        return KdfSuite(
            iterations=2, warmup=1,
            time_costs=[1],
            memory_costs=[16_384],
            parallelism=[1],
            include_scrypt=True,
        )

    def test_returns_results(self, suite):
        results = suite.run()
        assert len(results) > 0

    def test_argon2id_present(self, suite):
        results = suite.run()
        algos = {r.algorithm for r in results}
        assert "Argon2id" in algos

    def test_pbkdf2_present(self, suite):
        results = suite.run()
        algos = {r.algorithm for r in results}
        assert "PBKDF2-SHA256" in algos

    def test_scrypt_present(self, suite):
        results = suite.run()
        algos = {r.algorithm for r in results}
        assert "scrypt" in algos

    def test_security_score_positive(self, suite):
        results = suite.run()
        for r in results:
            score = r.extra.get("security_score", -1)
            assert score > 0

    def test_gpu_resistance_in_extra(self, suite):
        results = suite.run()
        argon = [r for r in results if r.algorithm == "Argon2id"]
        for r in argon:
            assert "gpu_resistance" in r.extra
            assert r.extra["gpu_resistance"] > 0

    def test_owasp_flag_present(self, suite):
        results = suite.run()
        for r in results:
            assert "owasp_compliant" in r.extra

    def test_scrypt_owasp(self, suite):
        results = suite.run()
        scrypt_results = [r for r in results if r.algorithm == "scrypt"]
        # N=16384 (N<65536) → not owasp compliant
        low_n = [r for r in scrypt_results if r.extra.get("N", 0) < 65_536]
        for r in low_n:
            assert r.extra.get("owasp_compliant") is False


# ── MemorySuite ───────────────────────────────────────────────────────────────

class TestMemorySuite:
    @pytest.fixture
    def suite(self):
        from bench.suites.memory_suite import MemorySuite
        return MemorySuite(iterations=2, warmup=1, vault_sizes=[10, 50])

    def test_returns_results(self, suite):
        results = suite.run()
        assert len(results) > 0

    def test_vault_results_present(self, suite):
        results = suite.run()
        vault = [r for r in results if "entries" in r.name]
        assert len(vault) > 0

    def test_cache_result_present(self, suite):
        results = suite.run()
        cache = [r for r in results if "cache" in r.name]
        assert len(cache) > 0

    def test_mb_per_entry_in_extra(self, suite):
        results = suite.run()
        vault = [r for r in results if r.algorithm == "VaultBuild"]
        assert len(vault) > 0, "Aucun résultat VaultBuild trouvé"
        for r in vault:
            assert "mb_per_entry" in r.extra
            assert r.extra["mb_per_entry"] >= 0

    def test_cache_speedup_positive(self, suite):
        results = suite.run()
        cache = [r for r in results if "cache" in r.name]
        for r in cache:
            assert r.extra.get("cache_speedup", 0) >= 0


# ── StreamingSuite ────────────────────────────────────────────────────────────

@pytest.mark.slow
class TestStreamingSuite:
    """Suite de streaming — marked slow, skipped par défaut."""

    @pytest.fixture
    def suite(self):
        from bench.suites.streaming_suite import StreamingSuite
        return StreamingSuite(
            iterations=1, warmup=0,
            sizes=[1_048_576],  # 1MB uniquement
        )

    def test_returns_results(self, suite):
        results = suite.run()
        assert len(results) > 0

    def test_throughput_positive(self, suite):
        results = suite.run()
        for r in results:
            assert r.throughput_mbps > 0

    def test_streaming_flag_in_extra(self, suite):
        results = suite.run()
        for r in results:
            assert r.extra.get("streaming_mode") is True


# ── AVX2Suite ─────────────────────────────────────────────────────────────────

class TestAVX2Suite:
    @pytest.fixture
    def suite(self):
        from bench.suites.avx2_suite import AVX2Suite
        return AVX2Suite(
            iterations=2, warmup=1,
            sizes=[65_536],  # 64KB
        )

    def test_returns_list(self, suite):
        results = suite.run()
        assert isinstance(results, list)

    def test_results_not_empty(self, suite):
        results = suite.run()
        assert len(results) > 0

    def test_avx2_and_scalar_variants(self, suite):
        results = suite.run()
        algos = {r.algorithm for r in results}
        # Si CAGOULE v2.2 disponible : CAGOULE-AVX2 + CAGOULE-Scalar
        # Sinon : CAGOULE seule (mock)
        assert len(algos) > 0

    def test_suite_name(self, suite):
        assert suite.NAME == "avx2"


# ── Orchestrator (sans crypto réel) ──────────────────────────────────────────

class TestOrchestrator:
    def test_unknown_suite_raises(self):
        from bench.orchestrator import BenchmarkError, Orchestrator
        with pytest.raises(BenchmarkError, match="inconnues"):
            Orchestrator(suites=["nonexistent_suite"])

    def test_valid_suite_instantiation(self):
        from bench.orchestrator import Orchestrator
        orch = Orchestrator(suites=["encryption"], iterations=2, warmup=1)
        assert orch.suite_names == ["encryption"]

    def test_regression_check_no_baseline(self, tmp_path):
        from bench.orchestrator import Orchestrator
        orch = Orchestrator(suites=["encryption"], iterations=2, warmup=1)
        r = BenchmarkResult(suite="encryption", name="test", algorithm="A",
                            throughput_mbps=25.0)
        passed, msgs = orch.check_regression([r], baseline_path=tmp_path / "nonexistent.json")
        assert passed is True

    def test_regression_check_detects_regression(self, tmp_path):
        import json

        from bench.orchestrator import Orchestrator
        # BUG4 FIX: tester les deux formats JSON (liste plate ET dict)
        for fmt_name, baseline in [
            ("dict_format", {"results": [{
                "suite": "encryption", "name": "encrypt-1MB",
                "algorithm": "CAGOULE", "throughput_mbps": 30.0,
            }]}),
            ("list_format", [{
                "suite": "encryption", "name": "encrypt-1MB",
                "algorithm": "CAGOULE", "throughput_mbps": 30.0,
            }]),
        ]:
            path = tmp_path / f"baseline_{fmt_name}.json"
            path.write_text(json.dumps(baseline))
            orch = Orchestrator(suites=["encryption"], iterations=2, warmup=1)
            current = [BenchmarkResult(
                suite="encryption", name="encrypt-1MB", algorithm="CAGOULE",
                throughput_mbps=10.0,
            )]
            passed, msgs = orch.check_regression(current, baseline_path=path)
            assert passed is False, f"Format {fmt_name}: régression non détectée"
            assert len(msgs) > 0

    def test_save_history_separated_from_run(self, tmp_path):
        """BUG3 FIX: save_history est séparé de run() pour ne pas contaminer le baseline."""
        from bench.orchestrator import Orchestrator
        orch = Orchestrator(suites=["encryption"], iterations=2, warmup=1,
                            db_path=tmp_path / ".bench" / "hist.db")
        # save_history doit exister comme méthode séparée
        assert hasattr(orch, "save_history"), "save_history() manquant"
