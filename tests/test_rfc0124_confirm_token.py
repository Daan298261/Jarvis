"""RFC-0124 confirm token validation."""

from app.installer.confirm_token import issue_confirm_token, verify_confirm_token


def test_confirm_token_round_trip():
    roots = [r"C:\Users\owner\AppData\Local\Jarvis"]
    token, exp = issue_confirm_token(roots)
    assert exp > 0
    assert verify_confirm_token(token, roots) is None


def test_confirm_token_rejects_mismatched_roots():
    roots = [r"C:\Users\owner\AppData\Local\Jarvis"]
    token, _ = issue_confirm_token(roots)
    assert verify_confirm_token(token, [r"D:\other"]) is not None


def test_confirm_token_rejects_missing_final_ack():
    roots = [r"C:\Users\owner\AppData\Local\Jarvis"]
    token, _ = issue_confirm_token(roots)
    assert verify_confirm_token("", roots) is not None
