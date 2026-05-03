"""
Tests for build config file discovery and parsing in blueprint_io.py.
Covers _config_kind, _parse_*, and _collect_configs round-trip.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import blueprint_io as bio


# ---------------------------------------------------------------------------
# _config_kind
# ---------------------------------------------------------------------------

class TestConfigKind:
    def test_pyproject(self):
        assert bio._config_kind(Path("pyproject.toml")) == "python-pyproject"

    def test_cargo(self):
        assert bio._config_kind(Path("Cargo.toml")) == "cargo"

    def test_pom(self):
        assert bio._config_kind(Path("pom.xml")) == "maven"

    def test_gradle_settings(self):
        assert bio._config_kind(Path("settings.gradle")) == "gradle-settings"
        assert bio._config_kind(Path("settings.gradle.kts")) == "gradle-settings"

    def test_gradle_build(self):
        assert bio._config_kind(Path("build.gradle")) == "gradle-build"
        assert bio._config_kind(Path("build.gradle.kts")) == "gradle-build"

    def test_package_json(self):
        assert bio._config_kind(Path("package.json")) == "npm"

    def test_go_mod(self):
        assert bio._config_kind(Path("go.mod")) == "go-mod"

    def test_requirements_txt(self):
        assert bio._config_kind(Path("requirements.txt")) == "python-requirements"
        assert bio._config_kind(Path("requirements-dev.txt")) == "python-requirements"
        assert bio._config_kind(Path("requirements_test.txt")) == "python-requirements"

    def test_setuptools_and_make(self):
        assert bio._config_kind(Path("setup.py")) == "setuptools"
        assert bio._config_kind(Path("setup.cfg")) == "setuptools"
        assert bio._config_kind(Path("CMakeLists.txt")) == "cmake"
        assert bio._config_kind(Path("Makefile")) == "make"

    def test_unrecognized(self):
        assert bio._config_kind(Path("foo.json")) is None


# ---------------------------------------------------------------------------
# Parser registry / strategy dispatch
# ---------------------------------------------------------------------------

class TestConfigParserRegistry:
    def test_registry_kinds_are_unique(self):
        kinds = [parser.kind for parser in bio.CONFIG_PARSERS]
        assert len(kinds) == len(set(kinds))

    def test_parser_for_path_matches_exact_filename(self):
        parser = bio._parser_for_path(Path("package.json"))
        assert parser is not None
        assert parser.kind == "npm"

    def test_parser_for_path_matches_glob_pattern(self):
        parser = bio._parser_for_path(Path("requirements-dev.txt"))
        assert parser is not None
        assert parser.kind == "python-requirements"

    def test_parser_for_path_rejects_unknown(self):
        assert bio._parser_for_path(Path("foo.json")) is None

    def test_parse_config_file_delegates_to_strategy(self, tmp_path):
        class DummyParser:
            kind = "dummy"
            filenames = frozenset({"dummy.conf"})
            patterns = ()

            def parse(self, path: Path):
                return "dummy-name", "1.0", ["dummy-dep"], ["dummy-module"]

        parser = DummyParser()
        old = bio.CONFIG_PARSERS
        try:
            bio.CONFIG_PARSERS = (parser,) + tuple(old)
            entry = bio._parse_config_file(tmp_path / "dummy.conf", tmp_path)
        finally:
            bio.CONFIG_PARSERS = old

        assert entry is not None
        assert entry.kind == "dummy"
        assert entry.name == "dummy-name"
        assert entry.version == "1.0"
        assert entry.raw_deps == ["dummy-dep"]
        assert entry.modules == ["dummy-module"]


# ---------------------------------------------------------------------------
# Per-format parsers
# ---------------------------------------------------------------------------

class TestParsePyproject:
    def test_full(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "myapp"\nversion = "1.2.3"\n'
            'dependencies = ["requests", "click>=8"]\n'
        )
        name, version, deps = bio._parse_pyproject(tmp_path / "pyproject.toml")
        assert name == "myapp"
        assert version == "1.2.3"
        assert "requests" in deps
        assert "click>=8" in deps

    def test_missing_fields(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[build-system]\nrequires=[]\n")
        name, version, deps = bio._parse_pyproject(tmp_path / "pyproject.toml")
        assert name is None
        assert version is None
        assert deps == []

    def test_invalid_toml(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("{{broken")
        name, version, deps = bio._parse_pyproject(tmp_path / "pyproject.toml")
        assert name is None
        assert deps == []


class TestParseRequirements:
    def test_basic(self, tmp_path):
        (tmp_path / "requirements.txt").write_text(
            "requests>=2.0\nclick\n# comment\n-r other.txt\nnumpy==1.24\n"
        )
        deps = bio._parse_requirements(tmp_path / "requirements.txt")
        assert "requests" in deps
        assert "click" in deps
        assert "numpy" in deps
        assert len([d for d in deps if d.startswith("#")]) == 0

    def test_empty(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("# just comments\n")
        assert bio._parse_requirements(tmp_path / "requirements.txt") == []


class TestParsePom:
    def test_full(self, tmp_path):
        (tmp_path / "pom.xml").write_text(
            '<?xml version="1.0"?>'
            '<project xmlns="http://maven.apache.org/POM/4.0.0">'
            "<artifactId>mylib</artifactId>"
            "<version>2.0</version>"
            "<dependencies>"
            "  <dependency>"
            "    <groupId>com.google</groupId><artifactId>guava</artifactId>"
            "  </dependency>"
            "</dependencies>"
            "<modules><module>core</module><module>api</module></modules>"
            "</project>"
        )
        name, version, deps, modules = bio._parse_pom(tmp_path / "pom.xml")
        assert name == "mylib"
        assert version == "2.0"
        assert "com.google:guava" in deps
        assert modules == ["core", "api"]

    def test_no_namespace(self, tmp_path):
        # Maven without namespace — gracefully returns None fields
        (tmp_path / "pom.xml").write_text(
            "<project><artifactId>x</artifactId></project>"
        )
        name, version, deps, modules = bio._parse_pom(tmp_path / "pom.xml")
        # Without namespace, ElementTree won't find the tags — result is None/[]
        assert deps == []
        assert modules == []

    def test_invalid_xml(self, tmp_path):
        (tmp_path / "pom.xml").write_text("<broken")
        name, version, deps, modules = bio._parse_pom(tmp_path / "pom.xml")
        assert name is None
        assert deps == []


class TestParseGradleSettings:
    def test_groovy(self, tmp_path):
        (tmp_path / "settings.gradle").write_text(
            "rootProject.name = 'myproject'\ninclude ':core', ':api'\n"
        )
        name, modules = bio._parse_gradle_settings(tmp_path / "settings.gradle")
        assert name == "myproject"
        assert "core" in modules
        assert "api" in modules

    def test_kotlin_dsl(self, tmp_path):
        (tmp_path / "settings.gradle.kts").write_text(
            'rootProject.name = "myproject"\ninclude(":core")\ninclude(":api")\n'
        )
        name, modules = bio._parse_gradle_settings(tmp_path / "settings.gradle.kts")
        assert name == "myproject"
        assert "core" in modules


class TestParseGradleBuild:
    def test_basic(self, tmp_path):
        (tmp_path / "build.gradle").write_text(
            "group = 'com.example'\nversion = '1.0'\n"
            "dependencies {\n"
            "  implementation 'org.springframework:spring-core:5.3'\n"
            "  testImplementation 'junit:junit:4.13'\n"
            "}\n"
        )
        name, version, deps = bio._parse_gradle_build(tmp_path / "build.gradle")
        assert name == "com.example"
        assert version == "1.0"
        assert any("spring-core" in d for d in deps)
        assert any("junit" in d for d in deps)


class TestParsePackageJson:
    def test_full(self, tmp_path):
        import json
        (tmp_path / "package.json").write_text(json.dumps({
            "name": "my-app",
            "version": "3.0.0",
            "dependencies": {"react": "^18", "lodash": "^4"},
            "devDependencies": {"jest": "^29"},
        }))
        name, version, deps = bio._parse_package_json(tmp_path / "package.json")
        assert name == "my-app"
        assert version == "3.0.0"
        assert "react" in deps
        assert "jest" in deps

    def test_invalid_json(self, tmp_path):
        (tmp_path / "package.json").write_text("{broken")
        name, version, deps = bio._parse_package_json(tmp_path / "package.json")
        assert name is None
        assert deps == []


class TestParseCargo:
    def test_full(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text(
            "[package]\nname = \"myapp\"\nversion = \"0.1.0\"\n"
            "[dependencies]\nserde = \"1\"\ntokio = \"1\"\n"
        )
        name, version, deps, modules = bio._parse_cargo(tmp_path / "Cargo.toml")
        assert name == "myapp"
        assert version == "0.1.0"
        assert "serde" in deps
        assert "tokio" in deps
        assert modules == []

    def test_workspace(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text(
            "[workspace]\nmembers = [\"crate-a\", \"crate-b\"]\n"
        )
        name, version, deps, modules = bio._parse_cargo(tmp_path / "Cargo.toml")
        assert modules == ["crate-a", "crate-b"]


class TestParseGoMod:
    def test_basic(self, tmp_path):
        (tmp_path / "go.mod").write_text(
            "module github.com/myorg/myapp\n\ngo 1.21\n\n"
            "require (\n"
            "\tgithub.com/pkg/errors v0.9.1\n"
            "\tgolang.org/x/net v0.20.0\n"
            ")\n"
        )
        name, deps = bio._parse_go_mod(tmp_path / "go.mod")
        assert name == "github.com/myorg/myapp"
        assert "github.com/pkg/errors" in deps
        assert "golang.org/x/net" in deps


# ---------------------------------------------------------------------------
# _collect_configs integration
# ---------------------------------------------------------------------------

class TestCollectConfigs:
    def test_finds_and_parses(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "root"\nversion = "1.0"\n'
        )
        (tmp_path / "package.json").write_text(
            '{"name": "frontend", "version": "2.0", "dependencies": {}}'
        )
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "pyproject.toml").write_text('[project]\nname = "sub"\n')

        entries = bio._collect_configs(tmp_path)
        kinds = {e.kind for e in entries}
        assert "python-pyproject" in kinds
        assert "npm" in kinds

    def test_skips_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules" / "some-pkg"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text('{"name": "dep"}')
        (tmp_path / "package.json").write_text('{"name": "root"}')

        entries = bio._collect_configs(tmp_path)
        paths = [e.path for e in entries]
        assert all("node_modules" not in p for p in paths)

    def test_stable_ids(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        entries = bio._collect_configs(tmp_path)
        assert entries[0].id == "cfg0"

    def test_root_path_is_directory(self, tmp_path):
        sub = tmp_path / "backend"
        sub.mkdir()
        (sub / "pyproject.toml").write_text('[project]\nname = "backend"\n')
        entries = bio._collect_configs(tmp_path)
        assert entries[0].root_path == "backend"

    def test_empty_dir(self, tmp_path):
        assert bio._collect_configs(tmp_path) == []


# ---------------------------------------------------------------------------
# ExtractConfig.semantic_enrichment
# ---------------------------------------------------------------------------

class TestSemanticEnrichmentConfig:
    def test_default_is_true(self):
        from config import ComprehensityConfig
        cfg = ComprehensityConfig()
        assert cfg.extract.semantic_enrichment is True

    def test_false_parses_from_toml(self, tmp_path):
        from config import _build_config
        cfg = _build_config({"extract": {"semantic_enrichment": False}})
        assert cfg.extract.semantic_enrichment is False

    def test_true_explicit(self, tmp_path):
        from config import _build_config
        cfg = _build_config({"extract": {"semantic_enrichment": True}})
        assert cfg.extract.semantic_enrichment is True
