from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import AppSettings
from app.tools.mcp_presets import (
    PRESETS,
    expand_args,
    instantiate_preset,
    list_presets,
    missing_env,
    public_server,
    resolve_mcp_env,
    resolve_stdio_command,
    sanitize_env,
    scrub_servers,
)
from app.tools.mcp_runtime import MCPRuntime


class McpPresetTests(unittest.TestCase):
    def test_catalog_has_documented_optional_servers(self) -> None:
        ids = {preset["id"] for preset in PRESETS}
        self.assertGreaterEqual(len(PRESETS), 4)
        self.assertTrue({"filesystem", "memory", "git", "fetch", "time", "github", "whatsapp", "email"} <= ids)

    def test_catalog_contains_no_secrets(self) -> None:
        blob = json.dumps(PRESETS).lower()
        for needle in ("ghp_", "sk-", "password=", "xoxb-", "-----begin"):
            self.assertNotIn(needle, blob)
        self.assertNotIn("daanv", blob)
        for preset in PRESETS:
            self.assertEqual(preset.get("env") or {}, {})
            self.assertFalse(preset.get("enabled", False))

    def test_default_config_enables_no_mcp_servers(self) -> None:
        raw = json.loads((ROOT / "config" / "default.json").read_text(encoding="utf-8"))
        self.assertEqual(raw.get("mcp_servers"), [])

    def test_filesystem_keeps_placeholders_until_runtime(self) -> None:
        item = instantiate_preset("filesystem")
        joined = " ".join(item["args"])
        self.assertIn("{desktop}", joined)
        self.assertIn("{documents}", joined)
        expanded = " ".join(expand_args(item["args"]))
        self.assertNotIn("{desktop}", expanded)
        self.assertTrue(expanded)

    def test_github_token_is_env_from_not_a_value(self) -> None:
        item = instantiate_preset("github")
        self.assertEqual(item["env_from"], ["GITHUB_PERSONAL_ACCESS_TOKEN"])
        self.assertEqual(item["env"], {})

    def test_messaging_presets_are_pinned_and_keep_credentials_out_of_git(self) -> None:
        whatsapp = instantiate_preset("whatsapp")
        email = instantiate_preset("email")
        self.assertIn("wappmcp@0.4.0", whatsapp["args"])
        self.assertIn("@codefuturist/email-mcp@0.2.3", email["args"])
        self.assertEqual(whatsapp["env"], {})
        self.assertEqual(email["env"], {})
        self.assertEqual(whatsapp["env_from"], [])
        self.assertEqual(email["env_from"], [])

    def test_sanitize_env_rejects_raw_tokens(self) -> None:
        with self.assertRaises(ValueError):
            sanitize_env({"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_this_is_a_secret_value_not_a_ref"})
        refs = sanitize_env({"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}"})
        self.assertEqual(refs["GITHUB_PERSONAL_ACCESS_TOKEN"], "${GITHUB_PERSONAL_ACCESS_TOKEN}")

    def test_public_server_redacts_raw_env_values(self) -> None:
        view = public_server(
            {
                "id": "x",
                "name": "github",
                "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_should_not_leak"},
                "env_from": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
            }
        )
        self.assertEqual(view["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"], "${REDACTED}")
        self.assertEqual(view["env_from"], ["GITHUB_PERSONAL_ACCESS_TOKEN"])

    def test_resolve_mcp_env_reads_process_environment(self) -> None:
        server = instantiate_preset("github")
        with patch.dict(os.environ, {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_runtime_only"}, clear=False):
            env = resolve_mcp_env(server)
        self.assertEqual(env["GITHUB_PERSONAL_ACCESS_TOKEN"], "ghp_runtime_only")
        self.assertNotIn("ghp_runtime_only", json.dumps(server))

    def test_tool_count_uses_connected_runtime_tools(self) -> None:
        from app.tools.mcp_runtime import MCP

        previous = dict(MCP._tools)
        MCP._tools = {
            "mcp_filesystem_read": {"server": {"name": "filesystem"}, "tool": {"name": "read"}},
            "mcp_filesystem_write": {"server": {"name": "filesystem"}, "tool": {"name": "write"}},
            "mcp_git_status": {"server": {"name": "git"}, "tool": {"name": "status"}},
        }
        try:
            self.assertEqual(MCP.tool_count("filesystem"), 2)
            self.assertEqual(MCP.tool_count("git"), 1)
            self.assertEqual(MCP.tool_count("memory"), 0)
        finally:
            MCP._tools = previous

    def test_list_presets_includes_docs(self) -> None:
        catalog = list_presets()
        blob = json.dumps(catalog)
        self.assertTrue(all(item.get("docs") and item.get("description") for item in catalog))
        self.assertNotIn("daanv", blob)
        filesystem = next(item for item in catalog if item["id"] == "filesystem")
        self.assertIn("{desktop}", " ".join(filesystem["args"]))
        github = next(item for item in catalog if item["id"] == "github")
        self.assertEqual(github["env_from"], ["GITHUB_PERSONAL_ACCESS_TOKEN"])

    def test_scrub_servers_drops_raw_tokens(self) -> None:
        cleaned = scrub_servers(
            [
                {
                    "name": "github",
                    "env": {
                        "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_should_not_be_written",
                        "KEEP": "${GITHUB_PERSONAL_ACCESS_TOKEN}",
                    },
                    "env_from": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
                }
            ]
        )
        self.assertEqual(cleaned[0]["env"], {"KEEP": "${GITHUB_PERSONAL_ACCESS_TOKEN}"})
        self.assertNotIn("ghp_should_not_be_written", json.dumps(cleaned))

    def test_save_settings_strips_mcp_secrets(self) -> None:
        import tempfile

        from app.config import save_settings

        tmp = Path(tempfile.mkdtemp(prefix="jarvis-t19-")) / "settings.json"
        settings = AppSettings(
            mcp_servers=[
                {
                    "name": "github",
                    "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_should_not_be_written"},
                    "env_from": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
                }
            ]
        )
        with patch("app.config.settings_path", lambda: tmp):
            save_settings(settings)
        dumped = json.loads(tmp.read_text(encoding="utf-8"))
        self.assertNotIn("ghp_should_not_be_written", json.dumps(dumped))
        self.assertEqual(dumped["mcp_servers"][0]["env"], {})

    def test_resolve_stdio_command_is_nonempty(self) -> None:
        resolved = resolve_stdio_command("npx")
        self.assertTrue(resolved)


class McpRuntimeGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_skips_github_without_token(self) -> None:
        runtime = MCPRuntime()
        server = instantiate_preset("github")
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_PERSONAL_ACCESS_TOKEN"}
        with patch.dict(os.environ, env, clear=True), patch.object(runtime, "_list_tools", new_callable=AsyncMock) as listed:
            status = await runtime.refresh([server])
        listed.assert_not_called()
        self.assertIn("missing env", status["github"])
        self.assertIn("GITHUB_PERSONAL_ACCESS_TOKEN", status["github"])


class McpApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.settings = AppSettings(mcp_servers=[])
        self.patches = [
            patch("app.api.mcp.load_settings", lambda: self.settings),
            patch("app.api.mcp.save_settings", lambda settings: None),
            patch("app.api.mcp.MCP.refresh", new_callable=AsyncMock, return_value={"filesystem": "skipped"}),
        ]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()

    async def test_add_preset_stores_placeholders_not_user_paths(self) -> None:
        from app.api.mcp import add_preset

        item = await add_preset("filesystem")
        blob = json.dumps(item)
        self.assertIn("{desktop}", blob)
        self.assertNotIn("Users\\\\daanv", blob)
        self.assertEqual(self.settings.mcp_servers[0]["preset"], "filesystem")

    async def test_add_raw_secret_is_rejected(self) -> None:
        from app.api.mcp import MCPServerIn, add_mcp

        with self.assertRaises(Exception):
            await add_mcp(
                MCPServerIn(
                    name="github",
                    command="npx",
                    env={"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_do_not_save_this"},
                )
            )
        self.assertEqual(self.settings.mcp_servers, [])


if __name__ == "__main__":
    unittest.main()
