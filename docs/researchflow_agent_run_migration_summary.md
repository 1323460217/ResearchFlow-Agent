# ResearchFlow-Agent Run Migration Summary

> Scope: 03–10B migration and reliability baseline. This document records the
> current repository state; it does not claim exactly-once delivery.

## 1. Migration goals

The migration introduces durable report runs, human-in-the-loop review,
PostgreSQL-backed LangGraph checkpoints, Redis realtime projection, and
Celery start/resume execution while preserving the existing chat, RAG, and
agent paths.

The reliability goal is business-effect idempotency for one report run and one
review action. Celery task-result de-duplication is not a goal and is not
claimed.

## 2. Current architecture

FastAPI creates and reads report runs. PostgreSQL is the source of truth for
run, review, report, evidence, tool-call, and step state. Celery carries only
`run_id` for start/resume tasks. LangGraph executes with a stable
`thread_id`; its checkpoints are stored in PostgreSQL through the existing
synchronous PostgresSaver adapter. Redis stores a version-checked projection
for status reads and realtime updates.

The worker runtime creates a task-scoped async SQLAlchemy engine using
`NullPool` and a task-scoped Redis client. Both are closed within the same
`asyncio.run` lifecycle. The FastAPI process keeps its existing pooled async
session factory.

## 3. Completed stages 03–10B

- 03–05: AgentRun domain model, enums, repositories, services, and migration.
- 06: Report-runs API and persisted request/review state.
- 07: Redis status projection and status repair path.
- 08: Celery start/resume tasks carrying only `run_id`.
- 09: LangGraph HITL interrupt/resume with stable thread identity and
  PostgreSQL checkpoints.
- 10A: real worker and HITL E2E validation.
- 10B: CAS state transitions, review/report idempotency, Redis version gate,
  worker async resource lifecycle, step sequence locking, and read-only stale
  recovery inventory.

## 4. Data tables

- `agent_runs`: durable run identity, status, status version, task identity,
  timestamps, and failure information.
- `agent_run_steps`: traceable node executions, sequence, attempt, and
  checkpoint/trace references.
- `human_reviews`: one pending review per run, review rounds, action, payload,
  and business idempotency key.
- `research_reports`: one report per run with generation status, review action,
  and revision.
- `evidence`: report evidence records with content/locator uniqueness.
- `tool_calls`: tool execution audit records and run-scoped idempotency.
- LangGraph `checkpoints`, `checkpoint_writes`, and `checkpoint_blobs`: durable
  graph state managed by PostgresSaver.

No new ORM field or Alembic migration was added in 10B reliability hardening.

## 5. API list

Under `/api/report-runs`:

- `POST /api/report-runs`
- `GET /api/report-runs/{run_id}`
- `GET /api/report-runs/{run_id}/status`
- `GET /api/report-runs/{run_id}/steps`
- `GET /api/report-runs/{run_id}/pending-review`
- `POST /api/report-runs/{run_id}/resume`

The resume request persists the review before enqueueing the worker. Repeated
submission with the same business key returns the existing review/task result.

## 6. State machine

The principal guarded transitions are:

```text
PENDING -> STARTED -> RUNNING -> WAITING_HUMAN
WAITING_HUMAN -> RESUME_QUEUED -> RESUMED -> RUNNING -> SUCCESS
STARTED/RUNNING/RESUMED -> FAILURE
```

Each guarded transition increments `status_version`. PostgreSQL conditional
updates check the expected previous state and affected-row count. A losing
concurrent request returns the current state instead of running the graph
again.

## 7. Redis projection design

Redis keys use `report_run:{run_id}:status`. The projection contains status,
node, progress, review/task identifiers, updated time, and `status_version`.

`set_run_status_projection_if_newer` uses a Lua script to compare the incoming
version with the stored version atomically. Older versions are rejected;
equal versions are explicitly allowed to overwrite. PostgreSQL remains the
source of truth when Redis is unavailable.

## 8. Celery delivery and business idempotency

The current worker configuration has `acks_late=True`, prefetch 1, and no
automatic retry for `start_report_task` or `resume_report_task`. A task
exception is acknowledged under the current default failure-ack behavior;
worker loss before acknowledgement may cause redelivery. Therefore delivery
is mixed at-most-once/at-least-once behavior, not exactly-once.

Business idempotency is based on:

- start: `report_run_id`;
- resume: `report_run_id + review_id + action`;
- database status CAS and conditional enqueue claim;
- existing uniqueness constraints;
- report-content finalization guard;
- Redis projection version gate.

Celery `task_id` is an operational identifier, not the business idempotency
key. Two task results may both be `SUCCESS` even when only one business graph
execution is admitted.

## 9. LangGraph interrupt/resume flow

Start runs `graph.astream()` with a stable `thread_id`. An interrupt creates or
reuses the pending PostgreSQL `HumanReview` and writes `WAITING_HUMAN` to the
projection. Resume reads the submitted review from PostgreSQL and invokes
`Command(resume=payload)` against the same thread/checkpointer. The database
CAS admits one resume path.

## 10. PostgreSQL checkpointer

The pinned synchronous PostgresSaver remains process-scoped and is accessed
through the existing async adapter, which serializes saver calls in a worker
thread. This preserves the current dependency choice and avoids a LangGraph
major upgrade. The checkpointer is not a substitute for business state CAS.

## 11. Verified scenarios

- Full pytest baseline: `115 passed, 3 skipped`.
- Real duplicate start: one pending review and one interrupted start step.
- Real duplicate resume: one approved review, one resume step, one report with
  `report_revision=1`, and one final Redis state.
- Near-simultaneous API approve: both requests returned the same Celery task
  id and only one enqueue claim was published.
- Redis stale-version write: older projection write was rejected.
- Failure injection: first task failed, second terminal delivery was guarded;
  no duplicate review/report and no cross-event-loop asyncpg error.
- Windows solo worker: task-scoped DB `NullPool` and Redis resources removed the
  reproduced cross-event-loop pool failure.
- Stale recovery tool: dry-run only; current inventory returned no candidates.

## 12. Uncovered scenarios

- Crash between the database enqueue claim and the external Celery publish.
- Crash after `RUNNING` but before graph execution, followed by automated
  recovery. The current recovery tool intentionally does not auto-requeue.
- Broker visibility timeout/redelivery timing under production load.
- Multi-host clock/version skew and equal-version projection races.
- Full production load or worker-loss chaos testing.

## 13. Remaining risks

The database claim and broker publish are not one atomic transaction. Celery
task result state remains non-idempotent. Redis is a cache/projection and may
be stale or unavailable. The pinned LangGraph/checkpoint dependency warning
remains. The reliability tests under `tests/` are currently ignored by the
local `.git/info/exclude` rule, so they can pass locally without appearing in
ordinary Git status or `git diff --stat`.

## 14. Interview explanation

The design separates durable truth from realtime projection: PostgreSQL owns
the state machine and uniqueness constraints, while Redis is a version-checked
read projection. Celery transports only a run id, so duplicate delivery is
handled by database conditional transitions rather than task ids or a first
choice distributed lock. Human review is persisted before resume, and
LangGraph resumes from the same PostgreSQL checkpoint thread. On Windows, the
worker does not reuse loop-bound async resources across `asyncio.run` calls;
it creates and disposes a `NullPool` database engine and Redis client per task.
This yields verified business-effect idempotency for the tested paths, not an
exactly-once guarantee for the underlying broker.
