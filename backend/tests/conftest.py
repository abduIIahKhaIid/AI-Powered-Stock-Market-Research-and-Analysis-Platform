"""Shared test setup: API tests run as the local user with an in-memory rate limiter.

Sign-in itself is tested in test_auth.py, which removes these overrides.
"""

from collections.abc import Iterator

import pytest

from stock_api.auth import LOCAL_USER, MemoryRateLimiter, current_user, get_rate_limiter
from stock_api.main import app


@pytest.fixture(autouse=True)
def signed_in_locally() -> Iterator[None]:
    app.dependency_overrides[current_user] = lambda: LOCAL_USER
    app.dependency_overrides[get_rate_limiter] = MemoryRateLimiter
    yield
    app.dependency_overrides.pop(current_user, None)
    app.dependency_overrides.pop(get_rate_limiter, None)
