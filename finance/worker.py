"""Background tracking: payment outcomes, reminders, rate alerts and email reports. Never prepares or submits payments."""
import asyncio
import logging

log = logging.getLogger("finance.worker")


async def run(finance, stop, interval=3, alive=lambda: True):
    tick = 0
    while not stop.is_set() and alive():  # alive() turns false when the account is closed
        try:
            await asyncio.to_thread(finance.reconcile_open)
            if tick % 20 == 0:
                await asyncio.to_thread(finance.refresh_reminders)
            if tick % 4 == 0 and finance.evm:
                await asyncio.to_thread(finance.evm.info, 10)  # keep the wallet view warm; RPC calls are slow
            if tick % 7200 == 60 and getattr(finance, "page_reader", None):  # every ~6 hours: banks for the pairs you plan to exchange
                await asyncio.to_thread(finance.auto_refresh_plans)
            if tick % 20 == 5:  # ~1 minute: your conditional exchange rules
                await asyncio.to_thread(finance.check_fx_rules)
            if tick % 200 == 0:  # ~10 minutes; reference data itself is daily and cached
                await asyncio.to_thread(finance.check_rate_alerts)
                await asyncio.to_thread(finance.check_watches)
                await asyncio.to_thread(finance.materialize_recurring)
                await asyncio.to_thread(finance.email_tick)
                if finance.motivation_settings()["enabled"]:
                    await asyncio.to_thread(finance.motivation_refresh)
        except Exception:  # keep tracking; details may contain RPC credentials, so do not log them
            log.warning("background cycle failed")
        tick += 1
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
