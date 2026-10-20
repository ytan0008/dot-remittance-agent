"""The full DOT demo video — exactly five minutes, narrated, with music and borderless captions.

Three stages, each run in the browser-test image (network on for the voices):
    python demo_full.py tts      # one voice clip per narration line (Microsoft neural voice via edge-tts) + durations
    python demo_full.py record   # the walkthrough in a fresh demo workspace; lines follow each other without gaps
    python demo_full.py mix      # synthesised background music, voice laid at the recorded times, ducking -> MP4 of 5:00
Only the narration text is sent to the voice service. Everything runs against the local simulation. Voice input is
shown with a simulated speech recogniser (an automated browser has no microphone); the rest is the real app.
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import wave
from datetime import date, timedelta
from pathlib import Path

BASE = os.getenv('BASE_URL', 'http://frontend')
OUT = Path(os.getenv('OUT', '/out'))
VOICE = os.getenv('VOICE', 'en-US-AvaNeural')
SIZE = {'width': 1440, 'height': 900}
TARGET = 300.0   # seconds: the video is exactly five minutes
GAP = 0.25       # pause between two lines

LINES = [
    ('intro', "Meet DOT, an AI money assistant for students whose money lives across borders. Everything here runs in a local sandbox, so no real money ever moves."),
    ('blob', "Even the sign-in dot is playful: drag it, and it springs back like jelly."),
    ('lang', "The whole app speaks six languages, starting right here. Let's open the demo."),
    ('overview', "The overview shows what I hold in each currency, my exchange plans, and any gap over the next sixty days."),
    ('plan', "An exchange plan sets what I need, by when, and the lowest rate I'll accept. DOT's watch keeps an eye on it for me."),
    ('dark', "Light or dark, it's one tap."),
    ('sandbox', "The sandbox replays the coming months day by day. Pretend money lets me test a what-if without touching anything real."),
    ('rates', "The rates page shows where today's rate sits in the last ninety days, and what waiting a week is likely to be worth, in money."),
    ('rule', "A conditional exchange runs when the rate hits my target before my deadline, never above my cap, and it asks me first."),
    ('alert', "A simple target alert tells me the moment a rate crosses my line."),
    ('banks', "DOT reads each bank's official pages, and keeps every fee, from wire fees to cable charges, with its exact quote and link."),
    ('drag', "Cards can be dragged and arranged however I like."),
    ('send', "To send money, I compare every route and scenario, with each fee kept in its own currency."),
    ('draft', "Preparing makes a draft only, and thirteen guardrails check it first."),
    ('authorize', "Approval is deliberate: I press and hold, and it's bound to these exact details."),
    ('settle', "It settles in the sandbox, with a receipt clearly marked as a simulation."),
    ('me', "My own bank accounts always appear as Me, so moving money between them is never counted as spending."),
    ('template', "Transfer templates check SWIFT codes, IBANs and local formats as I type."),
    ('history', "Transfer history keeps every payment I made, with its full audit trail."),
    ('budget', "For spending, I keep two monthly budgets: one for my own money, and one for what my parents pay."),
    ('account', "My parents' card is marked as paid by others. It counts as my spending, but never as my cash or my debt."),
    ('csv', "Its statement imports in seconds, and every row waits for my review."),
    ('split', "Totals and budgets are split between me and my parents, and insights show where I could save."),
    ('quick', "Quick entry takes a line in my own words."),
    ('voice', "Or I can simply say it."),
    ('scan', "Banking screenshots and receipts work too. Before anything leaves my device, I black out my card number."),
    ('scanread', "The AI reads every transaction, and I choose who paid for all of them at once."),
    ('fixed', "Fixed costs gather bills, rent and subscriptions in one list, with reminders before they're due."),
    ('afford', "Can I afford it? DOT checks my cash, my term plan, and the budget of whoever pays."),
    ('term', "Term planning projects my cash month by month, with tuition, living costs, and what my parents cover."),
    ('scholar', "Scholarships are tracked with deadlines, document checklists and reminders."),
    ('progress', "Progress rewards good habits with badges and small challenges, never comparisons."),
    ('memory', "Memory shows what DOT remembers about me, and I can delete any note."),
    ('settings', "Settings hold my currencies, email reports, and privacy controls to export or delete everything."),
    ('agent', "And the assistant does almost anything I ask, in plain words."),
    ('agentcard', "It reads my records and prepares a confirm card. Nothing changes until I press confirm."),
    ('agent2', "I can also just ask a question, like whether a jacket fits my parents' budget this month."),
    ('agent2a', "It checks the right budget and answers with the real numbers, ready as a card on the board."),
    ('agentnot', "Payments are different: it can never approve or send money on its own."),
    ('orb', "And DOT is one tap away on every page."),
    ('audit', "Every action lands in an append-only audit log, chained by hashes, so any change would be detected."),
    ('recap', "From planning to paying, every part of my money lives in one calm place."),
    ('outro', "DOT. Helpful with everything, except moving money on its own."),
]
TEXT = dict(LINES)


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def duration(path):
    out = subprocess.run([ffmpeg(), '-i', str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r'Duration: (\d+):(\d+):([\d.]+)', out).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


# ---------------------------------------------------------------- 1. voices
async def _tts():
    import edge_tts
    folder = OUT / 'voice'
    folder.mkdir(parents=True, exist_ok=True)
    lengths = {}
    for key, text in LINES:
        path = folder / f'{key}.mp3'
        await edge_tts.Communicate(text, VOICE, rate='+6%').save(str(path))
        lengths[key] = round(duration(path), 3)
    (OUT / 'voice.json').write_text(json.dumps(lengths, indent=1), encoding='utf-8')
    print('lines', len(lengths), '| speech total', round(sum(lengths.values()), 1), 's')


# ---------------------------------------------------------------- 2. recording
CAPTION_JS = """text => {
  let bar = document.getElementById('demo-caption');
  if (!bar) {
    bar = document.createElement('div'); bar.id = 'demo-caption'; bar.setAttribute('popover', 'manual');
    Object.assign(bar.style, {position: 'fixed', inset: 'auto', margin: '0', border: '0', padding: '0', background: 'transparent',
      zIndex: 2147483647, pointerEvents: 'none', color: '#fff', textAlign: 'center', maxWidth: '1180px',
      font: '700 24px/1.4 Inter, Arial, sans-serif',
      textShadow: '0 0 3px #000, 0 0 3px #000, 1px 1px 2px #000, -1px -1px 2px #000, 1px -1px 2px #000, -1px 1px 2px #000, 0 2px 10px rgba(0,0,0,.7)'});
    Object.assign(bar.style, {left: '50%', bottom: '64px', top: 'auto', right: 'auto', transform: 'translateX(-50%)'});
    document.documentElement.appendChild(bar);
    // a dialog opened later would cover it: keep re-entering the top layer
    setInterval(() => { try { if (bar.matches(':popover-open')) bar.hidePopover(); bar.showPopover(); } catch (e) {} }, 400);
  }
  bar.textContent = text; bar.style.opacity = text ? '1' : '0';
  try { if (bar.matches(':popover-open')) bar.hidePopover(); bar.showPopover(); } catch (e) {}
}"""
CURSOR_JS = """() => {
  if (document.getElementById('demo-cursor')) return;
  const dot = document.createElement('div'); dot.id = 'demo-cursor'; dot.setAttribute('popover', 'manual');
  Object.assign(dot.style, {position: 'fixed', inset: 'auto', margin: '0', padding: '0', width: '18px', height: '18px', borderRadius: '50%',
    background: 'rgba(255,90,60,.6)', border: '2px solid #fff', zIndex: 2147483647, pointerEvents: 'none', left: '-40px', top: '-40px',
    transform: 'translate(-50%,-50%)', transition: 'scale .08s'});
  document.documentElement.appendChild(dot);
  try { dot.showPopover(); } catch (e) {}
  addEventListener('mousemove', e => { dot.style.left = e.clientX + 'px'; dot.style.top = e.clientY + 'px'; }, true);
  addEventListener('mousedown', () => { dot.style.scale = '.7'; }, true);
  addEventListener('mouseup', () => { dot.style.scale = '1'; }, true);
  setInterval(() => { try { if (dot.matches(':popover-open')) dot.hidePopover(); dot.showPopover(); } catch (e) {} }, 600);
}"""
# no microphone in an automated browser: a stand-in recogniser "hears" a short phrase, word by word
SPEECH_JS = """(() => {
  class FakeRecognition {
    start() {
      const words = ['coffee', '4.50', 'dollars'];
      let said = [];
      words.forEach((w, i) => setTimeout(() => {
        said.push(w);
        this.onresult && this.onresult({results: [[{transcript: said.join(' ')}]]});
        if (i === words.length - 1) setTimeout(() => this.onend && this.onend(), 500);
      }, 700 + i * 550));
    }
    stop() { this.onend && this.onend(); }
  }
  window.SpeechRecognition = window.webkitSpeechRecognition = FakeRecognition;
})();"""
API_JS = ("async a => { const r = await fetch('/api' + a[0], {method: a[1], credentials: 'same-origin', headers: {'Content-Type': 'application/json', "
          "'X-Workspace-Request': '1'}, body: a[2] ? JSON.stringify(a[2]) : undefined}); return r.json(); }")


def record():
    from playwright.sync_api import sync_playwright, expect
    lengths = json.loads((OUT / 'voice.json').read_text(encoding='utf-8'))
    today = date.today()
    d = lambda n: (today - timedelta(days=n)).strftime('%d/%m/%Y')
    csv_path = OUT / 'mum-card.csv'
    csv_path.write_text(f"Date,Description,Amount\n{d(1)},WOOLWORTHS TOWN HALL,-86.40\n{d(2)},UBER *TRIP SYDNEY,-23.10\n"
                        f"{d(3)},OFFICEWORKS BROADWAY,-41.95\n{d(4)},JB HI-FI BROADWAY,-129.00\n{d(5)},PAYMENT RECEIVED - THANK YOU,500.00\n",
                        encoding='utf-8')
    timeline = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport=SIZE, record_video_dir=str(OUT / 'raw'), record_video_size=SIZE)
        ctx.add_init_script("try{localStorage.setItem('dot.lang','en');sessionStorage.setItem('dot.intro','1')}catch(e){}")
        ctx.add_init_script(SPEECH_JS)
        page = ctx.new_page()
        t0 = time.monotonic()
        state = {'free': 0.0}
        api = lambda path, method='GET', body=None: page.evaluate(API_JS, [path, method, body])
        clock = lambda: time.monotonic() - t0

        def overlay():
            try:
                page.evaluate(CURSOR_JS)
            except Exception:
                pass

        def say(key, block=False):
            """Start a line as soon as the previous one has finished; actions carry on while it plays."""
            if clock() < state['free']:
                time.sleep(state['free'] - clock())
            start = clock()
            overlay(); page.evaluate(CAPTION_JS, TEXT[key])
            timeline.append({'key': key, 'at': round(start, 3)})
            state['free'] = start + lengths[key] + GAP
            if block:
                wait_voice()

        def wait_voice():
            if clock() < state['free']:
                time.sleep(state['free'] - clock())

        def step(name, fn):
            try:
                fn()
            except Exception as exc:  # one step failing must not ruin the take
                print(f'WARN {name}: {type(exc).__name__}: {str(exc)[:160]}')

        def dismiss():
            for _ in range(3):  # a badge pop-up may close by itself just as we click: never fatal
                try:
                    if not page.locator('.celebrate [data-cel=ok]').count():
                        return
                    page.locator('.celebrate [data-cel=ok]').first.click(timeout=1500); page.wait_for_timeout(250)
                except Exception:
                    page.wait_for_timeout(200)

        def go(view, ms=900):
            page.evaluate(CAPTION_JS, '')
            page.evaluate(f"location.hash = '#{view}'"); page.wait_for_timeout(ms); overlay(); dismiss()

        def glide(sel, ms=250):
            box = page.locator(sel).first.bounding_box()
            if box:
                page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2, steps=10); page.wait_for_timeout(ms)

        def show(sel, ms=700):
            el = page.locator(sel).first
            el.evaluate("el => { const f = el.closest('article.panel.folded'); if (f) f.querySelector('.card-fold')?.click(); "
                        "el.scrollIntoView({behavior: 'smooth', block: 'center'}); }")
            page.wait_for_timeout(ms)

        def top():
            page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})"); page.wait_for_timeout(450)

        def hold(sel, ms=1400):
            page.locator(sel).scroll_into_view_if_needed(); page.wait_for_timeout(150)
            box = page.locator(sel).bounding_box()
            page.mouse.move(box['x'] + 24, box['y'] + box['height'] / 2, steps=10)
            page.mouse.down(); page.wait_for_timeout(ms); page.mouse.up()

        def tab(name):
            page.get_by_role('tab', name=name).click(); page.wait_for_timeout(600)

        # ================= sign-in: the jelly dot, six languages =================
        page.goto(BASE); page.locator('#auth .auth-lang select').wait_for(timeout=30000); page.wait_for_timeout(500); overlay()
        say('intro')
        page.wait_for_timeout(3500)
        say('blob')
        def blob():
            b = page.locator('#auth .auth-blob').bounding_box()
            cx, cy = b['x'] + b['width'] / 2, b['y'] + b['height'] / 2
            page.mouse.move(cx, cy, steps=10); page.mouse.down()
            page.mouse.move(cx + 170, cy - 90, steps=25); page.wait_for_timeout(250)
            page.mouse.move(cx - 120, cy + 60, steps=25); page.mouse.up(); page.wait_for_timeout(1200)
        step('blob', blob)
        say('lang')
        for lang in ('zh-CN', 'ja', 'ko', 'en'):
            page.select_option('#auth .auth-lang select', lang); page.wait_for_timeout(650)
        glide('#auth [data-go=demo]')
        page.locator('#auth [data-go=demo]').click(); page.locator('#auth').wait_for(state='detached', timeout=20000)
        page.wait_for_timeout(900); overlay(); dismiss()
        page.set_default_timeout(5000)  # a step that cannot act gives up quickly instead of freezing the video
        api('/banks/auto', 'POST', {'source': 'AUD', 'target': 'CNY'})  # banks are read in the background during the tour
        api('/recipients', 'POST', {'recipient_id': 'family-li', 'name': 'Li Wei (family)', 'currency': 'CNY', 'country': 'CN',
                                    'account': '6222000011112222', 'kind': 'individual', 'enabled': True, 'address': ''})
        api('/cash', 'PUT', {'currency': 'AUD', 'amount': '3200'})

        # ================= overview, dark mode, sandbox =================
        say('overview')
        page.wait_for_timeout(1500); page.mouse.wheel(0, 400); page.wait_for_timeout(1600); top()
        say('plan')
        def plan():
            page.click('[data-action=plan-new]'); page.wait_for_timeout(600)
            page.locator('#pf-amount').fill('4300'); page.locator('#pf-purpose').fill('Tuition, semester 1')
            page.fill('#pf-due', str(today + timedelta(days=40))); page.wait_for_timeout(1500)
            page.click('#plan-form button.primary'); page.wait_for_timeout(900); dismiss()
        step('plan', plan); wait_voice()
        say('dark')
        step('dark', lambda: (glide('#theme-toggle'), page.click('#theme-toggle')))
        go('sandbox'); say('sandbox')
        def sandbox():
            show('#sim-extra-form'); f = page.locator('#sim-extra-form')
            f.locator('select[name=currency]').select_option('CNY'); f.locator('input[name=amount]').type('20000', delay=50)
            f.locator('button').click(); page.wait_for_timeout(1300); page.mouse.wheel(0, 450)
        step('sandbox', sandbox); wait_voice()
        step('light', lambda: page.click('#theme-toggle'))

        # ================= rates: decision, rule, banks, drag =================
        go('markets', 1300); say('rates')
        step('decide', lambda: show('.decide-panel', 1500)); wait_voice()
        say('rule')
        def rule():
            glide('[data-action=rule-new]'); page.click('[data-action=rule-new]'); page.wait_for_timeout(500)
            page.fill('#rl-amount', ''); page.type('#rl-amount', '3000', delay=50)
            page.fill('#rl-due', str(today + timedelta(days=30))); page.wait_for_timeout(1200)
            page.click('#rule-form button.primary'); page.wait_for_timeout(900)
        step('rule', rule); wait_voice()
        say('alert')
        def alert():
            show('#alert-form', 700)
            box = page.locator('#alert-form input:not([type=hidden])').first
            box.fill(''); box.type('4.80', delay=60); page.locator('#alert-form button.primary').click(); page.wait_for_timeout(800)
        step('alert', alert); wait_voice()
        say('banks')
        def banks():
            show('#bank-panel', 900)
            kb = page.locator('#bank-panel details.kb').first
            if kb.count():
                kb.evaluate('d => d.open = true'); show('#bank-panel details.kb', 1200)
            page.mouse.wheel(0, 300)
        step('banks', banks); wait_voice()
        say('drag')
        def drag():
            top(); cards = page.locator('#view .deck > *')
            a = cards.nth(1).locator(':scope > .card-grip').bounding_box(); b = cards.nth(3).bounding_box()
            page.mouse.move(a['x'] + 10, a['y'] + 8, steps=6); page.mouse.down()
            page.mouse.move(b['x'] + b['width'] / 2, b['y'] + b['height'] - 8, steps=30); page.wait_for_timeout(300); page.mouse.up()
        step('drag', drag); wait_voice()

        # ================= send: compare, draft, authorise, settle, me, templates, history =================
        go('send', 1100); say('send')
        def compare():
            tab('Compare & send'); page.select_option('#pair-source', 'AUD'); page.wait_for_timeout(300)
            page.select_option('#pair-target', 'CNY'); page.wait_for_timeout(400)
            glide('#send-amount'); page.type('#send-amount', '250', delay=90)
            expect(page.locator('.option.best')).to_be_visible(timeout=20000)
            page.select_option('#send-recipient', 'family-li'); page.type('#send-purpose', 'Family support', delay=25)
            page.mouse.wheel(0, 650); page.wait_for_timeout(1300); page.mouse.wheel(0, -650)
        step('compare', compare); wait_voice()
        say('draft')
        def draft():
            page.get_by_role('button', name='Get quote & prepare draft').click()
            expect(page.locator('#modal .env')).to_contain_text('Local simulation', timeout=15000); page.wait_for_timeout(800)
            page.locator('#modal-body').evaluate("el => el.scrollTo({top: 520, behavior: 'smooth'})")
        step('draft', draft); wait_voice()
        say('authorize')
        def authorize():
            page.locator('#approve-check').check(); hold('#hold-approve')
            expect(page.locator('#modal .detail-top .chip')).to_contain_text('Authorized', timeout=10000)
        step('authorize', authorize); wait_voice()
        say('settle')
        def settle():
            page.get_by_role('button', name='Submit authorized payment').click()
            expect(page.locator('#modal .detail-top .chip')).to_contain_text('Completed', timeout=40000)
            page.get_by_role('button', name='Receipt').click(); page.wait_for_timeout(1500); page.keyboard.press('Escape')
        step('settle', settle); wait_voice()
        say('me')
        def me():
            tab('Recipients'); page.click('[data-action=own-account]'); page.wait_for_timeout(500)
            page.select_option('#o-currency', 'CNY'); page.type('#o-bank', 'Bank of China', delay=30)
            page.select_option('#o-country', 'CN'); page.type('#o-account', '6217000011118888', delay=20)
            page.click('#own-form button.primary'); page.wait_for_timeout(1000)
        step('me', me); wait_voice()
        say('template')
        def template():
            tab('Bank transfer templates'); page.type('#tf-name', 'UNSW tuition', delay=25)
            for name, value in (('beneficiary_name', 'UNSW Sydney'), ('account', 'GB82 WEST 1234 5698 7654 32'), ('bic', 'NWBKGB2X')):
                box = page.locator(f'#tf-form [name={name}]')
                if box.count():
                    box.first.type(value, delay=22)
            page.wait_for_timeout(700)
            bic = page.locator('#tf-form [name=bic]')
            if bic.count():
                bic.first.fill(''); bic.first.type('NWBKGB2L', delay=45)
        step('template', template); wait_voice()
        go('payments', 1000); say('history')
        step('history', lambda: (page.locator('#view [data-action=detail]').first.click(), page.wait_for_timeout(1300),
                                 page.get_by_role('button', name='Audit trail').click(), page.wait_for_timeout(1500), page.keyboard.press('Escape')))
        wait_voice()

        # ================= spending =================
        go('spending', 1000); say('budget')
        def budget():
            page.click('[data-action=budget-edit]'); page.wait_for_timeout(400)
            page.type('#bm-amount', '600', delay=55); page.type('#bm-others', '900', delay=55); page.select_option('#bm-cur', 'AUD')
            page.click('#budget-month-form button.primary'); page.wait_for_timeout(900); dismiss()
        step('budget', budget); wait_voice()
        say('account')
        def account():
            page.click('[data-action=acct-add]'); page.wait_for_timeout(400)
            page.type('#ac-name', "Mum's card", delay=35); page.select_option('#ac-type', 'credit'); page.select_option('#ac-cur', 'AUD')
            page.click('.ac-payer label:has(input[value=other])'); page.wait_for_timeout(600)
            page.click('#account-form button.primary'); page.wait_for_timeout(900); dismiss()
        step('account', account); wait_voice()
        say('csv')
        def csv():
            sel = page.locator('#csv-account'); sel.select_option(sel.locator('option', has_text='Mum').first.get_attribute('value'))
            page.set_input_files('#csv-file', str(csv_path)); page.wait_for_timeout(1600); dismiss()
            show('.review-panel', 700); page.locator('#review-all').check(); page.wait_for_timeout(300)
            page.click('[data-action=spend-confirm]'); page.wait_for_timeout(1200); dismiss()
        step('csv', csv); wait_voice()
        say('split')
        step('split', lambda: (show('.spend-summary', 1800), show('.insight-panel', 1200))); wait_voice()
        say('quick')
        def quick():
            top(); page.type('#quick-input', 'lunch 18.50 AUD', delay=60); page.wait_for_timeout(900)
            page.select_option('#quick-form .quick-payer', 'me'); page.click('#quick-form button.primary'); page.wait_for_timeout(900); dismiss()
        step('quick', quick); wait_voice()
        say('voice')
        def voice():
            glide('[data-action=spend-voice]'); page.click('[data-action=spend-voice]'); page.wait_for_timeout(3000)
            page.click('#quick-form button.primary'); page.wait_for_timeout(700); dismiss()
        step('voice', voice); wait_voice()
        say('scan')
        read = {'ok': False}
        def scan():
            page.set_input_files('#receipt-file', str(OUT / 'test1.jpg')); page.wait_for_timeout(1100)
            img = page.locator('.mask-img').first.bounding_box()
            # the card number at the top of the screenshot ("•••• 7806")
            page.mouse.move(img['x'] + img['width'] * 0.05, img['y'] + img['height'] * 0.094, steps=8); page.mouse.down()
            page.mouse.move(img['x'] + img['width'] * 0.33, img['y'] + img['height'] * 0.126, steps=16); page.mouse.up()
            page.wait_for_timeout(600); page.click('#mask-send')
            page.locator('#receipt-form').wait_for(timeout=90000); read['ok'] = True
        step('scan', scan); wait_voice()
        say('scanread')
        def scanread():
            if not read['ok']:
                page.keyboard.press('Escape'); return
            page.select_option('#scan-payer-all', 'other:Mum and Dad') if page.locator('#scan-payer-all option[value="other:Mum and Dad"]').count() else None
            page.locator('#receipt-form .table-wrap').evaluate("el => el.scrollTo({top: 400, behavior: 'smooth'})"); page.wait_for_timeout(1500)
            page.click('#receipt-form button.primary'); page.wait_for_timeout(900); dismiss()
        step('scanread', scanread); wait_voice()
        say('fixed')
        step('fixed', lambda: (top(), page.click('[data-action=spend-tab][data-v=fixed]'), page.wait_for_timeout(1400), page.mouse.wheel(0, 350)))
        wait_voice()

        # ================= term planning, scholarships =================
        go('study', 1000); say('afford')
        def afford():
            page.type('#afford-form [name=amount]', '120', delay=60); page.type('#afford-form [name=label]', 'Winter jacket', delay=25)
            page.click('.afford-payer label:has(input[value=other])'); page.click('#afford-form button.primary'); page.wait_for_timeout(1300)
        step('afford', afford); wait_voice()
        say('term')
        def term():
            page.locator('#term-form').evaluate("f => { const d = f.closest('details'); if (d) d.open = true; }")
            show('#term-form', 500)
            page.type('#tm-name', 'Semester 1 2027', delay=25); page.fill('#tm-start', str(today + timedelta(days=100)))
            page.fill('#tm-end', str(today + timedelta(days=220))); page.type('#tm-tuition', '18500', delay=30)
            page.fill('#tm-due', str(today + timedelta(days=95))); page.type('#tm-living', '1800', delay=30)
            page.click('#term-form button.primary, #term-form button[type=submit], #term-form .button'); page.wait_for_timeout(1200)
            show('.cash-panel', 1500)
        step('term', term); wait_voice()
        say('scholar')
        def scholar():
            page.locator('#sch-form').evaluate("f => { const d = f.closest('details'); if (d) d.open = true; }")
            show('#sch-form', 500)
            page.type('#sc-name', 'Global Excellence Scholarship', delay=20); page.type('#sc-provider', 'UNSW', delay=25)
            page.type('#sc-amount', '5000', delay=30); page.fill('#sc-deadline', str(today + timedelta(days=21)))
            page.click('#sch-form button.primary, #sch-form button[type=submit]'); page.wait_for_timeout(1200); dismiss()
            show('.sch-panel', 900)
        step('scholar', scholar); wait_voice()

        # ================= progress, memory, settings =================
        go('progress', 1000); say('progress')
        step('progress', lambda: (page.locator('[data-action=ch-start]').first.click(), page.wait_for_timeout(1000), dismiss(),
                                  page.mouse.wheel(0, 400)))
        wait_voice()
        go('memory', 900); say('memory')
        def memory():
            page.type('#note-text', 'Mum and Dad pay my phone bill', delay=25); page.click('#note-form button'); page.wait_for_timeout(1200)
            dismiss()
        step('memory', memory); wait_voice()
        say('settings')
        def settings():
            dismiss(); glide('#account'); page.locator('#account').click(timeout=8000); page.wait_for_timeout(1000)
            for y in (450, 900, 1400):
                page.locator('#modal-body').evaluate(f"el => el.scrollTo({{top: {y}, behavior: 'smooth'}})"); page.wait_for_timeout(900)
            page.keyboard.press('Escape')
        step('settings', settings); wait_voice()

        # ================= the assistant =================
        go('agent', 1000); say('agent')
        def agent():
            dismiss()
            box = page.locator('#chat-form textarea'); box.click(); box.fill('Add my phone bill: 35 AUD every month, due on the 5th.')
            page.wait_for_timeout(600); box.press('Enter')
            page.wait_for_function("() => document.querySelectorAll('.msg.bot.done').length >= 2 && !document.querySelector('.msg.bot.live')",
                                   timeout=90000)
        step('agent', agent); wait_voice()
        say('agentcard')
        def agentcard():
            btn = page.locator('[data-action=chat-decide][data-accept="1"]').last
            if btn.count():
                btn.scroll_into_view_if_needed(); glide('[data-action=chat-decide][data-accept="1"] >> nth=-1')
                btn.evaluate('b => b.click()'); page.wait_for_timeout(1500)  # on a draggable tile: the button's own click
        step('agentcard', agentcard); wait_voice()
        say('agent2')
        def agent2():
            box = page.locator('#chat-form textarea'); box.click()
            box.fill("Can I afford a 120 AUD jacket on my parents' card this month?"); page.wait_for_timeout(500); box.press('Enter')
            page.wait_for_function("() => document.querySelectorAll('.msg.bot.done').length >= 3 && !document.querySelector('.msg.bot.live')",
                                   timeout=90000)
        step('agent2', agent2); wait_voice()
        say('agent2a'); wait_voice()
        say('agentnot'); wait_voice()
        go('overview', 900); say('orb')
        step('orb', lambda: (glide('#ai-orb'), page.click('#ai-orb'), page.wait_for_timeout(1800), page.click('#ai-orb')))
        wait_voice()

        # ================= audit, close =================
        go('audit', 1200); say('audit')
        chain = api('/audit/verify')
        confirmed = [e for e in api('/audit?q=proposal.confirm') if e.get('action') == 'proposal.confirm']
        print('proposals confirmed during the take:', len(confirmed))
        wait_voice()
        # a recap that stretches to fill the time left, so the last line ends right at five minutes (the AI's speed varies)
        outro_at = TARGET - lengths['outro'] - 1.0
        if outro_at - clock() > lengths['recap'] + 4:
            say('recap')
            tour = ['overview', 'markets', 'send', 'spending', 'study', 'progress', 'sandbox', 'agent']
            for i, view in enumerate(tour):
                left = outro_at - clock()
                if left < 2.5:
                    break
                slot = min(6.0, left / max(1, len(tour) - i))
                go(view, 500); page.mouse.wheel(0, 380)
                page.wait_for_timeout(int(max(0.0, slot - 0.9) * 1000))
            go('overview', 400)
        if clock() < outro_at:
            time.sleep(outro_at - clock())
        say('outro'); wait_voice()
        if clock() < TARGET:
            page.wait_for_timeout(int((TARGET - clock()) * 1000) + 300)
        page.evaluate(CAPTION_JS, '')
        video = page.video.path()
        ctx.close(); browser.close()
    Path(video).replace(OUT / 'demo-full.webm')
    (OUT / 'timeline.json').write_text(json.dumps(timeline, indent=1), encoding='utf-8')
    end = timeline[-1]['at'] + lengths['outro']
    print('recorded', round(duration(OUT / 'demo-full.webm'), 1), 's | narration ends at', round(end, 1), 's | chain', chain.get('ok'), chain.get('checked'))


# ---------------------------------------------------------------- 3. music and mix
def music(path, seconds, rate=44100):
    """A calm pad: four chords, slow swells, a soft arpeggio. Synthesised here, so it is free to use."""
    import numpy as np
    n = int(seconds * rate)
    t = np.arange(n) / rate
    chords = [[261.63, 329.63, 392.00, 493.88], [220.00, 261.63, 329.63, 392.00],
              [174.61, 220.00, 261.63, 329.63], [196.00, 246.94, 293.66, 392.00]]  # Cmaj7 Am7 Fmaj7 G
    bar = 8.0
    left = np.zeros(n); right = np.zeros(n)
    for i, start in enumerate(np.arange(0, seconds, bar)):
        a, b = int(start * rate), min(n, int((start + bar + 2.0) * rate))
        seg = t[a:b] - start
        env = np.clip(seg / 2.5, 0, 1) * np.clip((bar + 2.0 - seg) / 2.5, 0, 1)
        for k, f in enumerate(chords[i % 4]):
            tone = np.sin(2 * np.pi * f * seg) + 0.25 * np.sin(2 * np.pi * 2 * f * seg) + 0.4 * np.sin(2 * np.pi * f / 2 * seg)
            left[a:b] += env * tone * (0.9 if k % 2 else 0.6)
            right[a:b] += env * np.sin(2 * np.pi * f * 1.003 * seg + 0.6) * (0.6 if k % 2 else 0.9)
        for j, f in enumerate(chords[i % 4] * 2):
            s0 = start + j * 0.5
            a2, b2 = int(s0 * rate), min(n, int((s0 + 1.6) * rate))
            if a2 >= n:
                break
            s2 = t[a2:b2] - s0
            (left if j % 2 else right)[a2:b2] += np.sin(2 * np.pi * 2 * f * s2) * np.exp(-s2 * 3.0) * 0.18
    for buf in (left, right):
        for delay, gain in ((0.23, 0.35), (0.41, 0.2)):
            dd = int(delay * rate)
            buf[dd:] += buf[:-dd] * gain
    fade = np.clip(t / 3.0, 0, 1) * np.clip((seconds - t) / 4.0, 0, 1)
    peak = max(np.abs(left).max(), np.abs(right).max()) or 1
    stereo = np.stack([left, right], axis=1) * (fade[:, None] * 0.8 / peak)
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes((stereo * 32767).astype('<i2').tobytes())


def mix():
    timeline = json.loads((OUT / 'timeline.json').read_text(encoding='utf-8'))
    video = OUT / 'demo-full.webm'
    music(OUT / 'music.wav', TARGET)
    cmd = [ffmpeg(), '-y', '-loglevel', 'error', '-i', str(video), '-i', str(OUT / 'music.wav')]
    parts = []
    for i, item in enumerate(timeline):
        cmd += ['-i', str(OUT / 'voice' / f"{item['key']}.mp3")]
        ms = int(item['at'] * 1000)
        parts.append(f"[{i + 2}:a]aresample=44100,aformat=channel_layouts=stereo,adelay={ms}|{ms}[v{i}]")
    voices = ''.join(f'[v{i}]' for i in range(len(timeline)))
    graph = ';'.join(parts) + (
        f";{voices}amix=inputs={len(timeline)}:normalize=0,volume=1.6[voice]"
        ";[voice]asplit=2[vk][vo]"
        ";[1:a]volume=0.30[bed]"
        ";[bed][vk]sidechaincompress=threshold=0.02:ratio=10:attack=30:release=600[duck]"
        ";[duck][vo]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95[aout]"
        f";[0:v]tpad=stop_mode=clone:stop_duration=5,trim=duration={TARGET},setpts=PTS-STARTPTS[vout]")
    cmd += ['-filter_complex', graph, '-map', '[vout]', '-map', '[aout]', '-t', str(TARGET), '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-crf', '22', '-preset', 'medium', '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', str(OUT / 'dot-demo-5min.mp4')]
    subprocess.run(cmd, check=True)
    print('mixed', round(duration(OUT / 'dot-demo-5min.mp4'), 2), 's ->', OUT / 'dot-demo-5min.mp4')


if __name__ == '__main__':
    stage = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if stage in ('tts', 'all'):
        asyncio.run(_tts())
    if stage in ('record', 'all'):
        record()
    if stage in ('mix', 'all'):
        mix()
