"""Tests for the Personal Access Token (PAT) CRUD endpoints + the
``get_current_user`` PAT branch.

Coverage:

- Create returns plaintext **once** with the right shape
- Created token authenticates against an existing JWT-only endpoint
- Listing never includes the plaintext secret
- Listing returns newest first
- Revoke is idempotent and revoked tokens 401 on use
- Expired tokens 401 on use
- Malformed PAT-shaped credentials 401 (don't fall through to JWT decode)
- Token row is owned by user — another user can't list/revoke it
- ``last_used_at`` is updated by a successful auth
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_token(client, auth_headers, name="MacBook Claude", **kwargs):
    payload = {"name": name, **kwargs}
    response = client.post("/auth/tokens", json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    return response.json()


def _pat_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestTokenCreate:
    def test_create_returns_plaintext_once_with_prefix(self, client, auth_headers):
        body = _create_token(client, auth_headers)
        assert "token" in body
        plaintext = body["token"]
        # Layout: vm_pat_<8 hex>_<32 hex secret>. Secret is hex precisely so
        # there are no underscores inside it and the parser can rely on a
        # bounded split.
        assert plaintext.startswith("vm_pat_"), plaintext
        parts = plaintext.split("_", 3)
        assert len(parts) == 4, plaintext
        assert parts[0] == "vm" and parts[1] == "pat"
        assert len(parts[2]) == 8
        assert len(parts[3]) == 32
        # Hex chars only — no underscore, no base64 punctuation.
        assert all(c in "0123456789abcdef" for c in parts[2])
        assert all(c in "0123456789abcdef" for c in parts[3])

        assert body["prefix"] == f"vm_pat_{parts[2]}"
        assert body["name"] == "MacBook Claude"
        assert body["scopes"] == ["read"]
        assert body["revoked_at"] is None
        assert body["expires_at"] is None

    def test_create_with_scopes_normalizes_input(self, client, auth_headers):
        body = _create_token(
            client,
            auth_headers,
            name="multi-scope",
            scopes=["WRITE", "read", "read", "  admin "],
        )
        assert body["scopes"] == ["write", "read", "admin"]

    def test_create_rejects_invalid_scope(self, client, auth_headers):
        response = client.post(
            "/auth/tokens",
            json={"name": "x", "scopes": ["lolwut"]},
            headers=auth_headers,
        )
        assert response.status_code == 400
        # Errors are wrapped in the project's standard envelope:
        #   {"error": {"code": "bad_request", "message": "..."}}
        body = response.json()
        assert "scope" in body["error"]["message"].lower()

    def test_create_with_expiry_sets_expires_at(self, client, auth_headers):
        before = datetime.utcnow()
        body = _create_token(
            client, auth_headers, name="short-lived", expires_in_days=30
        )
        assert body["expires_at"] is not None
        # Pydantic returns ISO string; parsing with fromisoformat avoids
        # extra deps. Within a generous 5-minute window of "now + 30d".
        expires = datetime.fromisoformat(body["expires_at"])
        delta = expires - before
        assert timedelta(days=29, hours=23) <= delta <= timedelta(days=30, hours=1)

    def test_create_requires_auth(self, client):
        response = client.post("/auth/tokens", json={"name": "no auth"})
        assert response.status_code == 401

    def test_create_rejects_blank_name(self, client, auth_headers):
        response = client.post(
            "/auth/tokens", json={"name": ""}, headers=auth_headers
        )
        assert response.status_code == 422

    def test_create_persists_hashed_secret_not_plaintext(
        self, client, auth_headers, db_session
    ):
        from src.database.models import PersonalAccessToken

        body = _create_token(client, auth_headers, name="hash-check")
        plaintext = body["token"]
        secret = plaintext.split("_", 3)[3]

        row = (
            db_session.query(PersonalAccessToken)
            .filter(PersonalAccessToken.prefix == body["prefix"])
            .first()
        )
        assert row is not None
        assert row.token_hash != secret
        assert row.token_hash != plaintext
        assert row.token_hash == hashlib.sha256(secret.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Auth-with-PAT (the path that makes the MCP server work)
# ---------------------------------------------------------------------------


class TestAuthenticateWithPAT:
    def test_pat_authenticates_a_jwt_protected_endpoint(
        self, client, auth_headers, test_user
    ):
        body = _create_token(client, auth_headers, name="for /auth/me")
        # /auth/me uses get_current_user — same dependency every other
        # protected endpoint uses. If this works, the PAT can call any
        # of them.
        response = client.get("/auth/me", headers=_pat_headers(body["token"]))
        assert response.status_code == 200
        assert response.json()["email"] == test_user["email"]

    def test_revoked_pat_is_rejected(self, client, auth_headers):
        body = _create_token(client, auth_headers, name="to revoke")
        token = body["token"]

        # First call works
        assert client.get("/auth/me", headers=_pat_headers(token)).status_code == 200

        # Revoke
        revoke = client.delete(
            f"/auth/tokens/{body['id']}", headers=auth_headers
        )
        assert revoke.status_code == 204

        # Now 401
        response = client.get("/auth/me", headers=_pat_headers(token))
        assert response.status_code == 401
        assert "invalid" in response.json()["error"]["message"].lower()

    def test_expired_pat_is_rejected(
        self, client, auth_headers, db_session
    ):
        from src.database.models import PersonalAccessToken

        body = _create_token(client, auth_headers, name="will expire")
        token = body["token"]

        # Backdate the expiry past now
        row = (
            db_session.query(PersonalAccessToken)
            .filter(PersonalAccessToken.id == body["id"])
            .first()
        )
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db_session.commit()

        response = client.get("/auth/me", headers=_pat_headers(token))
        assert response.status_code == 401

    def test_malformed_pat_shaped_credential_is_rejected(self, client):
        # Right prefix, wrong shape — must NOT fall through to JWT decode.
        # If it did, the response would look like "Invalid or expired token"
        # via the JWT branch; we want the PAT 401 instead.
        response = client.get(
            "/auth/me", headers=_pat_headers("vm_pat_garbage")
        )
        assert response.status_code == 401

    def test_unknown_pat_is_rejected(self, client):
        # Right format, secret never minted — must 401.
        response = client.get(
            "/auth/me",
            headers=_pat_headers("vm_pat_deadbeef_" + "a" * 32),
        )
        assert response.status_code == 401

    def test_successful_auth_updates_last_used_at(
        self, client, auth_headers, db_session
    ):
        from src.database.models import PersonalAccessToken

        body = _create_token(client, auth_headers, name="last-used touch")
        # last_used_at starts null
        row = (
            db_session.query(PersonalAccessToken)
            .filter(PersonalAccessToken.id == body["id"])
            .first()
        )
        assert row.last_used_at is None

        before = datetime.utcnow()
        response = client.get("/auth/me", headers=_pat_headers(body["token"]))
        assert response.status_code == 200

        db_session.expire_all()
        row = (
            db_session.query(PersonalAccessToken)
            .filter(PersonalAccessToken.id == body["id"])
            .first()
        )
        assert row.last_used_at is not None
        # Should be very recent (within a few seconds of the request)
        assert row.last_used_at >= before - timedelta(seconds=2)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class TestTokenList:
    def test_list_never_returns_plaintext(self, client, auth_headers):
        body = _create_token(client, auth_headers, name="secret-check")
        full_plaintext = body["token"]

        response = client.get("/auth/tokens", headers=auth_headers)
        assert response.status_code == 200
        listing = response.json()
        assert len(listing) == 1
        row = listing[0]
        assert "token" not in row
        # The prefix is fine — it's deliberately public. The secret
        # half must never appear anywhere.
        secret_half = full_plaintext.split("_", 3)[3]
        assert secret_half not in json.dumps(row)

    def test_list_returns_newest_first(self, client, auth_headers):
        first = _create_token(client, auth_headers, name="first")
        second = _create_token(client, auth_headers, name="second")
        third = _create_token(client, auth_headers, name="third")

        listing = client.get("/auth/tokens", headers=auth_headers).json()
        assert [r["name"] for r in listing] == ["third", "second", "first"]
        assert [r["id"] for r in listing] == [third["id"], second["id"], first["id"]]

    def test_list_includes_revoked_with_timestamp(self, client, auth_headers):
        body = _create_token(client, auth_headers, name="revoked")
        client.delete(f"/auth/tokens/{body['id']}", headers=auth_headers)

        listing = client.get("/auth/tokens", headers=auth_headers).json()
        assert len(listing) == 1
        assert listing[0]["revoked_at"] is not None

    def test_list_empty_when_no_tokens(self, client, auth_headers):
        response = client.get("/auth/tokens", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []

    def test_list_requires_auth(self, client):
        response = client.get("/auth/tokens")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Revoke
# ---------------------------------------------------------------------------


class TestTokenRevoke:
    def test_revoke_returns_204(self, client, auth_headers):
        body = _create_token(client, auth_headers, name="bye")
        response = client.delete(
            f"/auth/tokens/{body['id']}", headers=auth_headers
        )
        assert response.status_code == 204

    def test_revoke_is_idempotent(self, client, auth_headers):
        body = _create_token(client, auth_headers, name="bye-bye")
        first = client.delete(
            f"/auth/tokens/{body['id']}", headers=auth_headers
        )
        second = client.delete(
            f"/auth/tokens/{body['id']}", headers=auth_headers
        )
        assert first.status_code == 204
        assert second.status_code == 204

    def test_revoke_unknown_id_404s(self, client, auth_headers):
        response = client.delete("/auth/tokens/999999", headers=auth_headers)
        assert response.status_code == 404

    def test_revoke_requires_auth(self, client):
        response = client.delete("/auth/tokens/1")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Ownership isolation
# ---------------------------------------------------------------------------


class TestTokenOwnership:
    @pytest.fixture
    def second_user_headers(self, db_session) -> dict:
        from src.auth.jwt import create_access_token
        from src.auth.password import hash_password
        from src.database.models import User

        user = User(
            email="other@example.com",
            password_hash=hash_password("otherpassword123"),
            name="Other User",
            plan="free",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        token = create_access_token(user.id, user.email)
        return {"Authorization": f"Bearer {token}"}

    def test_user_cannot_see_other_users_tokens(
        self, client, auth_headers, second_user_headers
    ):
        _create_token(client, auth_headers, name="mine")
        mine_listing = client.get("/auth/tokens", headers=auth_headers).json()
        theirs_listing = client.get("/auth/tokens", headers=second_user_headers).json()
        assert len(mine_listing) == 1
        assert theirs_listing == []

    def test_user_cannot_revoke_other_users_token(
        self, client, auth_headers, second_user_headers
    ):
        body = _create_token(client, auth_headers, name="mine")
        # Attempt to revoke as the other user — should 404 (we surface
        # not-found rather than 403 to avoid leaking that the id exists).
        response = client.delete(
            f"/auth/tokens/{body['id']}", headers=second_user_headers
        )
        assert response.status_code == 404
