from __future__ import annotations

from unittest.mock import patch

from app.agent.context_policy import CONTEXT_XL, next_context_size
from app.inference.profiles import PROFILES
from app.inference.ram_policy import (
    CONTEXT_TIER_64K,
    effective_fit_target_mib,
    hardware_context_ceiling,
    ram_supported_context_ceiling,
)


def test_ram_ceiling_64gb_class():
    with patch("app.inference.ram_policy._ram_total_gb", return_value=64.0):
        assert ram_supported_context_ceiling() == CONTEXT_TIER_64K
        cap = hardware_context_ceiling(PROFILES["balanced"])
        assert cap == CONTEXT_TIER_64K


def test_ram_ceiling_small_machine():
    with patch("app.inference.ram_policy._ram_total_gb", return_value=16.0):
        assert ram_supported_context_ceiling() == 32768
        cap = hardware_context_ceiling(PROFILES["balanced"])
        assert cap == 32768


def test_next_context_can_reach_xl_on_large_ram():
    with patch("app.inference.ram_policy._ram_total_gb", return_value=64.0):
        cap = hardware_context_ceiling(PROFILES["balanced"])
        grown = next_context_size(32768, cap, 28000)
        assert grown == CONTEXT_XL


def test_fit_target_scales_with_ram_and_vram():
    with patch("app.inference.ram_policy._ram_total_gb", return_value=64.0):
        with patch("app.inference.ram_policy._vram_total_mib", return_value=16384):
            from app.config import AppSettings

            target = effective_fit_target_mib(AppSettings())
            assert target >= 4096
