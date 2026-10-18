"""Browser acceptance against the explicitly local simulation. Creates small sandbox test payments."""
import os
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

base = os.getenv('BASE_URL', 'http://frontend')
out = Path(os.getenv('ARTIFACTS', '/artifacts'))
out.mkdir(exist_ok=True)
errors = []


def hold(page, selector, ms=1500):
    box = page.locator(selector).bounding_box()
    page.mouse.move(box['x'] + 20, box['y'] + box['height'] / 2)
    page.mouse.down(); page.wait_for_timeout(ms); page.mouse.up()


def prepare_and_authorize(page, amount, purpose):
    page.goto(base + '/#send'); page.wait_for_timeout(1200)
    page.locator('.route-chip', has_text='AU → CN').click()
    page.locator('#send-amount').fill(amount)
    expect(page.locator('.option.best')).to_be_visible(timeout=15000)
    page.locator('#send-recipient').select_option('ui-acceptance')
    page.locator('#send-purpose').fill(purpose)
    page.get_by_role('button', name='Get quote & prepare draft').click()
    expect(page.locator('#modal .env')).to_contain_text('Local simulation', timeout=10000)
    assert page.get_by_role('button', name='Submit authorized payment').count() == 0, 'draft must not be submittable'
    page.locator('#approve-check').check()
    hold(page, '#hold-approve')
    expect(page.locator('#modal .detail-top .chip')).to_contain_text('Authorized', timeout=8000)
    page.get_by_role('button', name='Submit authorized payment').click()


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={'width': 1440, 'height': 1000})
    ctx.add_init_script("try{localStorage.setItem('dot.lang','en');sessionStorage.setItem('dot.intro','1')}catch(e){}")
    page = ctx.new_page()
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and '401' not in m.text else None)
    page.goto(base)
    expect(page.locator('#side-status')).to_have_text('Service connected', timeout=30000)
    assert 'Simulation' in page.locator('#env-badge').inner_text(), 'never test spending against a live environment'

    page.goto(base + '/#wallets'); page.wait_for_timeout(1200)
    if not page.locator('.list .row', has_text='ui-acceptance').count():
        page.get_by_role('button', name='Add recipient').first.click()
        page.locator('#r-name').fill('UI acceptance payee'); page.locator('#r-id').fill('ui-acceptance')
        page.locator('#r-country').select_option('CN'); page.locator('#r-account').fill('6222000011112222')
        page.get_by_role('button', name='Save recipient').click()
        expect(page.locator('#toast')).to_contain_text('Recipient saved')

    # Happy path: compare -> draft -> hold to authorize -> submit -> async settlement -> receipt and trail.
    prepare_and_authorize(page, '12.50', 'UI acceptance · local test funds')
    expect(page.locator('#modal .detail-top .chip')).to_contain_text('Completed', timeout=30000)
    page.screenshot(path=str(out / 'receipt-flow.png'))
    page.get_by_role('button', name='Receipt').click()
    expect(page.locator('.receipt')).to_contain_text('LOCAL SIMULATION')
    page.get_by_role('button', name='Back').click()
    page.get_by_role('button', name='Audit trail').click()
    expect(page.locator('.trail-summary')).to_be_visible()
    page.keyboard.press('Escape')

    # Recovery case: the provider response is lost (x.57); the outcome stays unknown until a status query finds it.
    prepare_and_authorize(page, '12.57', 'UI acceptance · timeout recovery')
    expect(page.locator('#modal .detail-top .chip')).to_contain_text(re.compile('Outcome unknown|Submitted|Completed'), timeout=8000)
    expect(page.locator('#modal .detail-top .chip')).to_contain_text('Completed', timeout=40000)
    page.keyboard.press('Escape')

    # Agent: understand -> plan -> act, and refusal to execute without authorization.
    page.goto(base + '/#agent'); page.wait_for_timeout(1000)
    page.locator('#chat-form textarea').fill('Send 5 AUD to ui-acceptance for books')
    page.keyboard.press('Enter')
    expect(page.locator('.msg.bot.done').last).to_contain_text('Draft prepared', timeout=20000)
    expect(page.locator('.msg.bot.done').last.locator('.stage')).to_have_count(3)
    page.locator('#chat-form textarea').fill('execute it')
    page.keyboard.press('Enter')
    expect(page.locator('.msg.bot.done').last).to_contain_text('approval', timeout=20000)
    page.screenshot(path=str(out / 'agent.png'))

    page.goto(base + '/#audit'); page.wait_for_timeout(1200)
    expect(page.locator('.audit-group').first).to_be_visible()
    page.set_viewport_size({'width': 390, 'height': 844})
    for view in ('overview', 'send', 'payments'):
        page.goto(base + '/#' + view); page.wait_for_timeout(1500)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'mobile overflow on {view}'
    page.screenshot(path=str(out / 'mobile.png'))
    browser.close()

assert not errors, errors
print('PASS: compare, draft, hold-to-authorize, async settlement, receipt, trail, lost-response recovery, agent refusal, mobile layout.')
