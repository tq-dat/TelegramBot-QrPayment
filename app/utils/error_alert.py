"""
Forward ERROR-level log records to admins on Telegram, so failures are seen the
day they start instead of sitting unread in journald (the 2026-10 VietQR outage
logged 14 errors over ~4 weeks before anyone noticed).
"""
import asyncio
import logging
import time

from app.utils.order import safe_html
from app.utils.payment import _send_to_admins

# Transient Telegram polling blips (aiogram retries them itself); ~140/6 weeks of noise.
IGNORED_PREFIXES = ("Failed to fetch updates",)
COOLDOWN_SECONDS = 30 * 60

_STD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


class AdminAlertHandler(logging.Handler):
    """At most one alert per (logger, message template) per COOLDOWN_SECONDS; repeats are counted."""

    def __init__(self, bot, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(level=logging.ERROR)
        self.bot = bot
        self.loop = loop
        self._last_sent: dict[tuple[str, str], float] = {}
        self._suppressed: dict[tuple[str, str], int] = {}
        self._tasks: set[asyncio.Task] = set()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if message.startswith(IGNORED_PREFIXES):
                return
            key = (record.name, str(record.msg))
            now = time.monotonic()
            if now - self._last_sent.get(key, -COOLDOWN_SECONDS) < COOLDOWN_SECONDS:
                self._suppressed[key] = self._suppressed.get(key, 0) + 1
                return
            self._last_sent[key] = now
            text = self.format_alert(record, message, self._suppressed.pop(key, 0))
            # emit() may run outside the loop thread (e.g. asyncio.to_thread), so hand off thread-safely.
            self.loop.call_soon_threadsafe(self._start_send, text)
        except Exception:
            pass  # alerting must never break the code that logged the error (e.g. loop already closed)

    def _start_send(self, text: str) -> None:
        task = self.loop.create_task(_send_to_admins(self.bot, text))
        self._tasks.add(task)  # keep a reference so the task is not garbage-collected mid-send
        task.add_done_callback(self._tasks.discard)

    @staticmethod
    def format_alert(record: logging.LogRecord, message: str, suppressed: int) -> str:
        extras = {k: v for k, v in vars(record).items() if k not in _STD_ATTRS}
        lines = [
            f"🚨 <b>Bot lỗi</b> — <code>{safe_html(record.name)}</code>",
            f"<b>{safe_html(message[:500])}</b>",
        ]
        lines += [f"• {safe_html(k)}: <code>{safe_html(str(v)[:300])}</code>" for k, v in extras.items()]
        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            lines.append(f"• exception: <code>{safe_html(f'{type(exc).__name__}: {exc}'[:300])}</code>")
        if suppressed:
            lines.append(f"<i>+{suppressed} lỗi giống vậy trong 30 phút trước đã được gộp.</i>")
        lines.append("<i>Lỗi giống vậy sẽ không báo lại trong 30 phút. Xem log: journalctl -u telegrambot</i>")
        return "\n".join(lines)
