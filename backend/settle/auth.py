"""Authentication and roles.

Users come from SETTLE_USERS (JSON list of {username, name, role, password, approval_limit_cents}) or, if unset, three
demo users (password "demo"). Passwords are kept only as PBKDF2 hashes; tokens are HMAC-SHA256-signed and expire.
The secret is SETTLE_SECRET, or random per process (tokens then end at restart, which is fine for a pilot).

Roles: viewer (read-only) < ar_clerk (operate; approve up to a money limit, never key accounts) < controller (all).
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass

TOKEN_TTL_S = 12 * 3600
ROLES = ("viewer", "ar_clerk", "controller")
RESERVED_ACTORS = ("outcome:", "settle:", "oracle")  # audit actors that mean "the system", never a person
DEMO_USERS = [
    {
        "username": "dana",
        "name": "Dana Whitfield",
        "role": "controller",
        "password": "demo",
        "approval_limit_cents": None,
    },
    {"username": "sam", "name": "Sam Okoro", "role": "ar_clerk", "password": "demo", "approval_limit_cents": 100_000},
    {"username": "vic", "name": "Vic Lindqvist", "role": "viewer", "password": "demo", "approval_limit_cents": 0},
]


@dataclass(frozen=True)
class User:
    username: str
    name: str
    role: str
    approval_limit_cents: int | None  # None = unlimited

    def public(self) -> dict:
        return {
            "username": self.username,
            "name": self.name,
            "role": self.role,
            "approval_limit_cents": self.approval_limit_cents,
        }

    def at_least(self, role: str) -> bool:
        return ROLES.index(self.role) >= ROLES.index(role)


class AuthError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)


class Directory:
    def __init__(self, users: list[dict] | None = None, secret: str | None = None):
        raw = users if users is not None else _users_from_env()
        self._secret = (secret or os.getenv("SETTLE_SECRET") or secrets.token_hex(32)).encode("utf-8")
        self.users: dict[str, User] = {}
        self._pw: dict[str, tuple[bytes, bytes]] = {}
        for u in raw:
            if u.get("role") not in ROLES:
                raise ValueError(f"user {u.get('username')!r}: role must be one of {ROLES}")
            if not u.get("username") or not u.get("password"):
                raise ValueError("every user needs a username and a password")
            if u["username"].lower().startswith(RESERVED_ACTORS):
                raise ValueError(f"username {u['username']!r} is reserved for system actors")
            salt = secrets.token_bytes(16)
            self.users[u["username"]] = User(
                u["username"], u.get("name") or u["username"], u["role"], u.get("approval_limit_cents")
            )
            self._pw[u["username"]] = (salt, _hash(u["password"], salt))

    def login(self, username: str, password: str) -> str:
        rec = self._pw.get(username)
        ok = rec is not None and hmac.compare_digest(_hash(password, rec[0]), rec[1])
        if not ok:
            _hash(password, b"x" * 16) if rec is None else None  # similar timing for unknown users
            raise AuthError(401, "invalid username or password")
        return self._sign({"u": username, "exp": int(time.time()) + TOKEN_TTL_S})

    def _sign(self, claims: dict) -> str:
        body = base64.urlsafe_b64encode(json.dumps(claims, sort_keys=True).encode()).decode().rstrip("=")
        sig = hmac.new(self._secret, body.encode(), hashlib.sha256).hexdigest()
        return f"{body}.{sig}"

    def verify(self, token: str | None) -> User:
        if not token or "." not in token:
            raise AuthError(401, "missing or malformed token")
        body, sig = token.rsplit(".", 1)
        expected = hmac.new(self._secret, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig.encode("utf-8"), expected.encode("utf-8")):
            raise AuthError(401, "invalid token")
        try:
            claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except (ValueError, json.JSONDecodeError) as exc:
            raise AuthError(401, "invalid token") from exc
        if claims.get("exp", 0) < time.time():
            raise AuthError(401, "token expired")
        user = self.users.get(claims.get("u"))
        if user is None:
            raise AuthError(401, "unknown user")
        return user


def _users_from_env() -> list[dict]:
    raw = os.getenv("SETTLE_USERS")
    if not raw:
        if os.getenv("SETTLE_ALLOW_DEMO_USERS", "1") != "1":
            raise ValueError("SETTLE_USERS is not set and demo users are disabled (SETTLE_ALLOW_DEMO_USERS=0)")
        return DEMO_USERS
    users = json.loads(raw)
    if not isinstance(users, list) or not users:
        raise ValueError("SETTLE_USERS must be a non-empty JSON list")
    return users


def check_approval(user: User, amount_cents: int | None, key_account: bool, money_moving: bool) -> None:
    """Separation of duties for human verdicts. Raises AuthError(403) with the reason."""
    if not user.at_least("ar_clerk"):
        raise AuthError(403, f"{user.role} cannot approve decisions")
    if user.role == "controller":
        return
    if key_account and money_moving:
        raise AuthError(403, "money-moving decisions on key accounts need a controller")
    limit = user.approval_limit_cents
    if limit is not None and (amount_cents or 0) > limit:
        raise AuthError(
            403, f"amount ${(amount_cents or 0) / 100:,.2f} exceeds your approval limit ${limit / 100:,.2f}"
        )
