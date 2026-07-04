"""Person-1 end-to-end smoke test — M2 (real LLM) + M9 (outbox/email + sweep) + M10 (ops).

Runs from the HOST venv against the Docker stack:
    docker compose up -d --build      # brings up postgres, redis, mailpit, api(uvicorn), workers, beat
    make seed                         # creates tenant with widget_key `wk_seed_retail`
    ./.venv/Scripts/python.exe scripts/smoke_e2e.py

Requires .env to have USE_FAKE_LLM=false + a real OPENAI_API_KEY (compose passes them into api).
Prints a PASS/FAIL line per flow and exits non-zero if any flow fails.
"""

from __future__ import annotations

import json
import sys
import time
import uuid

import httpx

BASE = "http://localhost:8000/api/v1"
MP = "http://localhost:8025/api/v1"  # MailPit REST API
SEED_WIDGET_KEY = "wk_seed_retail"
OPS_EMAIL, OPS_PASSWORD = "ops@platform.local", "ops-dev-password"

_results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  |  {detail}" if detail else ""))


def mail_subjects() -> list[str]:
    return [m.get("Subject", "") for m in httpx.get(f"{MP}/messages", timeout=10).json().get("messages", [])]


def wait_for_subject(needle: str, timeout_s: int = 20) -> bool:
    for _ in range(timeout_s):
        time.sleep(1)
        if any(needle in s for s in mail_subjects()):
            return True
    return False


def stream_turn(tok: str, cid: str, client_msg_id: str, content: str, escalate: bool = False):
    """POST one message and collect the SSE events. Returns (answer_text, final_event)."""
    events: list[tuple[str, dict]] = []
    cur = None
    with httpx.Client(timeout=90) as c:
        with c.stream(
            "POST",
            f"{BASE}/conversations/{cid}/messages",
            json={"client_msg_id": client_msg_id, "content": content, "escalate_request": escalate},
            headers={"Authorization": f"Bearer {tok}"},
        ) as r:
            for ln in r.iter_lines():
                if ln.startswith("event: "):
                    cur = ln[7:].strip()
                elif ln.startswith("data: "):
                    events.append((cur, json.loads(ln[6:])))
    answer = "".join(x["text"] for e, x in events if e == "token")
    final = next((x for e, x in events if e == "final"), {})
    return answer, final


def main() -> int:
    # Preconditions: wait until the readiness probe (pings Postgres + Redis) is green, so the
    # first real request doesn't race a freshly-(re)started container's cold connection pool.
    ready = False
    for _ in range(40):
        try:
            if httpx.get(f"{BASE}/readyz", timeout=5).status_code == 200:
                ready = True
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
    if not ready:
        print(f"API not ready at {BASE} — is the stack up? (docker compose up -d --build)")
        return 2
    httpx.delete(f"{MP}/messages", timeout=10)  # clear MailPit inbox for clean assertions

    # M9: signup -> verification email drained to MailPit -------------------
    email = f"owner-{uuid.uuid4().hex[:6]}@acmestore.com"
    su = httpx.post(
        f"{BASE}/auth/signup",
        json={"email": email, "password": "password123", "workspace_name": "Smoke Co", "industry": "retail"},
        timeout=20,
    )
    check("M9 signup", su.status_code == 201, f"status={su.status_code}")
    check("M9 verify email drained", wait_for_subject("Verify"), f"inbox={mail_subjects()}")

    # M2: grounded turn (real gpt-4o-mini) ---------------------------------
    d = httpx.post(f"{BASE}/widget/session", json={"widget_key": SEED_WIDGET_KEY}, timeout=20).json()
    tok, cid = d["session_token"], d["conversation_id"]
    ans, fin = stream_turn(tok, cid, "g1", "What is your return policy?")
    check(
        "M2 grounded (real LLM)",
        (not fin.get("escalate")) and fin.get("retrieval_hits", 0) >= 1,
        f"hits={fin.get('retrieval_hits')} answer={ans.strip()!r}",
    )

    # M2: explicit escalate -> ticket escalated ----------------------------
    _, fin2 = stream_turn(tok, cid, "e1", "I want to talk to a human", escalate=True)
    check(
        "M2 explicit escalate",
        fin2.get("escalate") is True and fin2.get("escalation_reason") == "explicit",
        f"reason={fin2.get('escalation_reason')}",
    )

    # M9: escalation support_notify email drained --------------------------
    check("M9 escalation email drained", wait_for_subject("human agent"), f"inbox={mail_subjects()}")

    # M10: ops login -> negatives -> health -> usage -----------------------
    login = httpx.post(f"{BASE}/ops/login", json={"email": OPS_EMAIL, "password": OPS_PASSWORD}, timeout=20)
    check("M10 ops login", login.status_code == 200, f"status={login.status_code}")
    if login.status_code != 200:
        return _summary()
    op = login.json()["access_token"]
    H = {"Authorization": f"Bearer {op}"}

    bad = httpx.post(f"{BASE}/ops/login", json={"email": OPS_EMAIL, "password": "wrong"}, timeout=20)
    check("M10 wrong password rejected", bad.status_code == 401, f"status={bad.status_code}")

    rej = httpx.get(f"{BASE}/ops/tenants", headers={"Authorization": f"Bearer {tok}"}, timeout=20)
    check("M10 tenant token rejected at /ops", rej.status_code == 403, f"status={rej.status_code}")

    h = httpx.get(f"{BASE}/ops/health", headers=H, timeout=20).json()
    check(
        "M10 health",
        h.get("components", {}).get("postgres") == "ok" and h.get("components", {}).get("redis") == "ok",
        f"dlq={h.get('email_dlq_depth')} retrying={h.get('email_retrying')}",
    )

    u = httpx.get(f"{BASE}/ops/usage", headers=H, timeout=20).json()
    check("M10 usage aggregates real cost", u.get("total_turns", 0) >= 1, f"turns={u.get('total_turns')} cost=${u.get('total_cost_usd')}")

    return _summary()


def _summary() -> int:
    passed = sum(1 for _, ok, _ in _results if ok)
    total = len(_results)
    print(f"\n{'='*48}\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
