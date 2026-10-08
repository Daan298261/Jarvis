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
