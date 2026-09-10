from app.tools.base import RiskLevel
from app.tools.safety import classify_command, is_destructive_operation, needs_confirmation, resolve_allowed_path


def test_only_destructive_operations_require_confirmation():
    assert classify_command("format C:") == RiskLevel.IRREVERSIBLE
    assert needs_confirmation("autonomous", RiskLevel.LOW, "format D:") is True
    assert needs_confirmation("autonomous", RiskLevel.MEDIUM, "dir") is False
    assert needs_confirmation("trusted", RiskLevel.HIGH, None) is False
    assert needs_confirmation("interactive", RiskLevel.MEDIUM, None) is False
    assert is_destructive_operation("filesystem", {"action": "delete", "path": "x"}) is True
    assert is_destructive_operation("filesystem", {"action": "write", "path": "x"}) is False
    assert is_destructive_operation("terminal", {"command": "Remove-Item x.txt"}) is True


def test_allowed_path_enforced(tmp_path):
    allowed = [str(tmp_path)]
    inside = resolve_allowed_path(str(tmp_path / "a.txt"), allowed)
    assert inside == (tmp_path / "a.txt").resolve()
    try:
        resolve_allowed_path("/etc/passwd", allowed)
        raise AssertionError("expected PermissionError")
    except PermissionError:
        pass
