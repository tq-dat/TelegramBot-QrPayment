"""Self-check for AdminAlertHandler. Run: python -m tests.test_error_alert (needs .env)."""
import asyncio
import logging

import app.utils.error_alert as ea


async def run() -> None:
    sent = []

    async def fake_send(bot, text):
        sent.append(text)

    ea._send_to_admins = fake_send
    log = logging.getLogger("test.alert")
    log.propagate = False
    log.addHandler(ea.AdminAlertHandler(bot=None, loop=asyncio.get_running_loop()))

    log.warning("not an error")                                        # below ERROR: ignored
    log.error("Failed to fetch updates - TelegramNetworkError: x")     # transient noise: ignored
    log.error("vietqr generation failed", extra={"error": "301 <Moved>"})
    log.error("vietqr generation failed", extra={"error": "again"})    # within cooldown: suppressed
    try:
        1 / 0
    except ZeroDivisionError:
        log.exception("auto confirm failed", extra={"order_code": "VIPX"})
    await asyncio.to_thread(log.error, "from a worker thread")         # thread-safe hand-off
    await asyncio.sleep(0.05)

    assert len(sent) == 3, sent
    assert "vietqr generation failed" in sent[0] and "301 &lt;Moved&gt;" in sent[0], sent[0]  # HTML-escaped
    assert "ZeroDivisionError" in sent[1] and "VIPX" in sent[1], sent[1]
    assert "worker thread" in sent[2]

    # After the cooldown the next alert reports how many repeats were folded in.
    h = log.handlers[0]
    h._last_sent = {k: v - ea.COOLDOWN_SECONDS for k, v in h._last_sent.items()}
    log.error("vietqr generation failed", extra={"error": "third"})
    await asyncio.sleep(0.05)
    assert "+1 lỗi giống vậy" in sent[-1], sent[-1]
    print("test_error_alert OK")


if __name__ == "__main__":
    asyncio.run(run())
