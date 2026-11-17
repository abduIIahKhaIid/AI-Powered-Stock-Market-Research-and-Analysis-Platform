"""Sign-in, tokens, per-user rate limits and keeping users' data apart (SCRUM-40)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest

from stock_api import job_events_api, jobs_api
from stock_api.agent import MemoryConversationStore
from stock_api.agent.approvals import ApprovalBroker, ApprovalNotFound
from stock_api.agent.factory import get_approval_broker
from stock_api.auth import (
    MemoryRateLimiter,
    MemoryUserStore,
    current_user,
    get_rate_limiter,
    get_user_store,
    issue_token,
    read_token,
)
from stock_api.auth.ratelimit import WINDOW_SECONDS
from stock_api.auth.tokens import AuthConfigError, TokenError, signing_secret
from stock_api.auth.users import hash_password, validate_new_account, verify_password
from stock_api.config import Settings, get_settings
from stock_api.jobs import JobKind, MemoryJobStore, get_job_store, get_registry
from stock_api.main import app

SECRET = "s" * 40


def settings(**changes: Any) -> Settings:
    base: dict[str, Any] = {
        "auth_enabled": True,
        "jwt_secret": SECRET,
        "rate_limit_chat_per_minute": 2,
        "rate_limit_auth_per_minute": 50,
    }
    return Settings(_env_file=None, **(base | changes))  # type: ignore[call-arg]


class Queue:
    def enqueue(self, job: Any, kind: Any) -> None:
        pass

    def revoke(self, job_id: str) -> None:
        pass


@pytest.fixture
def state() -> dict[str, Any]:
    return {"settings": settings()}


@pytest.fixture
async def client(state: dict[str, Any]) -> AsyncIterator[httpx.AsyncClient]:
    # Real sign-in: drop the local-user override from conftest.py.
    app.dependency_overrides.pop(current_user, None)
    users = MemoryUserStore(scrypt_n=2**12)
    limiter = MemoryRateLimiter()
    store = MemoryJobStore()
    broker = ApprovalBroker(5)
    registry = {"demo": JobKind("demo", "Demo", "analysis", 10, 20, lambda p: p, lambda p, c: None)}
    state.update(users=users, store=store, broker=broker)
    app.dependency_overrides[get_settings] = lambda: state["settings"]
    app.dependency_overrides[get_user_store] = lambda: users
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_job_store] = lambda: store
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[jobs_api.get_queue] = Queue
    app.dependency_overrides[get_approval_broker] = lambda: broker
    app.dependency_overrides[job_events_api.event_source_dependency] = lambda: None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http
    app.dependency_overrides.clear()


async def sign_up(client: httpx.AsyncClient, name: str, password: str = "correct horse") -> str:
    response = await client.post("/auth/register", json={"username": name, "password": password})
    assert response.status_code == 201, response.text
    return str(response.json()["access_token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- passwords and tokens ----------------------------------------------------------------


def test_passwords_are_salted_scrypt_hashes() -> None:
    first, second = hash_password("pw12345678", n=2**12), hash_password("pw12345678", n=2**12)
    assert first != second and first.startswith("scrypt$4096$")
    assert verify_password("pw12345678", first)
    assert not verify_password("pw12345679", first)
    assert not verify_password("pw12345678", "md5$abc")


@pytest.mark.parametrize(
    ("username", "password", "problem"),
    [
        ("alice", "long enough", None),
        ("al", "long enough", "Username"),
        ("bad name", "long enough", "Username"),
        ("alice", "short", "8 to 128"),
        ("alice12345", "ALICE12345", "same as the username"),
    ],
)
def test_new_account_rules(username: str, password: str, problem: str | None) -> None:
    result = validate_new_account(username, password)
    assert (result is None) if problem is None else (result is not None and problem in result)


def test_tokens_round_trip_and_reject_tampering() -> None:
    config = settings()
    token, lifetime = issue_token(config, "u1", "alice")
    assert lifetime == config.jwt_ttl_minutes * 60
    assert read_token(config, token).user_id == "u1"
    with pytest.raises(TokenError):
        read_token(settings(jwt_secret="t" * 40), token)  # signed with another key
    unsigned = jwt.encode({"sub": "u1", "iss": "stock-research-api"}, key="", algorithm="none")
    with pytest.raises(TokenError):
        read_token(config, unsigned)
    past = datetime.now(UTC) - timedelta(hours=2)
    expired = jwt.encode(
        {"sub": "u1", "iss": "stock-research-api", "iat": past, "exp": past + timedelta(hours=1)},
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(TokenError, match="expired"):
        read_token(config, expired)


def test_secret_rules() -> None:
    with pytest.raises(AuthConfigError, match="at least 32"):
        signing_secret(settings(jwt_secret="short"))
    with pytest.raises(AuthConfigError, match="production"):
        signing_secret(settings(jwt_secret="", app_env="production"))
    assert len(signing_secret(settings(jwt_secret=""))) >= 32  # development: random key


# --- the endpoints ---------------------------------------------------------------------


async def test_register_login_and_me(client: httpx.AsyncClient) -> None:
    token = await sign_up(client, "Alice")
    me = await client.get("/auth/me", headers=bearer(token))
    assert me.json() == {"username": "Alice", "auth_enabled": True}

    login = await client.post(
        "/auth/login", json={"username": "alice", "password": "correct horse"}
    )
    assert login.status_code == 200 and login.json()["username"] == "Alice"
    wrong = await client.post("/auth/login", json={"username": "alice", "password": "nope nope"})
    unknown = await client.post("/auth/login", json={"username": "bob", "password": "nope nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()  # no hint which part was wrong

    taken = await client.post(
        "/auth/register", json={"username": "ALICE", "password": "another one"}
    )
    weak = await client.post("/auth/register", json={"username": "carol", "password": "short"})
    assert taken.status_code == 409 and weak.status_code == 422


async def test_protected_endpoints_need_a_valid_token(client: httpx.AsyncClient) -> None:
    for method, path in [
        ("GET", "/analyses"),
        ("GET", "/jobs"),
        ("POST", "/chat"),
        ("GET", "/prices/AAPL"),
        ("POST", f"/approvals/{'0' * 32}"),
    ]:
        response = await client.request(method, path, json={})
        assert response.status_code == 401, path
        assert response.headers["www-authenticate"].startswith("Bearer")
    bad = await client.get("/analyses", headers=bearer("not-a-token"))
    assert bad.status_code == 401
    health = await client.get("/health/live")
    config = await client.get("/auth/config")
    assert health.status_code == 200
    assert config.json() == {"enabled": True, "signup": True, "invite_required": False}


async def test_invite_code_and_closed_signup(
    client: httpx.AsyncClient, state: dict[str, Any]
) -> None:
    state["settings"] = settings(auth_signup_code="letmein")
    body = {"username": "dave", "password": "correct horse"}
    assert (await client.post("/auth/register", json=body)).status_code == 403
    invited = await client.post("/auth/register", json=body | {"invite_code": "letmein"})
    assert invited.status_code == 201
    state["settings"] = settings(auth_allow_signup=False)
    closed = await client.post("/auth/register", json={**body, "username": "erin"})
    assert closed.status_code == 403


async def test_sign_in_can_be_turned_off(client: httpx.AsyncClient, state: dict[str, Any]) -> None:
    state["settings"] = settings(auth_enabled=False)
    assert (await client.get("/analyses")).status_code == 200
    assert (await client.get("/auth/me")).json()["username"] == "local"
    off = await client.post("/auth/login", json={"username": "x", "password": "y"})
    assert off.status_code == 404


async def test_chat_rate_limit_is_per_user(
    client: httpx.AsyncClient, state: dict[str, Any]
) -> None:
    from stock_api import chat as chat_module

    app.dependency_overrides[chat_module.agent_dependency] = lambda: None  # not reached
    alice, bob = await sign_up(client, "alice"), await sign_up(client, "bob1")
    codes = [
        (await client.post("/chat", json={"message": ""}, headers=bearer(alice))).status_code
        for _ in range(3)
    ]
    # The limit (2 a minute) is checked before the body: 2 bad requests, then 429.
    assert codes == [422, 422, 429]
    limited = await client.post("/chat", json={"message": ""}, headers=bearer(alice))
    assert limited.headers["retry-after"].isdigit()
    assert 0 < int(limited.headers["retry-after"]) <= WINDOW_SECONDS + 1
    assert (
        await client.post("/chat", json={"message": ""}, headers=bearer(bob))
    ).status_code == 422


async def test_sign_in_attempts_are_limited_per_address(
    client: httpx.AsyncClient, state: dict[str, Any]
) -> None:
    state["settings"] = settings(rate_limit_auth_per_minute=3)
    body = {"username": "mallory", "password": "guess guess"}
    codes = [(await client.post("/auth/login", json=body)).status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]


def test_memory_rate_limiter_resets_each_window() -> None:
    now = [1000.0]
    limiter = MemoryRateLimiter(clock=lambda: now[0])
    assert [limiter.hit("chat", "u", 2).allowed for _ in range(3)] == [True, True, False]
    now[0] += WINDOW_SECONDS
    assert limiter.hit("chat", "u", 2).allowed


# --- each user sees only their own data -------------------------------------------------


async def test_jobs_and_saved_analyses_belong_to_their_user(
    client: httpx.AsyncClient, state: dict[str, Any]
) -> None:
    alice, bob = await sign_up(client, "alice"), await sign_up(client, "bobby")
    created = await client.post("/jobs", json={"kind": "demo"}, headers=bearer(alice))
    assert created.status_code == 202
    job_id = created.json()["id"]
    state["store"].update(job_id, status="running")
    state["store"].update(job_id, status="succeeded", result={"ok": True})

    assert (await client.get(f"/jobs/{job_id}", headers=bearer(alice))).status_code == 200
    for path in (f"/jobs/{job_id}", f"/jobs/{job_id}/result", f"/jobs/{job_id}/events"):
        assert (await client.get(path, headers=bearer(bob))).status_code == 404, path
    cancel = await client.post(f"/jobs/{job_id}/cancel", headers=bearer(bob))
    assert cancel.status_code == 404
    mine = await client.get("/analyses", headers=bearer(alice))
    theirs = await client.get("/analyses", headers=bearer(bob))
    assert [a["id"] for a in mine.json()] == [job_id] and theirs.json() == []


async def test_only_the_owner_can_decide_an_approval(
    client: httpx.AsyncClient, state: dict[str, Any]
) -> None:
    alice, bob = await sign_up(client, "alice"), await sign_up(client, "bobby")
    alice_id = read_token(state["settings"], alice).user_id
    broker: ApprovalBroker = state["broker"]
    request = broker.open("c" * 32, "run_python_analysis", {}, "Runs code.", owner=alice_id)
    denied = await client.post(
        f"/approvals/{request.id}", json={"decision": "approve"}, headers=bearer(bob)
    )
    assert denied.status_code == 404 and request.status == "pending"
    ok = await client.post(
        f"/approvals/{request.id}", json={"decision": "approve"}, headers=bearer(alice)
    )
    assert ok.status_code == 200 and request.status == "approved"
    with pytest.raises(ApprovalNotFound):
        broker.decide(broker.open("c" * 32, "x", {}, "r", owner="u1").id, True, owner="u2")


async def test_conversations_are_kept_per_user() -> None:
    from fakes import scripted_gateway, text_turn

    from stock_api.agent import Agent

    store = MemoryConversationStore()

    class NoTools:
        async def __aenter__(self) -> Any:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def list_tools(self) -> list[Any]:
            return []

        async def call(self, name: str, arguments: dict[str, Any]) -> Any:
            raise AssertionError("no tools")

    gateway, llm = scripted_gateway(text_turn("Noted."), text_turn("Hello."))
    agent = Agent(gateway, NoTools, store)
    conversation = "c" * 32
    async for _ in agent.run("My secret plan is X.", conversation_id=conversation, owner="u1"):
        pass
    async for _ in agent.run("What did I say?", conversation_id=conversation, owner="u2"):
        pass
    second_prompt = " ".join(str(m.get("content")) for m in llm.requests[1]["messages"])
    assert "secret plan" not in second_prompt


@pytest.fixture(autouse=True)
def _restore_settings() -> Iterator[None]:
    yield
    app.dependency_overrides.pop(get_settings, None)
