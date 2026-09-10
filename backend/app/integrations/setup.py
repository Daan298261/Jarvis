from __future__ import annotations

import asyncio
import imaplib
import json
import os
import re
import shutil
import smtplib
import ssl
import tempfile
import tomllib
import uuid
from pathlib import Path
from typing import Any

from ..config import load_settings, repo_root, save_settings

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PAIRING_STATES = {"idle", "starting", "pairing", "connected", "failed"}


class IntegrationSetupError(RuntimeError):
    pass


def email_config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "email-mcp" / "config.toml"


def whatsapp_home() -> Path:
    return Path(os.environ.get("WAPPMCP_HOME") or (Path.home() / ".wappmcp"))


def _clean_text(value: str, label: str, maximum: int) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum or any(ord(char) < 32 for char in cleaned):
        raise IntegrationSetupError(f"Enter a valid {label}.")
    return cleaned


def normalize_gmail_input(account_name: str, email: str, full_name: str, app_password: str) -> dict[str, str]:
    account = _clean_text(account_name, "account name", 64)
    address = _clean_text(email, "email address", 254).lower()
    display_name = _clean_text(full_name, "display name", 128)
    password = "".join(app_password.split())
    if not EMAIL_PATTERN.fullmatch(address):
        raise IntegrationSetupError("Enter a valid email address.")
    if len(password) < 16 or len(password) > 128:
        raise IntegrationSetupError("Enter the 16-character Google app password.")
    return {
        "account_name": account,
        "email": address,
        "full_name": display_name,
        "app_password": password,
    }


def _test_gmail_connections(email: str, password: str, timeout: float = 20.0) -> None:
    context = ssl.create_default_context()
    imap: imaplib.IMAP4_SSL | None = None
    smtp: smtplib.SMTP_SSL | None = None
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com", 993, ssl_context=context, timeout=timeout)
        imap.login(email, password)
        imap.logout()
        imap = None

        smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=timeout)
        smtp.login(email, password)
        smtp.noop()
        smtp.quit()
        smtp = None
    except (imaplib.IMAP4.error, smtplib.SMTPAuthenticationError) as exc:
        raise IntegrationSetupError(
            "Google rejected the sign-in. Check the email address and use a fresh Google app password."
        ) from exc
    except (OSError, smtplib.SMTPException) as exc:
        raise IntegrationSetupError(
            "Jarvis could not reach Gmail. Check the internet connection and try again."
        ) from exc
    finally:
        if imap is not None:
            try:
                imap.shutdown()
            except Exception:
                pass
        if smtp is not None:
            try:
                smtp.close()
            except Exception:
                pass


def _node_executable() -> str:
    node = shutil.which("node")
    if not node:
        raise IntegrationSetupError("The Jarvis connector runtime is missing. Re-run the Jarvis installer.")
    return node


async def _persist_email_account(account: dict[str, str]) -> None:
    helper = repo_root() / "mcp" / "email-config.mjs"
    connector = repo_root() / "mcp" / "node_modules" / "@codefuturist" / "email-mcp"
    if not helper.is_file() or not connector.is_dir():
        raise IntegrationSetupError("The Gmail connector is missing. Re-run the Jarvis installer.")

    final_path = email_config_path()
    final_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="config.", suffix=".tmp", dir=final_path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    payload = {
        "configPath": str(final_path),
        "tempPath": str(temp_path),
        "account": {
            "name": account["account_name"],
            "email": account["email"],
            "full_name": account["full_name"],
            "password": account["app_password"],
            "imap": {
                "host": "imap.gmail.com",
                "port": 993,
                "tls": True,
                "starttls": False,
                "verify_ssl": True,
            },
            "smtp": {
                "host": "smtp.gmail.com",
                "port": 465,
                "tls": True,
                "starttls": False,
                "verify_ssl": True,
                "pool": {"enabled": True, "max_connections": 1, "max_messages": 100},
            },
        },
    }
    try:
        process = await asyncio.create_subprocess_exec(
            _node_executable(),
            str(helper),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await asyncio.wait_for(
            process.communicate(json.dumps(payload).encode("utf-8")), timeout=15
        )
        if process.returncode != 0 or stdout.strip() != b"ok":
            raise IntegrationSetupError("Jarvis could not save the Gmail connection. Try again.")
        os.replace(temp_path, final_path)
        try:
            final_path.chmod(0o600)
        except OSError:
            pass
    except asyncio.TimeoutError as exc:
        raise IntegrationSetupError("Saving the Gmail connection timed out. Try again.") from exc
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def email_status() -> dict[str, Any]:
    path = email_config_path()
    if not path.is_file():
        return {"configured": False, "email": "", "full_name": ""}
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        accounts = raw.get("accounts") or []
        if not accounts:
            return {"configured": False, "email": "", "full_name": ""}
        account = accounts[0]
        return {
            "configured": bool(account.get("email")),
            "email": str(account.get("email") or ""),
            "full_name": str(account.get("full_name") or ""),
        }
    except Exception:
        return {"configured": False, "email": "", "full_name": "", "error": "The saved Gmail setup needs repair."}


def ensure_mcp_preset(preset: str) -> None:
    specs = {
        "email": {
            "name": "email",
            "preset": "email",
            "transport": "stdio",
            "command": "npm",
            "args": ["exec", "--prefix", "mcp", "--", "email-mcp", "stdio"],
            "env": {},
            "enabled": True,
        },
        "whatsapp": {
            "name": "whatsapp",
            "preset": "whatsapp",
            "transport": "stdio",
            "command": "npm",
            "args": ["exec", "--prefix", "mcp", "--", "wappmcp", "mcp", "--headless"],
            "env": {},
            "enabled": True,
        },
    }
    wanted = specs[preset]
    settings = load_settings()
    existing = next(
        (item for item in settings.mcp_servers if item.get("preset") == preset or item.get("name") == preset),
        None,
    )
    if existing is None:
        settings.mcp_servers.append({"id": str(uuid.uuid4()), **wanted})
    else:
        existing_id = existing.get("id") or str(uuid.uuid4())
        existing.clear()
        existing.update({"id": existing_id, **wanted})
    save_settings(settings)


async def configure_gmail(account_name: str, email: str, full_name: str, app_password: str) -> dict[str, Any]:
    account = normalize_gmail_input(account_name, email, full_name, app_password)
    await asyncio.to_thread(_test_gmail_connections, account["email"], account["app_password"])
    await _persist_email_account(account)
    ensure_mcp_preset("email")
    return {"configured": True, "email": account["email"], "full_name": account["full_name"]}


def _chrome_executable() -> str | None:
    override = os.environ.get("WAPPMCP_BROWSER_PATH") or os.environ.get("PUPPETEER_EXECUTABLE_PATH")
    candidates = [
        override,
        shutil.which("chrome"),
        shutil.which("chromium"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
        str(Path(os.environ.get("PROGRAMFILES", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
        str(Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
    ]
    return next((str(Path(item)) for item in candidates if item and Path(item).is_file()), None)


class WhatsAppPairingManager:
    def __init__(self) -> None:
        self._state = "idle"
        self._qr = ""
        self._error = ""
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    def _paired_marker(self) -> Path:
        return whatsapp_home() / "jarvis-paired.json"

    def status(self) -> dict[str, Any]:
        paired = self._paired_marker().is_file()
        state = self._state
        if state == "idle" and paired:
            state = "connected"
        return {
            "state": state,
            "qr": self._qr if state == "pairing" else "",
            "error": self._error if state == "failed" else "",
            "paired": paired or state == "connected",
        }

    async def start(self) -> dict[str, Any]:
        async with self._lock:
            if self._process and self._process.returncode is None:
                return self.status()
            helper = repo_root() / "mcp" / "whatsapp-pairing.mjs"
            connector = repo_root() / "mcp" / "node_modules" / "wappmcp"
            chrome = _chrome_executable()
            if not helper.is_file() or not connector.is_dir():
                raise IntegrationSetupError("The WhatsApp connector is missing. Re-run the Jarvis installer.")
            if not chrome:
                raise IntegrationSetupError("Google Chrome is required for WhatsApp pairing. Install Chrome and try again.")
            env = os.environ.copy()
            env["WAPPMCP_BROWSER_PATH"] = chrome
            self._state = "starting"
            self._qr = ""
            self._error = ""
            self._process = await asyncio.create_subprocess_exec(
                _node_executable(),
                str(helper),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            self._reader = asyncio.create_task(self._read_process(self._process))
            return self.status()

    async def _read_process(self, process: asyncio.subprocess.Process) -> None:
        assert process.stdout is not None
        try:
            while line := await process.stdout.readline():
                try:
                    event = json.loads(line.decode("utf-8", errors="replace"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                state = str(event.get("state") or "")
                if state not in PAIRING_STATES:
                    continue
                self._state = state
                if state == "pairing":
                    self._qr = str(event.get("qr") or "")
                    self._error = ""
                elif state == "connected":
                    self._qr = ""
                    self._error = ""
                    marker = self._paired_marker()
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.write_text(json.dumps({"paired": True}), encoding="utf-8")
                    ensure_mcp_preset("whatsapp")
                elif state == "failed":
                    self._qr = ""
                    self._error = self._safe_pairing_error(str(event.get("error") or ""))
            await process.wait()
            if process.returncode and self._state not in {"failed", "idle"}:
                self._state = "failed"
                self._qr = ""
                self._error = "WhatsApp pairing stopped unexpectedly. Try again."
        except asyncio.CancelledError:
            raise
        except Exception:
            self._state = "failed"
            self._qr = ""
            self._error = "WhatsApp pairing stopped unexpectedly. Try again."

    @staticmethod
    def _safe_pairing_error(_message: str) -> str:
        return "WhatsApp could not complete pairing. Check Chrome and your internet connection, then try again."

    async def cancel(self) -> dict[str, Any]:
        async with self._lock:
            process = self._process
            reader = self._reader
            if process and process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            if reader and not reader.done():
                reader.cancel()
                try:
                    await reader
                except asyncio.CancelledError:
                    pass
            self._process = None
            self._reader = None
            self._state = "idle"
            self._qr = ""
            self._error = ""
            return self.status()

    async def close(self) -> None:
        await self.cancel()


WHATSAPP_PAIRING = WhatsAppPairingManager()
