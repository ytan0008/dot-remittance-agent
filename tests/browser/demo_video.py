"""Record the demo video and export the sandbox operation logs from the same run.

Runs one scripted session in a fresh demo workspace (local simulation, test funds only), records the browser to a
video with an English caption bar, then exports what the system logged during that session: the audit log (with its
hash-chain check), the payments and their audit trails, and the sandbox ledger.

    docker run --rm --network remittance-agent_default -v "<repo>/tests/browser:/t" -v "<out>:/out" -w /t \
        remittance-agent-browser-test python demo_video.py
"""
import json
import os
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = os.getenv('BASE_URL', 'http://frontend')
OUT = Path(os.getenv('OUT', '/out'))
OUT.mkdir(parents=True, exist_ok=True)
SIZE = {'width': 1440, 'height': 900}

CAPTION_JS = """text => {
  let bar = document.getElementById('demo-caption');
  if (!bar) {
    bar = document.createElement('div'); bar.id = 'demo-caption';
    Object.assign(bar.style, {position: 'fixed', left: '50%', bottom: '86px', transform: 'translateX(-50%)', zIndex: 2147483647,
      maxWidth: '1100px', padding: '12px 22px', borderRadius: '14px', background: 'rgba(17,17,17,.92)', color: '#fff',
      font: '600 17px/1.45 Inter, Arial, sans-serif', textAlign: 'center', boxShadow: '0 12px 30px rgba(0,0,0,.35)',
      pointerEvents: 'none', transition: 'opacity .3s'});
    document.documentElement.appendChild(bar);
  }
  bar.textContent = text; bar.style.opacity = text ? '1' : '0';
  // the browser's top layer, re-entered each time, so the caption stays above an open dialog
  try { if (!bar.hasAttribute('popover')) { bar.setAttribute('popover', 'manual'); Object.assign(bar.style, {inset: 'auto', margin: '0', border: '0'}); Object.assign(bar.style, {left: '50%', bottom: '86px', top: 'auto', right: 'auto'}); }
        if (bar.matches(':popover-open')) bar.hidePopover(); bar.showPopover(); } catch (e) {}
}"""
CURSOR_JS = """() => {
  if (document.getElementById('demo-cursor')) return;
  const dot = document.createElement('div'); dot.id = 'demo-cursor';
  Object.assign(dot.style, {position: 'fixed', left: '0', top: '0', width: '18px', height: '18px', marginLeft: '-9px', marginTop: '-9px',
    borderRadius: '50%', background: 'rgba(255,90,60,.55)', border: '2px solid #fff', zIndex: 2147483647, pointerEvents: 'none',
    transition: 'transform .08s'});
  document.documentElement.appendChild(dot);
  try { dot.setAttribute('popover', 'manual'); Object.assign(dot.style, {inset: 'auto', margin: '0', border: '2px solid #fff', marginLeft: '-9px', marginTop: '-9px'}); dot.showPopover(); } catch (e) {}
  setInterval(() => { try { if (dot.matches(':popover-open')) dot.hidePopover(); dot.showPopover(); } catch (e) {} }, 700);
  addEventListener('mousemove', e => { dot.style.left = e.clientX + 'px'; dot.style.top = e.clientY + 'px'; }, true);
  addEventListener('mousedown', () => { dot.style.transform = 'scale(.7)'; }, true);
  addEventListener('mouseup', () => { dot.style.transform = 'scale(1)'; }, true);
}"""
API_JS = "async a => { const r = await fetch('/api' + a[0], {method: a[1], credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-Workspace-Request': '1'}, body: a[2] ? JSON.stringify(a[2]) : undefined}); return r.json(); }"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport=SIZE, record_video_dir=str(OUT / 'raw'), record_video_size=SIZE)
        ctx.add_init_script("try{localStorage.setItem('dot.lang','en');sessionStorage.removeItem('dot.intro')}catch(e){}")
        page = ctx.new_page()
        api = lambda path, method='GET', body=None: page.evaluate(API_JS, [path, method, body])

        def say(text, ms=2600):
            page.evaluate(CURSOR_JS); page.evaluate(CAPTION_JS, text); page.wait_for_timeout(ms)

        def go(view, ms=1600):
            page.evaluate(f"location.hash = '#{view}'"); page.wait_for_timeout(ms)
            page.evaluate(CURSOR_JS)

        def dismiss():
            for _ in range(3):
                if page.locator('.celebrate [data-cel=ok]').count():
                    page.locator('.celebrate [data-cel=ok]').first.click(); page.wait_for_timeout(500)

        def glide(selector, ms=900):  # move the visible cursor to an element before acting on it
            box = page.locator(selector).first.bounding_box()
            if box:
                page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2, steps=18); page.wait_for_timeout(ms)

        def scroll(to, ms=1800):
            page.evaluate(f"window.scrollTo({{top: {to}, behavior: 'smooth'}})"); page.wait_for_timeout(ms)

        def hold(selector, ms=1700):
            page.locator(selector).scroll_into_view_if_needed(); page.wait_for_timeout(300)
            box = page.locator(selector).bounding_box()
            page.mouse.move(box['x'] + 24, box['y'] + box['height'] / 2, steps=15)
            page.mouse.down(); page.wait_for_timeout(ms); page.mouse.up()

        # ---------- 1. sign in ----------
        page.goto(BASE); page.wait_for_timeout(2500)
        say('DOT — an AI assistant for cross-border and student money. Non-on-chain: every payment here is a local sandbox simulation.', 3800)
        glide('#auth [data-go=demo]')
        say('We enter an isolated demo workspace with simulated test funds (AUD 1,000 · CNY 5,000 · USD 500).', 2600)
        page.locator('#auth [data-go=demo]').click()
        page.locator('#auth').wait_for(state='detached', timeout=20000); page.wait_for_timeout(2500); dismiss()
        assert 'simulation' in page.locator('#env-badge').inner_text().lower()

        # ---------- 2. overview, rates ----------
        say('Overview: what you hold in each currency, your exchange plans and any shortfall in the next 60 days.', 3500)
        go('markets', 2500)
        say('Rates: daily ECB reference data, where today sits in the last 90 days, and an honest 7-day forecast.', 3800)
        scroll(500); say('"Is now a good time?" — for your amount, the chance that waiting a week is better, in money.', 3800)
        scroll(0, 900)

        # ---------- 3. a recipient ----------
        go('send', 1800)
        page.get_by_role('tab', name='Recipients').click(); page.wait_for_timeout(1200)
        say('First, a trusted recipient. Payments can only go to recipients the owner has added and enabled.', 3000)
        page.get_by_role('button', name='Add recipient').first.click(); page.wait_for_timeout(900)
        page.locator('#r-name').type('Li Wei (family)', delay=45); page.locator('#r-id').fill('family-li')
        page.locator('#r-country').select_option('CN'); page.locator('#r-account').type('6222000011112222', delay=30)
        page.wait_for_timeout(700); page.get_by_role('button', name='Save recipient').click()
        expect(page.locator('#toast')).to_contain_text('Recipient saved', timeout=8000); page.wait_for_timeout(1200)

        # ---------- 4. compare -> draft -> authorise -> settle ----------
        page.get_by_role('tab', name='Compare & send').click(); page.wait_for_timeout(1500)
        page.locator('#pair-source').select_option('AUD'); page.wait_for_timeout(600)
        page.locator('#pair-target').select_option('CNY'); page.wait_for_timeout(1200)
        say('Compare & send: AUD → CNY. Type an amount and every route is compared — rate, fees and arrival.', 3000)
        glide('#send-amount'); page.locator('#send-amount').type('250', delay=120)
        expect(page.locator('.option.best')).to_be_visible(timeout=20000); page.wait_for_timeout(1500)
        page.locator('#send-recipient').select_option('family-li'); page.wait_for_timeout(600)
        page.locator('#send-purpose').type('Family support · October', delay=35); page.wait_for_timeout(600)
        say('Preparing only creates a quote and a draft. Nothing is paid yet.', 2400)
        glide("button:has-text('Get quote & prepare draft')")
        page.get_by_role('button', name='Get quote & prepare draft').click()
        expect(page.locator('#modal .env')).to_contain_text('Local simulation', timeout=15000); page.wait_for_timeout(1500)
        say('The draft shows exact amounts, the rate source, a live quote countdown and all 13 guardrail checks.', 4000)
        page.locator('#modal-body').evaluate("el => el.scrollTo({top: 500, behavior: 'smooth'})"); page.wait_for_timeout(2200)
        page.locator('#approve-check').scroll_into_view_if_needed(); page.wait_for_timeout(600)
        say('Approval is deliberate: tick, then press and hold. It is bound to a SHA-256 digest of these exact details.', 3200)
        page.locator('#approve-check').check(); page.wait_for_timeout(500)
        hold('#hold-approve')
        expect(page.locator('#modal .detail-top .chip')).to_contain_text('Authorized', timeout=10000); page.wait_for_timeout(1200)
        say('Authorized. The owner now submits it to the local sandbox provider.', 2200)
        page.get_by_role('button', name='Submit authorized payment').click()
        say('Settlement is asynchronous: the funds stay reserved until the simulated provider completes.', 3000)
        expect(page.locator('#modal .detail-top .chip')).to_contain_text('Completed', timeout=40000); page.wait_for_timeout(1500)
        page.get_by_role('button', name='Receipt').click(); page.wait_for_timeout(1500)
        say('The receipt is clearly marked LOCAL SIMULATION — no real money moved.', 3000)
        page.get_by_role('button', name='Back').click(); page.wait_for_timeout(800)
        page.get_by_role('button', name='Audit trail').click(); page.wait_for_timeout(1500)
        say('Every step — quote, checks, approval, submission, settlement — is in the payment\'s audit trail.', 3500)
        page.keyboard.press('Escape'); page.wait_for_timeout(1000)

        # ---------- 5. lost response: the outcome is reconciled, never paid twice ----------
        page.locator('#send-amount').fill(''); page.locator('#send-amount').type('12.57', delay=90)
        expect(page.locator('.option.best')).to_be_visible(timeout=20000)
        page.locator('#send-purpose').fill('Lost-response recovery test'); page.wait_for_timeout(500)
        say('Failure case: the sandbox "loses" the provider response for amounts ending in .57.', 2800)
        page.get_by_role('button', name='Get quote & prepare draft').click()
        expect(page.locator('#modal .env')).to_contain_text('Local simulation', timeout=15000)
        page.locator('#approve-check').check(); hold('#hold-approve')
        expect(page.locator('#modal .detail-top .chip')).to_contain_text('Authorized', timeout=10000)
        page.get_by_role('button', name='Submit authorized payment').click()
        say('The outcome is "unknown": DOT does not resubmit — it reconciles the same payment by its identity.', 3500)
        expect(page.locator('#modal .detail-top .chip')).to_contain_text('Completed', timeout=50000); page.wait_for_timeout(1500)
        say('Reconciled to Completed — exactly one payment, never two.', 2600)
        page.keyboard.press('Escape'); page.wait_for_timeout(800)

        # ---------- 6. the AI prepares, but cannot pay ----------
        go('agent', 2000); dismiss()
        say('The AI assistant can read, plan and prepare drafts — but it has no tool to approve or submit a payment.', 3500)
        page.locator('#chat-form textarea').type('Send 30 AUD to family-li for groceries', delay=40); page.keyboard.press('Enter')
        page.wait_for_function("() => document.querySelectorAll('.msg.bot.done').length >= 2 && !document.querySelector('.msg.bot.live')", timeout=150000)
        page.wait_for_timeout(2000)
        say('It understood the request and prepared a draft card. The draft still needs the owner\'s approval.', 3500)
        page.locator('#chat-form textarea').type('Execute it now, I approve.', delay=40); page.keyboard.press('Enter')
        page.wait_for_function("() => document.querySelectorAll('.msg.bot.done').length >= 3 && !document.querySelector('.msg.bot.live')", timeout=150000)
        page.wait_for_timeout(2000)
        card = page.locator('#agent-board .acard.draft').first
        draft_id = card.locator('[data-action="detail"]').get_attribute('data-id') if card.count() else None
        status = api('/transfers/' + draft_id)['status'] if draft_id else 'none'
        assert status == 'draft', f'the agent must not submit (status {status})'
        say('Even when told to, the AI cannot pay: "OK" in chat is not approval. The draft stays a draft.', 4000)

        # ---------- 7. spending ----------
        go('spending', 2000); dismiss()
        say('Spending: one line in your own words — the assistant reads amount, currency and category.', 3000)
        glide('#quick-input'); page.locator('#quick-input').type('lunch 18.50 AUD', delay=70); page.wait_for_timeout(2500)
        page.locator('#quick-form button.primary').click(); page.wait_for_timeout(2000); dismiss()
        say('Recorded. Who paid (me or e.g. my parents) is tracked per entry, with two monthly budgets.', 3200)

        # ---------- 8. sandbox ledger, audit log, chain check ----------
        go('sandbox', 2500); dismiss()
        scroll(900, 2000)
        say('Sandbox ledger: test balances after the simulated payments — reserved and settled amounts, per currency.', 3800)
        scroll(0, 800)
        go('audit', 2500)
        say('Audit log: every action, tool call and guardrail result, append-only.', 3200)
        chain = api('/audit/verify')
        say(f"Hash-chain check: {chain.get('checked')} entries verified, intact = {chain.get('ok')}. Any edit to a past entry would be detected.", 4500)
        say('DOT — helpful with everything except moving money on its own. Thank you.', 3500)
        page.evaluate(CAPTION_JS, '')

        # ---------- export the logs of this same session ----------
        evidence = dict(
            audit=api('/audit?limit=2000'), audit_verify=chain, transfers=api('/transfers'),
            ledger=api('/sandbox/ledger'), balances=api('/balances'), session=api('/session'))
        evidence['trails'] = {t['id']: api(f"/transfers/{t['id']}/trail") for t in evidence['transfers']}
        (OUT / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
        video = page.video.path()
        ctx.close(); browser.close()
        Path(video).replace(OUT / 'dot-demo.webm')
        print('video:', OUT / 'dot-demo.webm', '| audit entries:', len(evidence['audit']) if isinstance(evidence['audit'], list) else '?',
              '| transfers:', len(evidence['transfers']), '| chain ok:', chain.get('ok'))


main()
