# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Telegram bot (aiogram 3, long polling) selling time-limited VIP memberships to a private Telegram music group. Payment is bank transfer verified by polling a third-party bank-history API (sieuthicode); on match the bot extends the subscription and hands out a single-use group invite link. Admin surface is entirely inside Telegram. Python 3.12 + PostgreSQL (14 in production), async throughout, no Docker (systemd on the VPS per `projectPlan/03-*.md`).

User-facing strings are bilingual Vietnamese/English HTML in `app/messages/templates.py`; admin strings are Vietnamese inline in `app/handlers/admin.py`.

## Commands

```bash
python -m venv venv && venv\Scripts\activate     # Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                              # then fill in real values

alembic upgrade head                              # apply migrations
alembic revision --autogenerate -m "description"  # see Alembic gotcha below
alembic downgrade -1

python main.py                                    # run the bot (long polling + scheduler)
```

No test suite, linter, or formatter is configured. Manual test cases live in `projectPlan/04-testcase-mvp.md`.

Scheduler jobs can be exercised without waiting for their cron slot: `/testkick` (admin-only) runs `_kick_expired_users` immediately; the report jobs are the same code path as the `/baocao` command and the report buttons in `/admin`.

## Architecture

Single process, single event loop. `main.py` builds the `Bot`/`Dispatcher`, registers `DbSessionMiddleware`, includes five routers, and starts an `AsyncIOScheduler` alongside `dp.start_polling`.

### Three ways a DB session is obtained

This is the thing to get right before touching any handler:

1. **`DbSessionMiddleware`** (`app/middleware.py`) is registered on `dp.message` and `dp.callback_query` only. It injects `session` and **commits after the handler returns** (rolls back on exception). Handlers that receive `session: AsyncSession` should not commit; use `await session.flush()` when they need a generated PK (see `cb_plan_selected` needing `order.id`).
2. **`chat_member` handlers get no session** — `app/handlers/group_events.py` takes none, by design. Adding DB work there means registering the middleware on `dp.chat_member` or opening a session manually.
3. **Background code opens its own** `AsyncSessionLocal()` and commits explicitly: scheduler jobs (incl. `check_payments`), `confirm_order_payment`, `_notify_admins_new_order`, and the admin FSM handlers in `admin.py` that mutate rows (they intentionally bypass the injected session so their commit boundary is their own).

### Payment flow (the core path)

`app/handlers/renewal.py` → `app/utils/payment.py`:

1. User picks a plan → any existing `pending` orders for that user become `cancelled` (conditional `UPDATE`, never overwrites `paid`).
2. An `Order` is created with `order_code = "VIP" + uuid4().hex[:8].upper()`, `transfer_description = "{telegram_id} {username_or_id} {order_code}"` and `expires_at = now + ORDER_EXPIRY_HOURS`. Admins are notified via a fire-and-forget task.
3. If bank + sieuthicode config is present, a VietQR image is fetched from `img.vietqr.io` and sent as a photo; otherwise the bot falls back to `Msg.PAYMENT_INSTRUCTIONS` text. Since ~2026-10 vietqr.io redirects to **SVG**, which `generate_vietqr_image` rasterizes with `resvg-py` (Linux needs a font package, e.g. `fonts-dejavu-core`, or the name/amount text is dropped). Payment detection does not depend on this step.
4. **Detection is the `check_payments` scheduler job**, not per-order tasks. Every `PAYMENT_POLL_INTERVAL_SECONDS` it loads all orders in `CONFIRMABLE_STATUSES` (`pending`/`cancelled`/`expired`) with `expires_at > now`; if any exist it calls sieuthicode **once** and matches each: type `IN`, amount equals `order.amount` exactly, `order_code` in the description, and `transactionID` not already stored on another order (unique index, migration `004`). No baseline snapshot — the order code is the unique key. A user who pays an old QR after switching plan, or pays late, is still confirmed within the window.
5. On match: `confirm_order_payment` locks the order row (`SELECT … FOR UPDATE`), calls `activate_subscription` — which sets `paid` and **stacks days onto the user's existing active subscription in place** (`expires_at += plan["days"]`, `plan_code` overwritten); only a user with no active sub gets a new `Subscription` — stores `transaction_id`, creates a single-use invite link (`member_limit=1`, `INVITE_LINK_TTL_SECONDS`) and the user is DM'd.
6. `pending` orders past `expires_at` become `expired` (conditional `UPDATE`); the user is DM'd only if it lapsed within the last hour, so a deploy/downtime backlog expires silently.
7. If sieuthicode fails (HTTP error, or a body whose `status` is not `success` — an expired cookie still returns 200) for 3+ minutes, admins get one alert and a recovery message later. Health is only probed while orders are open.

All state is in the DB, so a restart loses nothing. Admin "Confirm đơn" (`fsm_confirm_order`) calls the same `confirm_order_payment`, so the job and an admin confirming at the same moment activate the order exactly once. `tests/test_payment_match.py` is an assert-based self-check for the matcher (`python -m tests.test_payment_match`, needs `.env`).

`qr_example.py` is a standalone prototype of the matching logic, kept as reference — nothing imports it. The production version is `app/utils/payment.py`.

### Plans are database rows, not config

Plans live in the `plans` table and are read through `app/utils/plan_loader.py` (`get_plan`, `get_visible_plans` for user keyboards, `get_all_plans` for admin). Admins do full CRUD from `/admin` → "Quản lý gói"; codes are derived with `slugify(name)` and de-duplicated by appending `_{days}`. Deleting a plan is blocked while active subscriptions reference it — hiding (`is_visible`) is the intended alternative. `plan_code` is a plain string, not an FK, so subscriptions survive plan deletion; `"gift"` is used for admin-granted days and matches no plan row (lookups fall back to `plan_code` as the display name).

**`PLANS` in `app/config.py` is dead legacy** — it was the pre-migration-003 source of truth and is no longer read anywhere. Migration `003` seeded the same four plans into the table. Don't add plan data there.

### Scheduler jobs (`app/scheduler.py`)

- `check_payments` — every `PAYMENT_POLL_INTERVAL_SECONDS` (`max_instances=1`, `coalesce=True`). See payment flow step 4. APScheduler's per-run executor INFO lines are silenced in `main.py` to keep journald readable.
- `expiry_reminders` — daily 08:00 local. Two windows (60–84h out = D-3, 12–36h out = D-1), each guarded by a per-subscription flag (`d3_reminder_sent` / `d1_reminder_sent`) so reruns don't double-send.
- `kick_expired` — every 30 min. Kick = `ban_chat_member` then immediate `unban_chat_member` so the user can rejoin after buying again; marks `is_active = False`.
- `report_daily` / `report_weekly` — pushed to every admin ID.

Reminder flags are never reset, so a stacked renewal keeps the flags of the extended subscription and will not re-trigger those reminders for the new period.

### Admin authorization

`settings.admin_id_list` (comma-separated `ADMIN_IDS`, Telegram user IDs — never usernames). Every callback re-checks `_is_admin` itself; there is no router-level filter, so a new admin callback must add its own check. All mutations write an `AuditLog` row. FSM state handlers use the `_not_command` filter so a user typing `/start` mid-flow escapes the state instead of having it parsed as input.

### Time handling

Application code writes timezone-aware UTC (`datetime.now(timezone.utc)`) into `DateTime(timezone=True)` columns. APScheduler triggers use `settings.TIMEZONE` (Asia/Ho_Chi_Minh), and `app/utils/report.py` computes day/week/month boundaries in **UTC**, so "today" in a report is a UTC day while the job fires at 08:00 local. `app/utils/invite.py` uses naive `datetime.now()` for the invite expiry timestamp.

## Gotchas

- **`alembic/env.py` does not import `app.models.plan`.** Its metadata is therefore missing the `plans` table, and `--autogenerate` will emit a `drop_table("plans")`. Add the import (alongside the existing `User`/`Order`/`Subscription`/`AuditLog` imports) before autogenerating, and always read generated migrations before applying.
- **Every `logger.error`/`logger.exception` is DM'd to all admins** (`AdminAlertHandler` in `app/utils/error_alert.py`, attached in `main.py`): one alert per (logger, message template) per 30 min, aiogram's transient "Failed to fetch updates" skipped. Use ERROR only for things an admin should act on; use WARNING for expected/self-healing failures. Logs are JSON on stdout, so journald sees everything as info — filter with `grep '"levelname": "ERROR"'`, not `journalctl -p err`.
- Migration revision IDs are hand-written (`001`…`004`) — keep the sequence when adding one.
- `plans.basic` is seeded at 2000 VND, a live payment-testing value, not a real price.
- Escape any user-supplied text interpolated into HTML messages with `safe_html` from `app/utils/order.py`; the bot runs with `ParseMode.HTML` globally.
- `.env` is gitignored and required — `Settings` has no default for `BOT_TOKEN` or `DATABASE_URL`, so the process fails at import if they are absent.
