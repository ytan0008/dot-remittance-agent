"""Read-only sweep: every view in every language, desktop and mobile. No JS errors, raw keys or overflow."""
import os
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

base = os.getenv('BASE_URL', 'http://frontend')
out = Path(os.getenv('ARTIFACTS', '/artifacts'))
out.mkdir(exist_ok=True)
views = ['agent', 'overview', 'sandbox', 'markets', 'send', 'wallets', 'templates', 'payments', 'spending', 'study', 'progress', 'memory', 'audit']
langs = ['en', 'zh-CN', 'zh-TW', 'vi', 'ja', 'ko']
raw_key = re.compile(r'\b(?:nav|page|status|check|err|send|detail|markets|wallets|autonomy|agent|plans|habits|routes|audit|memory|spend|rem|cat|study|afford|insight|email|sch|doc|prog|badge|level|cel|group|watch|tf|af|ov|tool|auth|acct|scen|bank)\.[a-z_]+\b')
problems = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    for lang in langs:
        for label, size in (('desktop', {'width': 1440, 'height': 1000}), ('mobile', {'width': 390, 'height': 844})):
            ctx = browser.new_context(viewport=size)
            ctx.add_init_script(f"try{{localStorage.setItem('dot.lang','{lang}');sessionStorage.setItem('dot.intro','1')}}catch(e){{}}")
            page = ctx.new_page()
            page.on('pageerror', lambda e, l=lang: problems.append(f'{l}: {e}'))
            # The sign-in stage first: it must fit and be translated, then enter through the demo.
            page.goto(f'{base}/#overview')
            page.locator('#auth [data-go=demo]').wait_for(timeout=30000)
            if page.evaluate('document.documentElement.scrollWidth > innerWidth'):
                problems.append(f'{lang} {label} sign-in: horizontal overflow')
            signin = page.locator('#auth').inner_text()
            if raw_key.search(signin):
                problems.append(f'{lang} {label} sign-in: untranslated key {raw_key.search(signin).group(0)}')
            page.screenshot(path=str(out / f'{lang}-{label}-signin.png'))
            page.locator('#auth [data-go=demo]').click()
            page.locator('#auth').wait_for(state='detached', timeout=15000)
            for view in views:
                page.goto(f'{base}/#{view}')
                page.wait_for_timeout(1400)
                if page.evaluate('document.documentElement.scrollWidth > innerWidth'):
                    problems.append(f'{lang} {label} {view}: horizontal overflow')
                text = page.locator('#view').inner_text() + page.locator('#nav').inner_text()
                if view != 'audit' and raw_key.search(text):  # audit shows event identifiers on purpose
                    problems.append(f'{lang} {label} {view}: untranslated key {raw_key.search(text).group(0)}')
            page.screenshot(path=str(out / f'{lang}-{label}.png'))
            ctx.close()
    browser.close()
assert not problems, problems
print(f'PASS: {len(views)} views x {len(langs)} languages x desktop/mobile without errors, raw keys or overflow.')
