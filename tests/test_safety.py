from app.tools.base import RiskLevel
from app.tools.safety import classify_command, needs_confirmation, resolve_allowed_path


def test_irreversible_commands_are_blocked_in_autonomous():
    assert classify_command("format C:") == RiskLevel.IRREVERSIBLE
    assert needs_confirmation("autonomous", RiskLevel.LOW, "format D:") is True
    assert needs_confirmation("autonomous", RiskLevel.MEDIUM, "dir") is False
    assert needs_confirmation("trusted", RiskLevel.HIGH, None) is True
    assert needs_confirmation("interactive", RiskLevel.MEDIUM, None) is True


def test_allowed_path_enforced(tmp_path):
    allowed = [str(tmp_path)]
    inside = resolve_allowed_path(str(tmp_path / "a.txt"), allowed)
    assert inside == (tmp_path / "a.txt").resolve()
    try:
        resolve_allowed_path("/etc/passwd", allowed)
        raise AssertionError("expected PermissionError")
    except PermissionError:
        pass
