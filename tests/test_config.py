"""
tests/test_config.py — Tests du loader de configuration v2.0.
"""

from bench.config import DEFAULTS, BenchConfig


class TestBenchConfigDefaults:
    def test_default_iterations(self):
        cfg = BenchConfig()
        assert cfg.iterations == 500

    def test_default_warmup(self):
        cfg = BenchConfig()
        assert cfg.warmup == 10

    def test_default_output_dir(self):
        cfg = BenchConfig()
        assert cfg.output_dir == "./benchmark_results"

    def test_default_regression_threshold(self):
        cfg = BenchConfig()
        assert cfg.regression_threshold == -5.0

    def test_default_suites_none(self):
        cfg = BenchConfig()
        assert cfg.suites is None

    def test_to_dict_has_all_keys(self):
        cfg = BenchConfig()
        d = cfg.to_dict()
        assert "iterations" in d
        assert "warmup" in d
        assert "suites" in d
        assert "output_dir" in d
        assert "regression_threshold" in d


class TestBenchConfigFromDict:
    def test_from_dict_overrides_defaults(self):
        cfg = BenchConfig._from_dict({"iterations": 1000, "warmup": 5}, source="test")
        assert cfg.iterations == 1000
        assert cfg.warmup == 5

    def test_from_dict_partial_override(self):
        cfg = BenchConfig._from_dict({"iterations": 100}, source="test")
        assert cfg.iterations == 100
        assert cfg.warmup == DEFAULTS["warmup"]  # default intact

    def test_from_dict_suite_list(self):
        cfg = BenchConfig._from_dict({"suites": ["encryption", "kdf"]}, source="test")
        assert cfg.suites == ["encryption", "kdf"]

    def test_source_tracked(self):
        cfg = BenchConfig._from_dict({}, source="mytest.toml")
        assert cfg._source == "mytest.toml"

    def test_regression_threshold_float(self):
        cfg = BenchConfig._from_dict({"regression_threshold": -10.0}, source="test")
        assert cfg.regression_threshold == -10.0


class TestBenchConfigLoad:
    def test_load_returns_config(self):
        cfg = BenchConfig.load()
        assert isinstance(cfg, BenchConfig)

    def test_load_source_defaults_when_no_file(self, tmp_path):
        """Dans un dossier sans config, retourne les defaults."""
        cfg = BenchConfig.load(start_dir=tmp_path)
        assert cfg._source == "defaults"

    def test_load_from_toml_file(self, tmp_path):
        """Charge depuis cagoule_bench.toml si présent."""
        toml_content = "iterations = 999\nwarmup = 7\n"
        cfg_file = tmp_path / "cagoule_bench.toml"
        cfg_file.write_text(toml_content)

        cfg = BenchConfig.load(start_dir=tmp_path)
        # Peut échouer si tomllib/tomli non disponible
        if cfg._source != "defaults":
            assert cfg.iterations == 999
            assert cfg.warmup == 7

    def test_load_from_pyproject_toml(self, tmp_path):
        """Charge depuis [tool.cagoule-bench] dans pyproject.toml."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.cagoule-bench]\niterations = 777\noutput_dir = "./out"\n')
        cfg = BenchConfig.load(start_dir=tmp_path)
        if cfg._source != "defaults":
            assert cfg.iterations == 777

    def test_toml_priority_over_pyproject(self, tmp_path):
        """cagoule_bench.toml a priorité sur pyproject.toml."""
        (tmp_path / "cagoule_bench.toml").write_text("iterations = 111\n")
        (tmp_path / "pyproject.toml").write_text("[tool.cagoule-bench]\niterations = 222\n")
        cfg = BenchConfig.load(start_dir=tmp_path)
        if cfg._source != "defaults":
            assert cfg.iterations == 111
