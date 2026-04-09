"""Tests for phase0.py — pre-analysis scanner."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import subprocess
from phase0 import scan, detect_runtimes, recommend_installs, _RUNTIME_SPECS


REPOS = Path(__file__).parent / "fixtures" / "repos"
EXPECTED = Path(__file__).parent / "fixtures" / "expected"


def load_expected(scenario: str) -> dict:
    # Expected files live outside the repo dirs so they don't skew extension counts.
    path = EXPECTED / scenario / "phase0.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    # root and runtimes are machine-specific; never stored in expected files
    data.pop("root", None)
    data.pop("runtimes", None)
    return data


def run(scenario: str) -> dict:
    result = scan(str(REPOS / scenario))
    result.pop("root")
    result.pop("runtimes")  # machine-specific; tested separately
    return result


# ---------------------------------------------------------------------------
# Parametrised fixture tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scenario", [
    "py_simple",
    "ts_monorepo",
    "mixed_java_py",
    "flat_js",
    "empty_dir",
    "generated_code",
])
def test_fixture(scenario):
    assert run(scenario) == load_expected(scenario)


# ---------------------------------------------------------------------------
# Targeted assertions — keep these alongside the parametrised test so that
# failures point directly at the feature that broke.
# ---------------------------------------------------------------------------

def test_monorepo_detected():
    result = run("ts_monorepo")
    assert result["monorepo"] is True


def test_single_project_not_monorepo():
    assert run("py_simple")["monorepo"] is False


def test_generated_dirs_excluded_from_counts():
    result = run("generated_code")
    # dist/ and proto/ should not contribute to extension counts
    assert result["extensions"].get(".js") is None
    assert result["extensions"].get(".go") is None
    assert result["extensions"][".py"] == 1


def test_generated_dirs_reported():
    result = run("generated_code")
    assert "dist" in result["generated_dirs"]
    assert "proto" in result["generated_dirs"]


def test_empty_dir_no_languages():
    result = run("empty_dir")
    assert result["languages"] == {}
    assert result["build_configs"] == []
    assert result["primary_languages"] == []


def test_mixed_languages():
    result = run("mixed_java_py")
    assert result["languages"]["java"] == 2
    assert result["languages"]["python"] == 2
    # Both have depth-0 build configs (pom.xml → java, pyproject.toml → python)
    assert set(result["primary_languages"]) == {"java", "python"}


def test_primary_languages_build_config():
    # py_pkg has pyproject.toml at depth 0 → python is primary regardless of file count
    result = run("py_pkg")
    assert "python" in result["primary_languages"]


def test_primary_languages_file_count_fallback(tmp_path):
    # No build config, but 10+ .py files → python crosses the threshold
    for i in range(10):
        (tmp_path / f"module_{i}.py").write_text("x = 1\n")
    result = scan(str(tmp_path))
    assert "python" in result["primary_languages"]


def test_primary_languages_incidental(tmp_path):
    # A handful of .py scripts in what is otherwise an empty repo → below threshold
    for i in range(3):
        (tmp_path / f"script_{i}.py").write_text("x = 1\n")
    result = scan(str(tmp_path))
    assert result["primary_languages"] == []


def test_build_configs_sorted_by_path():
    result = run("ts_monorepo")
    paths = [bc["path"] for bc in result["build_configs"]]
    assert paths == sorted(paths)


def test_build_config_depth():
    result = run("ts_monorepo")
    by_path = {bc["path"]: bc for bc in result["build_configs"]}
    assert by_path["package.json"]["depth"] == 0
    assert by_path["packages/api/package.json"]["depth"] == 2
    assert by_path["packages/client/package.json"]["depth"] == 2


# ---------------------------------------------------------------------------
# Runtime detection tests
# ---------------------------------------------------------------------------

def test_runtimes_present_in_scan_output():
    result = scan(str(REPOS / "py_simple"))
    assert "runtimes" in result
    assert isinstance(result["runtimes"], dict)
    assert set(result["runtimes"].keys()) == {"node", "npm", "go", "java", "rust"}


def test_runtimes_values_are_string_or_none():
    result = scan(str(REPOS / "py_simple"))
    for key, val in result["runtimes"].items():
        assert val is None or isinstance(val, str), f"{key}: expected str or None, got {val!r}"


def _make_proc(stdout="", stderr="", returncode=0):
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = returncode
    return proc


def test_detect_runtimes_all_present():
    responses = {
        "node":  _make_proc(stdout="v20.11.0\n"),
        "npm":   _make_proc(stdout="10.2.4\n"),
        "go":    _make_proc(stdout="go version go1.22.0 darwin/arm64\n"),
        "java":  _make_proc(stderr='openjdk version "21.0.1" 2023-10-17\n'),
        "rustc": _make_proc(stdout="rustc 1.75.0 (82e1608df 2023-12-21)\n"),
    }

    def fake_which(binary):
        return f"/usr/bin/{binary}"

    def fake_run(cmd, **kwargs):
        return responses[cmd[0]]

    with patch("phase0.shutil.which", side_effect=fake_which), \
         patch("phase0.subprocess.run", side_effect=fake_run):
        result = detect_runtimes()

    assert result["node"] == "20.11.0"
    assert result["npm"] == "10.2.4"
    assert result["go"] == "1.22.0"
    assert result["java"] == "21.0.1"
    assert result["rust"] == "1.75.0"


def test_detect_runtimes_missing_binary():
    with patch("phase0.shutil.which", return_value=None):
        result = detect_runtimes()
    assert all(v is None for v in result.values())


def test_detect_runtimes_subprocess_timeout():
    def fake_which(binary):
        return f"/usr/bin/{binary}"

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 5)

    with patch("phase0.shutil.which", side_effect=fake_which), \
         patch("phase0.subprocess.run", side_effect=fake_run):
        result = detect_runtimes()

    assert all(v is None for v in result.values())


def test_detect_runtimes_unparseable_output():
    def fake_which(binary):
        return f"/usr/bin/{binary}"

    def fake_run(cmd, **kwargs):
        return _make_proc(stdout="something unexpected\n", stderr="something unexpected\n")

    with patch("phase0.shutil.which", side_effect=fake_which), \
         patch("phase0.subprocess.run", side_effect=fake_run):
        result = detect_runtimes()

    assert all(v is None for v in result.values())


def test_detect_runtimes_keys_match_spec():
    expected_keys = {key for key, *_ in _RUNTIME_SPECS}
    with patch("phase0.shutil.which", return_value=None):
        result = detect_runtimes()
    assert set(result.keys()) == expected_keys


# ---------------------------------------------------------------------------
# recommend_installs tests
# ---------------------------------------------------------------------------

def _scan_with(languages: dict, runtimes: dict) -> dict:
    """Build a minimal scan result for use with recommend_installs."""
    return {
        "extensions": {},
        "languages": languages,
        "build_configs": [],
        "monorepo": False,
        "generated_dirs": [],
        "runtimes": runtimes,
    }


def test_recommend_python_only():
    result = recommend_installs(_scan_with(
        {"python": 10},
        {"node": None, "npm": None, "go": None, "java": None, "rust": None},
    ))
    assert "tree-sitter-python" in result["grammar_packages"]
    assert "jedi-language-server" in result["pip_auto"]
    assert result["manual_steps"] == []


def test_recommend_js_node_present():
    result = recommend_installs(_scan_with(
        {"javascript": 5},
        {"node": "20.11.0", "npm": "10.2.4", "go": None, "java": None, "rust": None},
    ))
    assert "tree-sitter-javascript" in result["grammar_packages"]
    steps = result["manual_steps"]
    assert len(steps) == 1
    assert steps[0]["lang"] == "javascript"
    assert steps[0]["ready"] is True
    assert "typescript-language-server" in steps[0]["command"]
    assert "note" not in steps[0]


def test_recommend_js_node_absent():
    result = recommend_installs(_scan_with(
        {"javascript": 5},
        {"node": None, "npm": None, "go": None, "java": None, "rust": None},
    ))
    steps = result["manual_steps"]
    assert len(steps) == 1
    assert steps[0]["ready"] is False
    assert "note" in steps[0]
    assert "Node" in steps[0]["note"]


def test_recommend_ts_and_js_deduplicated():
    """JS and TS share one language server — only one manual step emitted."""
    result = recommend_installs(_scan_with(
        {"javascript": 3, "typescript": 5},
        {"node": "20.0.0", "npm": "9.0.0", "go": None, "java": None, "rust": None},
    ))
    lsp_langs = [s["lang"] for s in result["manual_steps"]]
    assert lsp_langs.count("javascript") + lsp_langs.count("typescript") == 1


def test_recommend_go_present():
    result = recommend_installs(_scan_with(
        {"go": 8},
        {"node": None, "npm": None, "go": "1.22.0", "java": None, "rust": None},
    ))
    assert "tree-sitter-go" in result["grammar_packages"]
    steps = result["manual_steps"]
    assert any(s["lang"] == "go" and s["ready"] is True for s in steps)


def test_recommend_go_absent():
    result = recommend_installs(_scan_with(
        {"go": 8},
        {"node": None, "npm": None, "go": None, "java": None, "rust": None},
    ))
    steps = result["manual_steps"]
    assert any(s["lang"] == "go" and s["ready"] is False for s in steps)


def test_recommend_rust_present():
    result = recommend_installs(_scan_with(
        {"rust": 4},
        {"node": None, "npm": None, "go": None, "java": None, "rust": "1.75.0"},
    ))
    steps = result["manual_steps"]
    assert any(s["lang"] == "rust" and s["ready"] is True for s in steps)


def test_recommend_no_languages():
    result = recommend_installs(_scan_with({}, {"node": None, "npm": None, "go": None, "java": None, "rust": None}))
    assert result["grammar_packages"] == []
    assert result["pip_auto"] == []
    assert result["manual_steps"] == []


def test_recommend_grammars_deduplicated():
    """cpp needs tree-sitter-c AND tree-sitter-cpp; c also needs tree-sitter-c → no duplicate."""
    result = recommend_installs(_scan_with(
        {"c": 2, "cpp": 3},
        {"node": None, "npm": None, "go": None, "java": None, "rust": None},
    ))
    pkgs = result["grammar_packages"]
    assert pkgs.count("tree-sitter-c") == 1
    assert "tree-sitter-cpp" in pkgs


def test_recommend_output_keys():
    result = recommend_installs(_scan_with({}, {}))
    assert set(result.keys()) == {"python_requirement", "grammar_packages", "pip_auto", "manual_steps"}


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------

def test_cli_install_guide_flag(tmp_path, capsys):
    """--install-guide prints grammar/server guidance without JSON."""
    import sys
    from unittest.mock import patch as _patch
    with _patch("sys.argv", ["comprehensity-scan", str(tmp_path), "--install-guide"]):
        from phase0 import main
        main()
    captured = capsys.readouterr()
    # No languages in an empty dir → only the SUMMARY line on stderr/stdout via applog;
    # guide block may be empty but should not contain JSON.
    assert "{" not in captured.out


def test_cli_output_flag(tmp_path):
    """With -o, JSON is written to file and stdout is clean."""
    out_file = tmp_path / "scan.json"
    import sys
    from unittest.mock import patch as _patch
    with _patch("sys.argv", ["comprehensity-scan", str(tmp_path), "-o", str(out_file)]):
        from phase0 import main
        main()
    data = json.loads(out_file.read_text())
    assert data["format"] == "phase0"
