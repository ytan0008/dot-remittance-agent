"""Background tracking: payment outcomes, reminders and rate alerts. Never prepares or submits payments."""
import asyncio
import logging

log = logging.getLogger("finance.worker")


async def run(finance, stop, interval=3):
    tick = 0
    while not stop.is_set():
        try:
            await asyncio.to_thread(finance.reconcile_open)
            if tick % 20 == 0:
                await asyncio.to_thread(finance.refresh_reminders)
            if tick % 4 == 0 and finance.evm:
                await asyncio.to_thread(finance.evm.info, 10)  # keep the wallet view warm; RPC calls are slow
            if tick % 600 == 0:
                await asyncio.to_thread(finance.check_rate_alerts)
        except Exception:  # keep tracking; details may contain RPC credentials, so do not log them
            log.warning("background cycle failed")
        tick += 1
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
