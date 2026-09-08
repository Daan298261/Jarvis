"""Conversational first-run setup planner (RFC-0049).

The UI is conversational, but the resulting configuration is deterministic and
inspectable. Free-text answers are normalized into a small set of policies,
then combined with detected hardware to produce a setup/model plan.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import data_dir, models_dir
from .hardware import HardwareInfo, detect_hardware
from .setup_recommend import recommend_from_hardware

ONBOARDING_VERSION = 1

QUESTIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "use",
        "question": "What do you mainly want Jarvis to do?",
        "help": "A short answer is enough. For example: coding, everyday automation, research and writing, security monitoring, or a bit of everything.",
        "choices": ["Everyday assistant", "Coding", "Research / writing", "Security / monitoring", "A bit of everything"],
    },
    {
        "id": "policy",
        "question": "How should I balance local privacy, speed and cloud quality?",
        "help": "Local first is the default: use this PC when practical and escalate only when it materially helps.",
        "choices": ["Local first", "Best result", "Cheapest practical", "Local only"],
    },
    {
        "id": "resources",
        "question": "How much of this computer may Jarvis use while you are using it?",
        "help": "Jarvis still respects the hardware limits it detects.",
        "choices": ["Light (~25%)", "Balanced (~50%)", "Aggressive (~80%)", "Maximum when needed"],
    },
    {
        "id": "voice",
        "question": "Do you want to use voice with Jarvis?",
        "help": "You can change this later. Speech input during setup is optional either way.",
        "choices": ["Yes", "No"],
    },
)

MODEL_MANIFEST: dict[str, dict[str, Any]] = {
    "bootstrap_ornith": {
        "id": "bootstrap_ornith",
        "label": "Ornith 1.5 9B · Bootstrap",
        "role": "Bootstrap / Orchestrator",
        "repo": "ornith-ai/Ornith-1.5-9B-GGUF",
        "include": "*Q4_K_M*.gguf",
        "relative_dir": "bootstrap",
        "filename": "Ornith-1.5-9B-Q4_K_M.gguf",
        "downloadable": True,
        "bundled": True,
        "why": "Always-available local brain for setup, chat, routing, tool use and recovery.",
        "limitations": "Not the preferred model for the hardest coding, deep reasoning, vision or specialist security work.",
    },
    "expert_qwen_27b": {
        "id": "expert_qwen_27b",
        "label": "Qwen 27B · Local Expert",
        "role": "Leader / Senior Worker",
        "repo": "unsloth/Qwen3.5-27B-GGUF",
        "include": "Qwen3.5-27B-Q4_K_M.gguf",
        "relative_dir": "Qwen3.5-27B-GGUF",
        "filename": "Qwen3.5-27B-Q4_K_M.gguf",
        "downloadable": True,
        "bundled": False,
        "why": "Heavier local reasoning/coding escalation when the machine has enough RAM/VRAM.",
        "limitations": "On a 16 GB GPU it may require partial CPU/RAM offload and is slower than the bootstrap model.",
    },
    "blue_redsage": {
        "id": "blue_redsage",
        "label": "RedSage 8B · Blue Team",
        "role": "Blue Team / SOC",
        "repo": "",
        "include": "",
        "relative_dir": "",
        "filename": "",
        "downloadable": False,
        "bundled": False,
        "why": "Cybersecurity-specialized analysis for alerts, telemetry and defensive investigation.",
        "limitations": "Security gate remains locked until the owner configures/unlocks it; the setup interview cannot bypass that gate.",
    },
    "dfir_imperum": {
        "id": "dfir_imperum",
        "label": "Imperum CybersecurityLLM · DFIR",
        "role": "DFIR / Detection Engineering",
        "repo": "",
        "include": "",
        "relative_dir": "",
        "filename": "",
        "downloadable": False,
        "bundled": False,
        "why": "Deeper incident-response, correlation and detection-engineering specialist.",
        "limitations": "Large specialist runtime; configure on demand and keep the existing security password gate authoritative.",
    },
    "red_deephat": {
        "id": "red_deephat",
        "label": "DeepHat 7B · Red Team",
        "role": "Authorized Red Team",
        "repo": "",
        "include": "",
        "relative_dir": "",
        "filename": "",
        "downloadable": False,
        "bundled": False,
        "why": "Optional offensive-security specialist for explicitly authorized assessments.",
        "limitations": "Never auto-enabled. Password plus the existing Red Team authorization/case gate remains mandatory.",
    },
}


def interview_questions() -> list[dict[str, Any]]:
    return [dict(row) for row in QUESTIONS]


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_use(value: Any) -> list[str]:
    text = _text(value)
    intents: list[str] = []
    aliases = {
        "coding": ("code", "coding", "develop", "developer", "software", "program"),
        "research": ("research", "write", "writing", "book", "document", "analyse", "analyze"),
        "security": ("security", "cyber", "soc", "blue team", "red team", "pentest", "monitor"),
        "assistant": ("assistant", "automation", "everyday", "general", "personal", "home"),
        "everything": ("everything", "all", "bit of everything", "anything"),
    }
    for intent, words in aliases.items():
        if any(word in text for word in words):
            intents.append(intent)
    if "everything" in intents:
        return ["assistant", "coding", "research", "security"]
    return intents or ["assistant"]


def _normalize_policy(value: Any) -> str:
    text = _text(value)
    if "only" in text and ("local" in text or "offline" in text):
        return "local-only"
    if "best" in text or "quality" in text or "cloud" in text:
        return "best-result"
    if "cheap" in text or "cost" in text or "budget" in text:
        return "cost-optimized"
    return "local-first"


def _normalize_resources(value: Any) -> tuple[str, int, str]:
    text = _text(value)
    if "25" in text or "light" in text or "low" in text:
        return "custom", 25, "dynamic"
    if "80" in text or "aggressive" in text or "high" in text:
        return "custom", 80, "dynamic"
    if "100" in text or "maximum" in text or "max" in text:
        return "maximum", 100, "static"
    return "dynamic", 50, "dynamic"


def _normalize_voice(value: Any) -> bool:
    text = _text(value)
    return text in {"yes", "y", "true", "1", "on"} or any(word in text for word in ("yes", "voice", "speak", "talk"))


def _installed(model: dict[str, Any]) -> bool:
    relative_dir = str(model.get("relative_dir") or "")
    filename = str(model.get("filename") or "")
    if not relative_dir or not filename:
        return False
    return (models_dir() / relative_dir / filename).exists()


def _model_row(model_id: str, *, status: str, selected: bool, reason: str = "") -> dict[str, Any]:
    row = dict(MODEL_MANIFEST[model_id])
    row["installed"] = _installed(row)
    row["status"] = "installed" if row["installed"] else status
    row["selected"] = selected
    row["reason"] = reason or row["why"]
    return row


def _hardware_summary(hw: HardwareInfo) -> dict[str, Any]:
    try:
        raw = asdict(hw)
    except TypeError:
        raw = {
            "os_name": hw.os_name,
            "cpu_name": hw.cpu_name,
            "cpu_cores": hw.cpu_cores,
            "cpu_threads": hw.cpu_threads,
            "ram_total_gb": hw.ram_total_gb,
            "gpu_name": hw.gpu_name,
            "vram_total_mib": hw.vram_total_mib,
            "disk_free_gb": hw.disk_free_gb,
        }
    return raw


def plan_interview(answers: dict[str, Any] | None = None, hw: HardwareInfo | None = None) -> dict[str, Any]:
    answers = dict(answers or {})
    info = hw or detect_hardware()
    hardware_rec = recommend_from_hardware(info)
    intents = _normalize_use(answers.get("use"))
    policy = _normalize_policy(answers.get("policy"))
    resource_preset, global_percent, resource_mode = _normalize_resources(answers.get("resources"))
    voice = _normalize_voice(answers.get("voice"))

    ram = float(info.ram_total_gb or 0)
    vram_gb = float(info.vram_total_mib or 0) / 1024.0
    has_gpu = bool(info.gpu_name) and vram_gb > 0

    models: list[dict[str, Any]] = [
        _model_row(
            "bootstrap_ornith",
            status="bundled",
            selected=True,
            reason="Jarvis keeps this local bootstrap available regardless of optional downloads.",
        )
    ]

    want_heavy = any(intent in intents for intent in ("coding", "research")) or len(intents) >= 3
    heavy_fit = ram >= 24 and (vram_gb >= 10 or not has_gpu)
    install_expert = bool(want_heavy and heavy_fit and policy != "cost-optimized")
    if want_heavy:
        models.append(
            _model_row(
                "expert_qwen_27b",
                status="recommended download" if install_expert else "optional",
                selected=install_expert,
                reason=(
                    "Your workload benefits from a heavier local Leader and this machine has enough system memory to use it."
                    if install_expert
                    else "Useful for hard local work, but not selected automatically under the current hardware/cost preference."
                ),
            )
        )

    if "security" in intents:
        models.extend(
            [
                _model_row("blue_redsage", status="security-gated", selected=True),
                _model_row("dfir_imperum", status="security-gated", selected=ram >= 32),
                _model_row("red_deephat", status="manual authorization", selected=False),
            ]
        )

    recommended_class = str(hardware_rec.get("recommended_class") or "")
    role_policies = dict(hardware_rec.get("role_policies") or {})
    inference_choice = "local"
    if policy == "best-result" and not has_gpu:
        inference_choice = "remote"
    elif policy == "cost-optimized" and not has_gpu:
        inference_choice = "remote"

    setup_patch = {
        "onboarding_version": ONBOARDING_VERSION,
        "interview_answers": {
            "use": answers.get("use") or "Everyday assistant",
            "policy": answers.get("policy") or "Local first",
            "resources": answers.get("resources") or "Balanced (~50%)",
            "voice": answers.get("voice") if "voice" in answers else "No",
            "intents": intents,
            "routing_policy": policy,
            "voice_enabled": voice,
        },
        "jarvis_role": "standalone",
        "recommended_class": recommended_class,
        "role_policies": role_policies,
        "resource_preset": resource_preset,
        "global_percent": global_percent,
        "resource_mode": resource_mode,
        "inference_choice": inference_choice,
        "inference_profile": "bootstrap",
        "install_expert_27b": install_expert,
        "install_playwright": True,
        "selected_models": [row["id"] for row in models if row.get("selected")],
    }

    download_models = [
        row for row in models
        if row.get("selected") and row.get("downloadable") and not row.get("installed") and not row.get("bundled")
    ]
    bootstrap_missing = not _installed(MODEL_MANIFEST["bootstrap_ornith"])
    if bootstrap_missing:
        # Source/dev installs need a recovery path. Release installers are expected
        # to have the model already copied from the staged payload.
        download_models.insert(0, _model_row("bootstrap_ornith", status="required bootstrap", selected=True))

    reasoning = [
        f"Detected {ram:.0f} GB RAM and {vram_gb:.1f} GB VRAM{f' on {info.gpu_name}' if info.gpu_name else ''}.",
        f"Primary intents: {', '.join(intents)}.",
        f"Routing preference: {policy}; host resource target: {global_percent}%.",
        "Ornith 1.5 9B Q4_K_M remains the local bootstrap/fallback model.",
    ]
    if install_expert:
        reasoning.append("A 27B local expert is selected for harder work and may use RAM offload when it does not fully fit VRAM.")
    if "security" in intents:
        reasoning.append("Security specialists are prepared as gated roles; onboarding does not unlock Red or Blue Team access.")
    if voice:
        reasoning.append("Voice is enabled as a preference; typing remains available everywhere.")

    return {
        "version": ONBOARDING_VERSION,
        "answers": setup_patch["interview_answers"],
        "hardware": _hardware_summary(info),
        "setup_state_patch": setup_patch,
        "recommended_models": models,
        "download_models": download_models,
        "keep_loaded": ["bootstrap_ornith"],
        "routing_policy": policy,
        "reasoning": reasoning,
    }


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_download_script(plan: dict[str, Any]) -> str:
    models = list(plan.get("download_models") or [])
    lines = [
        "#Requires -Version 5.1",
        "# Generated by Jarvis onboarding (RFC-0049). Safe to re-run.",
        "$ErrorActionPreference = 'Stop'",
        "$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\\..')).Path",
        "$Models = Join-Path $Root 'models'",
        "$Python = Join-Path $Root '.venv\\Scripts\\python.exe'",
        "if (-not (Test-Path $Python)) {",
        "  $cmd = Get-Command python -ErrorAction SilentlyContinue",
        "  if (-not $cmd) { throw 'Python is required to download model weights.' }",
        "  $Python = $cmd.Source",
        "}",
        "& $Python -m pip install --quiet --upgrade huggingface_hub",
        "$Hf = Join-Path (Split-Path $Python -Parent) 'hf.exe'",
        "if (-not (Test-Path $Hf)) { $Hf = (Get-Command hf -ErrorAction SilentlyContinue).Source }",
        "if (-not $Hf) { throw 'huggingface_hub installed but hf CLI was not found.' }",
        "$env:HF_XET_HIGH_PERFORMANCE = '1'",
        "",
        "function Install-JarvisModel([string]$Repo, [string]$Include, [string]$Dir, [string]$Canonical) {",
        "  $dest = Join-Path $Models $Dir",
        "  $target = Join-Path $dest $Canonical",
        "  if ((Test-Path $target) -and ((Get-Item $target).Length -gt 0)) { Write-Host \"Already present: $Canonical\"; return }",
        "  New-Item -ItemType Directory -Force -Path $dest | Out-Null",
        "  Write-Host \"Downloading $Repo ($Include)...\" -ForegroundColor Cyan",
        "  & $Hf download $Repo --include $Include --local-dir $dest",
        "  if ($LASTEXITCODE -ne 0) { throw \"Download failed: $Repo\" }",
        "  if (-not (Test-Path $target)) {",
        "    $found = Get-ChildItem -Path $dest -Recurse -File | Where-Object { $_.Name -like $Include } | Select-Object -First 1",
        "    if (-not $found) { throw \"Download completed but no file matched $Include\" }",
        "    if ($found.FullName -ne $target) { Copy-Item -Force $found.FullName $target }",
        "  }",
        "  Write-Host \"Ready: $target\" -ForegroundColor Green",
        "}",
        "",
    ]
    if not models:
        lines.append("Write-Host 'All selected downloadable models are already present.' -ForegroundColor Green")
    else:
        for model in models:
            if not model.get("downloadable"):
                continue
            lines.append(
                "Install-JarvisModel "
                f"{_ps_quote(str(model.get('repo') or ''))} "
                f"{_ps_quote(str(model.get('include') or ''))} "
                f"{_ps_quote(str(model.get('relative_dir') or ''))} "
                f"{_ps_quote(str(model.get('filename') or ''))}"
            )
    lines.extend(["", "Write-Host 'Jarvis model download plan complete.' -ForegroundColor Green", ""])
    return "\r\n".join(lines)


def save_download_script(plan: dict[str, Any]) -> Path:
    folder = data_dir() / "setup"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "download-models.ps1"
    path.write_text(render_download_script(plan), encoding="utf-8")
    return path
