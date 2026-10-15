"""Regression coverage for the pre-wizard shutdown and real PowerShell selection."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_shutdown_runs_before_inno_startup_mutex_check():
    text = (ROOT / 'installer/windows/Jarvis.iss').read_text(encoding='utf-8')
    initialize = text.split('function InitializeSetup: Boolean;', 1)[1].split('procedure InitializeWizard;', 1)[0]
    assert initialize.index('ExtractInstallerHelpers;') < initialize.index('StopAnzuAtSetupStartup')
    assert initialize.index('DetectExistingInstallation;') < initialize.index('StopAnzuAtSetupStartup')
    assert 'Result := False;' in initialize.split('StopAnzuAtSetupStartup', 1)[1]
    assert 'AppMutex=Local\\ANZU' in text


def test_powershell_process_selection():
    shell = shutil.which('powershell.exe')
    if not shell:
        pytest.skip('Windows PowerShell required')
    result = subprocess.run([
        shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-File', str(ROOT / 'tests/windows/installer-process-identity.ps1'),
        '-Source', str(ROOT / 'installer/windows/force-stop-jarvis.ps1'),
    ], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASS:' in result.stdout
