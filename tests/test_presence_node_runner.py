"""Node 22 gate for the presence and owner-chat .mjs suites."""

from __future__ import annotations

import pytest

from tests.presence_node import node_major, run_presence_node_suite


def test_presence_suite_skips_below_node_22(monkeypatch):
    monkeypatch.setattr("tests.presence_node.node_major", lambda: 20)
    with pytest.raises(pytest.skip.Exception, match=r"Node 22.*--experimental-strip-types"):
        run_presence_node_suite("presence-lifecycle.test.mjs")


def test_presence_suite_skips_when_node_is_missing(monkeypatch):
    monkeypatch.setattr("tests.presence_node.node_major", lambda: None)
    with pytest.raises(pytest.skip.Exception, match=r"found missing"):
        run_presence_node_suite("presence-lifecycle.test.mjs")


def test_this_environment_reports_a_node_major():
    major = node_major()
    assert major is None or major >= 1


def test_presence_suite_names_missing_frontend_dependencies(monkeypatch, tmp_path):
    """A checkout without `npm ci` in frontend/ (CI always installs) must fail with the fix, not with
    node's ERR_MODULE_NOT_FOUND stack for whichever package a suite imports first."""
    (tmp_path / "package.json").write_text(
        '{"dependencies": {"react": "^18.3.1", "three": "^0.170.0"}, "devDependencies": {"vite": "^5.4.0"}}',
        encoding="utf-8",
    )
    (tmp_path / "node_modules" / "react").mkdir(parents=True)
    (tmp_path / "scene.test.mjs").write_text('import "three"\n', encoding="utf-8")
    (tmp_path / "pure.test.mjs").write_text('import { test } from "node:test"\ntest("ok", () => {})\n', encoding="utf-8")
    monkeypatch.setattr("tests.presence_node.FRONTEND", tmp_path)
    if (node_major() or 0) < 22:
        pytest.skip("needs Node 22")
    with pytest.raises(pytest.fail.Exception, match=r"three, vite.*npm ci"):
        run_presence_node_suite("scene.test.mjs")
    run_presence_node_suite("pure.test.mjs")  # suites that import no package still run without npm ci
