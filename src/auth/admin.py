"""Admin gate — checks the ``is_admin`` column on the User row.

Set a user as admin via the admin dashboard (Users tab → toggle) or
directly in the database:

    UPDATE users SET is_admin = true WHERE email = 'you@example.com';

``require_admin`` is a FastAPI dependency used on all operator-only routes.
It builds on ``get_current_user`` so the same auth flow (bearer token /
dev mode) applies.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status

from src.auth.dependencies import get_current_user
from src.database.models import User


def is_admin(user: User) -> bool:
    """True iff the user's ``is_admin`` DB column is set."""
    return bool(user and user.is_admin)


def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Dependency: 403 when the caller is not an admin.

    Returns the resolved user so handlers can log who did what.
    """
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin access required",
        )
    return current_user
