# Person-3 — Implementation Plan (Tenancy, Ticketing, Escalation & Agent Ops)

> **Your mission:** you own the **human-operations vertical** — everything from a business signing up and configuring its workspace, through the ticket that every conversation creates, to the moment a human agent takes over and resolves it. Your modules are broad but mostly straightforward CRUD + state management; the *hard* parts are a handful of **concurrency/state-machine traps** (claim races, sweeps, "the AI must stop talking once a human is involved") — and for every one of those, Person-1 hands you a ready-made primitive so you never have to invent the tricky bit yourself.
>
> **Read the master first:** [`00_TEAM_TASK_SPLIT.md`](./00_TEAM_TASK_SPLIT.md). It has the full picture, the phase plan, and the `IMP-*` improvement IDs this file points at. **Source of truth for module details:** `source/IMPLEMENTATION_PLAN.pdf` + `source/END_TO_END_FLOW.pdf`.

---

## Your scope at a glance

| # | Module | Days | What it is |
|---|---|:--:|---|
| **M1** | Tenancy, IAM & Onboarding | 14 | tenants, staff, RBAC, signup/verify/login, widget-key, industry→templates, agent-settings CRUD |
| **M5** | Ticketing & Tags | 11 | one ticket/conversation, lifecycle state machine + AI whitelist, tags approve/pending, reopen |
| **M6** | Escalation | 5 | triggers, hand-off + summary, after-hours capture-email + SLA promise |
| **M7** | Agent Workspace & Presence | 13 | presence, live queue, claim-lock, conversation view, reply/notes/resolve |
| **M10** | Platform Operator (`/ops` endpoints) | ~2 | cross-tenant list/suspend, health, usage — built on Person-1's bypass primitive |
| **FE-Auth** | `features/auth/` | ↴ | `/login` `/signup` `/verify` |
| **FE-Onboarding** | `features/onboarding/` | ↴ | industry picker, template downloads, KB/record upload, config forms, embed snippet + live preview |
| **FE-Staff** | `features/staff/` | 13 (B group) | invite / manage staff (admin only) |
| **FE-Tickets** | `features/tickets/` | ↴ | list + filter/search + detail |
| **FE-AgentWorkspace** | `features/agent-workspace/` | ~11 (D group) | Available/Away, live queue, claim-lock, full-context view, reply/resolve |

**≈ 71 person-days.** Backend ≈ 45, frontend ≈ 24. Broad surface, mostly complexity-3, all contract-fronted.

---

## What Person-1 gives you (build ON these, don't rebuild)

You are **never** allowed to hand-roll a security control or a concurrency primitive. Person-1 delivers these in **Phase 0**; you import them:

| Primitive / contract | You use it for |
|---|---|
| **Auth deps** — `require_auth` (JWT staff → current-staff+tenant), anonymous **widget-key → tenant** resolution, `require_permission(...)` RBAC dep | Gate every `/admin/*`, `/agents/*`, `/tickets/*` endpoint (M1/M5/M7). |
| **RLS/tenant-context harness** — the DB-session dependency issuing `SET LOCAL app.tenant_id`, and the worker `with_tenant(tid)` context manager | Every table you touch is RLS-isolated; you just go through the session dep. Your M9-adjacent sweeps use `with_tenant()`. |
| **Transition-whitelist + guarded-CAS primitive** — `apply_transition(ticket, to, actor)` (does `UPDATE … WHERE state=:expected`) + the `(from, to, allowed_actors[])` table | **Every** M5 ticket state change goes through this. You never write `ticket.state = …` directly. *(See [IMP-TKT-1], [IMP-TKT-2].)* |
| **Outbox primitive** — `core/events.py` "write-outbox-row-in-the-same-transaction" | M6 after-hours emails + M9 sweeps emit through this (never `smtp.send()` inline). |
| **Redis pub/sub pattern** (tenant-scoped channels) | M7 realtime queue push + claim/release deltas. |
| **M10 bypass primitive** — `with platform_bypass(actor, action):` on a dedicated least-privilege connection that auto-writes the audit row | Your `/ops` endpoints call *only* this for cross-tenant reads. *(See [IMP-SEC-9].)* |
| **SSE event protocol** (Pydantic↔TS union) | M7 live queue + the "a human is handling this" canned turn use the same event shapes. |
| **FE-Shell foundation** — typed API client, `useSSE` hook, auth provider + single-flight refresh, RBAC UI gating, design system | Every one of your FE screens mounts into this. You don't build routing/providers/token handling. |
| **`FakeLLM` / MailHog / seed CLI** | Run + test your whole vertical offline, no vendor keys. |

## What you depend on from Person-2

- **The 5 industry record schemas + verify-field metadata** (retail/logistics/telecom/healthcare/travel). M1's `GET /records/templates/{record_type}` renders CSV/JSON **from that single registry** (do **not** define a parallel copy — [drawback found in M1]). These are **frozen in Phase 0**, so this is a contract dependency, *not* a code blocker.

## What you give others

- **Presence read contract** — `is_agent_available(tenant) -> bool` — consumed by M6 (queue-vs-after-hours messaging) and M9 (unclaimed-nudge).
- **Escalation-reason enum [C6]** — `no_grounding | explicit | sensitive | dispute | n_fails | proactive | timeout` — one canonical source (put it in `domain/escalation/`); M2 records it into `turn_metric`, M8 groups by it. `dispute` = deterministic record-state escalations (void warranty / delivered-not-received / cancelled-refund-not-in-KB); `timeout` = the per-turn stall path. *(Agree the exact spelling with Person-1/Person-2 in Phase 0.)*
- **`GET /agents/queue` + the escalation-summary shape** — consumed by FE-AgentWorkspace.
- **Ticket state machine + `GET /tickets/{id}/context`** — consumed by M2 `ticket_ops`, M6, M8, and the agent FE.

---

## Backend modules

> **Golden rule for this whole vertical:** state changes are *events with side effects* (emails, notifications, summaries). If you ever write `ticket.state = X` and then fire a side effect **without** the guarded CAS, you have a bug. Always: *CAS the transition first → if it changed 0 rows, stop and fire nothing.*

### M1 — Tenancy, IAM & Onboarding  *(complexity 4, ~14 d)*

**Purpose:** tenants, staff logins, RBAC, self-signup + email verify, and the guided onboarding wizard (industry → templates → config → embed snippet).

**Folder / files:**
- `services/onboarding_service.py`
- `domain/tenancy/`
- `api/v1/auth.py`, `api/v1/admin.py`
- `infra/db/models/{tenant,staff,role,widget_key,allowed_domain,agent_settings}.py`

**Responsibilities:** signup / verify / login / refresh / logout; role→permission resolution; widget-key + domain allowlist; industry selection → provisions record schema + template downloads; staff invite/manage; agent-settings CRUD (hot-cached).

**APIs:**
- `POST /auth/{signup, verify-email, login, refresh, logout}`
- **`POST /auth/forgot-password`, `POST /auth/reset-password`** ← **add these** (the docs list a "password reset → reset link" email trigger but never expose the endpoint — a dangling contract). Single-use, short-TTL token via the outbox, invalidated on use and on password change.
- `POST/GET/PATCH /admin/staff`
- `POST /admin/widget-key/rotate`
- `GET /records/templates/{record_type}?format=csv|json`
- `GET /admin/embed-snippet`
- `GET/PATCH /admin/settings`

**Contracts you provide:** tenant + staff + agent_settings tables (all on the RLS base); the `agent_settings` object that M2 (persona/languages/threshold/timeouts), M3 (threshold), M4 (verify attempts N), and M6 (triggers/SLA/after-hours) all read at runtime. **Contracts you consume:** Person-1's auth/RLS/RBAC deps + email outbox; Person-2's 5 record schemas.

**Improvements to implement:**
- **[IMP-SEC-3]** (shared w/ P1): the `widget_key` is *public*; treat it as an identifier only. The anonymous `/widget/session` mint + rate-limiting is P1's, but your `widget-key/rotate` must **atomically replace the key and invalidate any cached key→tenant mapping**.
- **agent_settings hot-cache invalidation** (drawback found): a `PATCH /admin/settings` must **write the DB row then delete/update the Redis key `settings:{tenant_id}` in the same unit of work**, with a short TTL as a backstop. Don't leave stale config in cache.
- **RBAC catalog [C5]** (drawback found): seed a **static permission catalog** (enum) via migration and map roles — **`admin` + `agent` only** (+ the M10 platform super-admin); **no `owner` tier** (PRD §5.1.1/§7: the first signup becomes admin, multiple admins allowed). Expose it through Person-1's single `require_permission()` dep — don't invent per-endpoint checks.
- **agent_settings fields to add [A6][A9]:** `welcome_message` (a configurable, customer-visible string the widget renders as its first chrome line — P1/FE-Chat) and a nullable `carrier_url_template` (`https://carrier/track/{tracking_ref}`, consumed by the order flow in P1/M2). Both surface in FE-AgentSettings (P2).
- **Single schema registry** (drawback found): render templates *from* Person-2's `domain/records/` registry; add a test that round-trips a template download against a real schema.

**Gotchas & where you'll get stuck (read this):**
- **Email verification is asynchronous.** Signup writes the tenant + an **outbox row** in the *same transaction*; the M9 worker sends it via MailHog. Your endpoint returns immediately — don't block on SMTP.
- **The industry picker "provisions the record schema."** That means: store the tenant's chosen `industry`, and let M1/M4 derive `record_type`s from it. Don't copy schema definitions into M1.
- **Onboarding is resumable** — see FE-Onboarding below; the backend must expose enough state (`GET /admin/settings`, `GET /knowledge/sources`, `GET /records/datasets`, widget-key presence) for the FE to compute "which step am I on".

---

### M5 — Ticketing & Tags  *(complexity 3, ~11 d — your keystone module)*

**Purpose:** one ticket per conversation, a lifecycle state machine enforced by the AI transition whitelist, tag approval, and reopen.

**Folder / files:**
- `services/ticket_service.py`, `services/tag_service.py`
- `domain/ticketing/` (StateMachine + AI whitelist)
- `domain/tags/`
- `api/v1/tickets.py`

**APIs:**
- `GET /tickets` (list + filter/search)
- `GET/PATCH /tickets/{id}`
- `POST /tickets/{id}/reopen`
- `POST /admin/tags/{id}/approve|reject`
- **`GET /tickets/{id}/context`** ← **add this** ([IMP-FE-8]): returns `{transcript, ai_summary, kb_sources, suggested_reply, linked_record_pointer}` — the aggregated payload the agent workspace needs (M7's own APIs don't expose it).

**The ticket state machine (corrected — this is the version to build):**

```
        ┌─────┐  AI first response (AI)        ┌──────────────┐
        │ new │ ─────────────────────────────► │ ai_handling  │
        └─────┘                                 └──────┬───────┘
                                       trigger fires (AI/system)  │  complete answer /
                                                 │                │  idle 10m (system)
                                                 ▼                ▼
                                          ┌────────────┐    ┌──────────┐
                              agent claims │ escalated  │    │ resolved │
                              (CAS lock)   └─────┬──────┘    └────┬─────┘
                                                 ▼                │ idle 10m (system)
                                          ┌────────────┐          ▼
              agent resolves (agent) ◄─── │ with_agent │      ┌────────┐
                                          └────────────┘      │ closed │
                                                              └───┬────┘
                     reopen: customer msg ≤72h from closed_at     │
   ┌──────────────────────────────────────────────────────────────┘
   ▼   → if the ticket was escalated/with_agent: route back to with_agent
       (reassign the prior agent; → escalated if that agent is now Away)
       → else: route to ai_handling
   ─── customer msg AFTER 72h (or on a session whose ticket is closed): open a FRESH ticket ───
```

- **AI actor whitelist (non-negotiable, enforced in code):** `new→ai_handling`, `ai_handling→resolved`, `ai_handling→escalated` — **and nothing else.**
- **Agent actor:** `escalated→with_agent` (claim, in M7), `with_agent→resolved`, `with_agent→escalated` (release back).
- **System actor:** `ai_handling→resolved` (idle), `resolved→closed` (idle), reopen routing.

**Improvements to implement:**
- **[IMP-TKT-2] Every transition is a guarded CAS.** Use Person-1's `apply_transition(ticket, to, actor)` → `UPDATE ticket SET state=:new WHERE id=:id AND state=:expected`. **0 rows affected = "already taken" → return without firing side effects.** This is what stops the idle-resolve sweep and an incoming message from stomping each other.
- **[IMP-TKT-1] The AI-answer state gate** (co-owned with P1, but you own the M5 side): expose `ticket.state` cleanly so M2 can check it at the top of the message handler. Once a ticket is `escalated`/`with_agent`, the AI must **not** answer.
- **[IMP-TKT-3] Escalate dominates resolve.** If a turn both answers and sets `escalate`, you transition to `escalated`, never `resolved` — and cancel any pending idle-resolve timer for that ticket.
- **[A5] Auto-resolve on a confirmed complete answer.** When M2's structured output sets `answer_complete=true` (P1 owns the flag + the closing question), a **thumbs-up** on that message (feedback endpoint) or a detected **affirmative reply** fires your AI-actor `ai_handling→resolved` guarded CAS. Idle-10m stays the fallback for everyone who just leaves. (§4.2.2 path (a).)
- **[IMP-TKT-4] Reopen anchor + fresh-ticket rule.** Add `resolved_at`, `closed_at`, `last_customer_msg_at`. Reopen is measured from **`closed_at`** (state it). A customer message **after 72h** (or once closed on a live 30-day session) opens a **fresh ticket** — no dead ends. Add `UNIQUE(tenant_id, conversation_id)` and implement create as **get-or-create** (`ON CONFLICT DO NOTHING/RETURNING`) so M2's retry semantics are idempotent. Denormalize **`ticket.language`** (first detected language) so FE-Tickets/M8 can filter without digging into `message.structured_out`.
- **[IMP-TKT-6] Tag approve-flip grain.** Make **`tag_def.status`** the single authoritative approval state (tenant-scoped, `UNIQUE(tenant_id, name)`); `ticket_tag` references `tag_def_id` and derives its displayed approved/pending state. Approving a def is one `UPDATE` that also backfills existing pending `ticket_tag` rows of that name **in the same transaction**. `{id}` in the approve/reject endpoint = a **`tag_def` id**, not a ticket_tag id.
- **[IMP-TKT-5]** The verified `linked_record {type,key}` is recorded per-turn in `message.structured_out` (with P2), not only in the single mutable `ticket.linked_record_*` pointer.
- **[IMP-ESC-6] (storage half):** there is **no home for the escalation summary** in the data model — add an escalation-summary artifact `{transcript_ref, summary, kb_sources, suggested_reply, linked_record_ref}` (reuse the `resolution_summary` table with a `type` discriminator `{escalation|resolution}`). Freeze this shape in Phase 0.
- **Resolution/escalation summary is async** (drawback found): commit the transition + `ticket_event` as authoritative first, then **enqueue** summary generation via the outbox; render "summary pending" until it lands. The summary *text* is generated by M2 (the AI) — you only store it.
- **[C4] `ticket.priority` is a REQUIRED field** `{low, normal, high}` default `normal` — add it to the ticket model; it is **set on escalation per trigger** in M6 (sensitive/dispute → `high`; others → `normal`), per PRD §4.2 + §4.5.1. **Keep** the FE-Tickets `priority` filter — do **not** drop it (it now has a backing column). Supersedes the earlier "drop it" note in [IMP-FE-8].

**Gotchas & where you'll get stuck (WHY it matters):**
- **Why CAS and not read-then-write?** Two things transition tickets: your `PATCH`/message handler *and* the M9 idle sweep. If both read `ai_handling`, decide to act, and then write, you get a **lost update** (e.g., a resolve that swallows an escalation). The `WHERE state=:expected` clause makes the write *conditional*, and "0 rows changed" tells you someone beat you to it — so you can safely skip the side effects.
- **Why does `reopened` need a router?** The diagram draws `reopened` as a state, but it has no outbound edge — it's really "recompute where this goes." Persist `prior_state` + `prior_assignee_id` and route on reopen (back to the prior agent if it was escalated, else to the AI).
- **One ticket per conversation is a *deliberate simplification*.** A 30-day session can accumulate multiple topics onto one ticket. That's acceptable for the POC — just implement the fresh-ticket-after-close rule so it doesn't become a literal dead end.

---

### M6 — Escalation  *(complexity 3, ~5 d)*

**Purpose:** the "no dead ends" safety net — decide *when* to hand off and *how* (live queue vs after-hours).

**Folder / files:** `services/escalation_service.py`, `domain/escalation/` (triggers), config on `agent_settings`.

**Contract you provide:**
- `escalation_service.escalate(escalation_context) -> HandOffResult{mode: queued|after_hours, customer_message, summary_ref}`
- `domain/escalation.evaluate(signals, settings) -> reason|None` + the **escalation-reason enum**.

**Flow (corrected):** a trigger fires → transition `ai_handling→escalated` (via M5's CAS) + persist the AI-written summary → **always enqueue idempotently** → *then* presence decides only the customer-facing message + whether to also fire the after-hours capture-email + SLA + support-notify (all via the outbox).

**Improvements to implement:**
- **[IMP-ESC-3] Always enqueue, regardless of presence.** The docs contradict themselves ("presence check → queue OR capture email" vs "the escalated ticket persists in the queue regardless"). Resolve it: enqueue **every** escalation idempotently; presence is *advisory* for messaging/notification only — **never a gate on queueing.**
- **[A1] Deterministic record-state escalations → reason `dispute`.** M2 emits an escalate signal for `coverage=void`, `status=delivered` + reported non-receipt, and a cancelled-order refund not covered by KB. M6 records these with reason **`dispute`** — they are code-driven, not the model's soft `sensitive` backstop.
- **[A2] Proactive human offer → `proactive`/`explicit`.** When the AI is struggling (approaching the fail cap, or `NO_GROUNDING` with no tool answer), P1/M2 emits *"Would you like me to connect you to a human agent?"* instead of escalating immediately. A customer **"yes"** fires the first-class escalate flag (you record reason **`explicit`**, tagged as originating from a `proactive` offer); a **"no"** continues. This is §4.5's "no sentiment detection" design — you own the reason taxonomy, M2 owns the offer behavior.
- **[C4] Set `ticket.priority` on escalation.** In `escalation_service.escalate()`, set priority from the reason: `sensitive`/`dispute` → **`high`**; everything else → **`normal`** (default).
- **[A15] After-hours email capture.** In the no-agent branch, the escalation `customer_message` **asks for the customer's email**, and a **narrow non-LLM capture path** writes `ticket.contact_email` on the next inbound message *even though the ticket is `escalated`* (or capture it just before flipping state). This is the one exception that must coexist with the [IMP-TKT-1] "AI stops answering once escalated" gate — implement it as a dedicated capture step, not an LLM turn. `contact_email` stays distinct from the verified `linked_record`.
- **[T6] Support-notify = one email per escalation (POC).** Fire a **single** out-of-band support-notification email (via the outbox) on escalation. **Drop the recurring multi-round unclaimed-nudge scheduler** — no `nudge_round` cadence for the POC.
- **[IMP-ESC-5] Sensitive-intent + "talk to a human" (with P1).** The **"talk to a human" button posts a first-class escalate signal** (a boolean flag on the message endpoint), **not** a prefilled text string the model re-interprets — deterministic and cross-language for free. Keep the model's sensitive-intent detection as a *soft backstop* only.
- **[IMP-ESC-4] N-fails counter.** Count **`unverified`** (identity mismatch — the risky one) against Person-2's durable Redis counter keyed `(tenant, record_type, key)` ([IMP-SEC-6]); treat **`not_found`** (benign typo) more leniently. Use two distinct counters: `verify_attempts` vs answer/`stall_retries`.
- **[IMP-ESC-7] After-hours needs a data field.** Add **`ticket.contact_email`** (nullable, format-validated, **kept distinct** from the verified `linked_record`) — without it the M9 "SLA follow-up to customer" email has nothing to send to. Add **`support_notification_email`** to `agent_settings`.
- **Trigger taxonomy is one source of truth** (drawback found): M2 feeds *raw signals* (`grounded:bool`, `verify_attempts:int`, `model_escalate_reason`, `sensitive_intent_hit:bool`) into your pure `evaluate(signals, settings)`. Don't split trigger logic between M2 and M6.
- **Summary generation is M2's, not yours** (drawback found): M6 is **LLM-free**. M2 produces the summary as part of the escalate tool call and passes it inside `escalation_context`. You persist + route it.

**Gotchas:** M6 is *coordination glue* — the hard lifting (LLM summary, ticket FSM, presence, email) lives in M2/M5/M7/M9. Your job is to wire them correctly and keep the trigger logic pure and testable.

---

### M7 — Agent Workspace & Presence  *(complexity 4, ~13 d — the concurrency-heavy one)*

**Purpose:** humans work escalations — presence, a live queue, claim-lock, the full-context conversation view, and reply/resolve.

**Folder / files:** `services/agent_service.py`, `domain/tenancy/` (presence/assignment), `api/v1/agents.py`, Redis pub/sub.

**APIs:** `GET /agents/queue`, `POST /agents/presence`, `POST /tickets/{id}/claim|release|reply|notes`. *(Agent tag/resolve/close route through M5's `PATCH /tickets/{id}` + `/admin/tags` — keep M7's own endpoints to claim/release/reply/notes.)*

**Improvements to implement:**
- **[IMP-ESC-1] Presence needs liveness — not just `logout = Away`.** Back presence with a **Redis key + short TTL (~60s)** set on SSE-connect and refreshed by the agent-workspace SSE connection's heartbeat; a missed refresh auto-flips the agent to `Away` and reconciles `agent_presence`. *(Otherwise a crashed "Available" agent silently disables the after-hours safety net.)*
- **[IMP-ESC-2] Claim = atomic CAS + lease.** `UPDATE ticket SET state='with_agent', assignee=:me WHERE id=:id AND state='escalated' AND assignee IS NULL`. The **loser gets 0 rows → return 409 + current holder**; publish the lock over pub/sub so the loser's open view flips read-only. **Tie the lock to the presence heartbeat** so a dead agent's claim auto-releases (re-queues).
- **Server-side read-only enforcement** (drawback found): **every** M7 write endpoint (`reply`/`notes`/resolve/close) must verify `caller == current ticket_assignment holder` server-side and return 403 otherwise. Read-only is an **authorization check, not a UI state**.
- **[IMP-FE-6] Queue deltas.** Extend the tenant-scoped Redis pub/sub channel to publish **claim/release/resolve** deltas (not just "new escalation") so other agents' queues don't show ghost tickets. **`GET /agents/queue` (derived from ticket state) is the source of truth** on reconnect — pub/sub is only a nudge (fire-and-forget, no delivery guarantee).
- **[IMP-ESC-8] Queue order = FIFO by `escalated_at`;** "wait time" = `now - escalated_at`, **agent-facing only** (never a customer ETA).
- **Live-record re-fetch is a separate staff read path** (drawback found): re-invoke M4's lookup via `ticket.linked_record_{type,key}`, but as an **internal, already-verified staff read** (RLS-scoped) — *not* the customer verify flow. If the record is now `not_found`, show an explicit "record changed/unavailable" state.
- **[IMP-ESC-6] (display half):** the "suggested reply" the agent sees must be **grounding-gated** — if the escalation reason was no-grounding/unverified, omit it and show a fixed label rather than an ungrounded guess.

**Gotchas & where you'll get stuck (WHY):**
- **Why atomic claim?** The queue is broadcast to *all* agents, so two will click Claim near-simultaneously. Without the `WHERE … AND assignee IS NULL` guard, both "win" → two agents work the same ticket. The DB row is the referee: exactly one `UPDATE` changes a row.
- **Why a TTL on presence?** A tab crash or lost network never sends "logout". If presence only flips on explicit logout, a dead agent stays "Available" forever and escalations route into the void. The heartbeat + TTL makes presence reflect *reality*.
- **Why is pub/sub not the source of truth?** Redis pub/sub drops messages if a subscriber is briefly disconnected. So use it to *nudge* the UI, but always let the FE re-derive the real queue from `GET /agents/queue` on (re)connect.

---

### M10 — Platform Operator endpoints  *(complexity 3, ~2 d)*

**Purpose:** the cross-tenant admin surface — you build the **endpoints**; Person-1 owns the **bypass primitive**.

**Folder / files:** `api/v1/ops.py`, a dedicated audited super-admin role.

**APIs:** `GET /ops/{tenants, health, usage}`, `PATCH /ops/tenants/{id}`.

**Improvements to implement:**
- **[IMP-SEC-9] Bypass only via Person-1's primitive.** Every cross-tenant read/mutation goes through `with platform_bypass(actor, action):` — which uses a dedicated least-privilege connection and auto-writes the **append-only `platform_audit_log`** row. You never write raw superuser queries.
- **Operator identity is a separate principal** — require a token with `scope=platform`; **never** accept a tenant-scoped JWT here.
- **`tenant.status ∈ {active, suspended}`** (drawback found): add it to M1's tenant model; **suspension must be rejected at session mint** — the tenant-resolve middleware and M2's `/widget/session` short-circuit a suspended tenant with a 403. Your `PATCH /ops/tenants/{id}` flips this.
- **[IMP-WRK-5]** `GET /ops/health` surfaces the **email DLQ depth + recent send-failure count** (from the outbox/email_log) so a stalled SMTP relay is visible, not silent.
- **`GET /ops/usage` aggregates Person-2's M8 rollups**, not raw `turn_metric` — one source of truth for cost.

**Gotcha:** this is the single most security-critical module by blast radius (it *intentionally* breaches tenant isolation). Keep it tiny and lean entirely on the reviewed primitive. If you're ever tempted to "just connect as superuser," stop and ask Person-1.

---

## Frontend modules

> All of these mount into **FE-Shell** (Person-1). You get the typed API client, the `useSSE` hook, the auth provider (**[IMP-FE-4]** single-flight refresh — you just *consume* it), RBAC UI gating, and the design system. **You do not build routing, providers, or token handling.**

### FE-Auth — `features/auth/` (routes `/login`, `/signup`, `/verify`)
- Render forms; call `login()`/`signup()`/`verify()` from the shell's auth lib. The token lifecycle (access-in-memory, httpOnly refresh, 401→refresh→retry) is **the shell's**, not yours — don't reimplement it.

### FE-Onboarding — `features/onboarding/`
- Industry picker → Download CSV/JSON template buttons → KB/record upload with an **inline validation report** (row errors, missing headers, duplicate keys) → pre-filled agent-config forms → embed snippet + **live widget preview**.
- **Resumable wizard** (drawback found): derive the current step from **server state** (`GET /admin/settings`, `GET /knowledge/sources`, `GET /records/datasets`, widget-key presence) so a refresh doesn't lose progress.
- **Live preview mounts chat-core directly** (Person-1's shared component), **not** the built `widget.js` bundle — decouples the preview from the widget build. Show the copy-paste `<script>` snippet as static text beside it.
- **[IMP-FE-3]** Put an **"Embedding requirements" note beside the snippet** listing the CSP directives a strict-CSP tenant must add: `script-src <widget-origin>`, `connect-src <api-origin>`, `img-src data:`.
- Reuse Person-2's shared `<UploadWithValidation>`/`<IngestionStatus>` components (don't re-implement the upload UI three times).

### FE-Staff — `features/staff/`
- Admin-only invite/manage staff CRUD against `POST/GET/PATCH /admin/staff`. Gate the route with the shell's RBAC (admin only).

### FE-Tickets — `features/tickets/`
- List + filter/search (status / tag / language / date / **priority — see [IMP-FE-8]**) + detail view. Read/render only; low concurrency.

### FE-AgentWorkspace — `features/agent-workspace/` *(the hardest FE you own)*
- Available/Away toggle (drives presence heartbeat over the SSE connection — [IMP-ESC-1]).
- **Live queue via SSE** — keep a queue store keyed by `ticket_id` and **apply claim/release/resolve deltas** ([IMP-FE-6]); re-fetch `GET /agents/queue` on connect/reconnect as the source of truth.
- **Claim-lock:** on claim, flip other agents' open views to **read-only reactively** (via the lock delta); send `lock_version` on reply/PATCH so the server returns 409 on contention ("claimed by X" → re-fetch).
- **Conversation view** via `GET /tickets/{id}/context`: transcript + AI summary + KB sources + **grounding-gated** suggested reply + live record.
- **Live-record panel** is an independent async widget with explicit **loading / ok / stale / unavailable** states that **never blocks the reply composer** (surface M4's status inline).

---

## Your phase-by-phase tasks

### Phase 0 — Foundations & Contracts
- Co-author the **transition-whitelist table + ticket/tag/queue DTOs** + the **escalation-summary shape** + the **escalation-reason enum** with Person-1.
- Scaffold M1 `tenant/staff/role/agent_settings` tables + Alembic migrations **on Person-1's RLS base**.
- Scaffold FE-Auth against the mock client.
- **✅ Checkpoint (team):** RLS two-tenant leak test green; OpenAPI client generates; SSE fixture parses; `docker-compose up` brings the stack with fakes + seed.

### Phase 1 — Walking-skeleton vertical slice
- **M1:** signup/login + session issuance + `agent_settings` read.
- **M5:** create-ticket + guarded-CAS `new→ai_handling→resolved` + resolution-summary **stub**.
- **FE:** FE-Auth login + FE-Onboarding industry pick.
- **✅ Checkpoint (team):** admin logs into the seeded tenant, asks a question in the in-app console, gets a grounded streamed answer with a citation; the ticket transitions `new→ai_handling→resolved`; exactly one `turn_metric` row.

### Phase 2 — Feature build-out
- **M1 full:** RBAC resolution, staff invite, widget-key rotate, template downloads (consuming P2's schemas), embed snippet, hot-cached `agent_settings` CRUD, forgot/reset-password.
- **M5 full:** `tag_def`/`ticket_tag` CAS approve/reject, reopen 72h from `closed_at` + fresh-ticket rule, `GET /tickets/{id}/context`, search/filter, `ticket_event` audit.
- **FE:** FE-Onboarding (full wizard), FE-Staff, FE-Tickets.
- **✅ Checkpoint (team):** full onboarding works; a record lookup returns `ok`/`unverified`/`not_found` **neutrally**; the widget streams on an external test page.

### Phase 3 — Escalation + Agent Workspace + Realtime *(your big phase)*
- **M6:** triggers, presence check, after-hours capture-email + SLA + support-notify via outbox.
- **M7:** presence w/ Redis TTL heartbeat, FIFO-by-`escalated_at` queue, claim = guarded-CAS lock + server-side read-only, reply/notes/resolve, tenant-scoped pub/sub deltas, live-record panel.
- **FE:** FE-AgentWorkspace + FE-AgentSettings escalation config (triggers/sensitive-intent list/SLA text — note the threshold field is P2's).
- **✅ Checkpoint (team):** a no-grounding turn **and** an explicit "talk to human" both escalate; an agent sees the live queue in real time, **claims (2nd agent read-only)**, replies, resolves; after-hours captures an email + notifies support in MailHog.

### Phase 4 — Ops, Workers & Hardening
- **M10:** `/ops` endpoints on Person-1's bypass primitive; **suspension rejected at session mint**.
- Wire the ticketing/escalation **query-driven idempotent scheduled sweeps** ([IMP-WRK-3]) into M9 (with Person-1). Support-notify is a **single** email per escalation ([T6]) — no recurring nudge for the POC.
- **FE:** FE-AgentWorkspace polish (queue deltas, reconnect).
- **✅ Checkpoint (team):** operator suspends a tenant → its chat is rejected; escalation + SLA emails deliver via MailHog with dedupe; all four non-negotiable CI suites green.

---

## Definition of done for your slice
- A business can **sign up, verify email (MailHog), pick an industry, invite staff, configure the agent, and rotate a widget key.**
- Every conversation has exactly one ticket that moves through the lifecycle **only via guarded CAS**, with the AI whitelist enforced and a working reopen/fresh-ticket rule.
- An escalation **always enqueues**, writes a stored summary, and either notifies an online agent in real time **or** captures a contact email + promises an SLA + notifies support.
- An **agent claims a ticket atomically** (a second agent is read-only server-side), reads the full context, replies, and resolves; a crashed agent's presence expires and their claim auto-releases.
- The operator can list/suspend tenants through the **audited bypass**, and a suspended tenant's chat is rejected at session mint.

## How to test offline
- **MailHog** (from Person-1's compose) catches all verification / invite / escalation / SLA emails — assert they land there.
- Use the **seed CLI** (≥2 tenants, ≥2 industries) to test M1 flows and RLS isolation.
- **Simulate two agents racing a claim:** fire two concurrent `POST /tickets/{id}/claim` in a test — assert exactly one gets 200 and the other 409.
- **Simulate the sweep-vs-message race:** transition a ticket to `resolved` via the sweep while posting a message — assert no lost update and no double side-effect.
- Presence: connect an SSE client, kill it, assert the agent flips to `Away` after the TTL and their claimed ticket re-queues.

---

## Watch-outs (read before you start)
1. **Never write ticket state directly.** Always go through Person-1's guarded-CAS `apply_transition(...)`; 0 rows changed = stop, fire nothing.
2. **Escalate dominates resolve** — never resolve a turn that also escalates.
3. **The AI must stop answering once a ticket is `escalated`/`with_agent`** — this is the "no auto-resume" guarantee; the state gate lives at the top of M2's message handler (co-owned with P1).
4. **Presence needs a TTL heartbeat, not just `logout = Away`** — a crashed agent must auto-flip to Away.
5. **Always enqueue an escalation regardless of presence** — presence only decides messaging/notification; fire **one** support-notify email, no recurring nudge ([T6]).
6. **Count `unverified` (not `not_found`) against the durable identity counter** — `not_found` is a benign typo, `unverified` is a possible attacker.
7. **Every M7 write endpoint checks the caller is the current lock holder server-side** — read-only is authorization, not a UI toggle.
8. **Scheduled sweeps must be query-driven + idempotent** (`WHERE due_at <= now()` + CAS + `FOR UPDATE SKIP LOCKED`), never per-ticket delayed tasks — so missed ticks self-correct and nothing double-fires.
9. **`tag_def.status` is the single approval source of truth** — `ticket_tag` derives from it.
10. **`/ops` is a loaded gun** — only ever touch cross-tenant data through the audited `platform_bypass` primitive.
