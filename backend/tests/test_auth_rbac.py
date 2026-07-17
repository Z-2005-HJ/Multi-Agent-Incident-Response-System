from __future__ import annotations

from app.auth import build_user_scopes, hash_password, issue_user_session_token, verify_password


def test_password_hash_round_trip() -> None:
    password_hash = hash_password("super-secure-password")

    assert password_hash.startswith("pbkdf2_sha256$")
    assert verify_password("super-secure-password", password_hash) is True
    assert verify_password("wrong-password", password_hash) is False


def test_user_role_scopes_are_hierarchical() -> None:
    viewer = build_user_scopes("viewer")
    operator = build_user_scopes("operator")
    approver = build_user_scopes("approver")
    admin = build_user_scopes("admin")

    assert "incident:read" in viewer
    assert viewer < operator
    assert "approval:write" in approver
    assert "tenant:user_admin" in admin


def test_session_token_has_expected_prefix() -> None:
    token = issue_user_session_token()

    assert token.startswith("user_")
    assert len(token) > 20
