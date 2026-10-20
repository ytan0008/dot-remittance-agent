import pytest
from fastapi.testclient import TestClient
from finance.api import create_app
from finance.domain import Config
from finance.service import Finance
from conftest import FakeRates

H = {'X-Workspace-Request': '1'}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('OWNER_TOKEN', 'o' * 32)
    monkeypatch.setenv('AGENT_TOKEN', 'a' * 32)
    monkeypatch.delenv('ALLOW_SIGNUP', raising=False)
    f = Finance(Config(db=str(tmp_path / 'web.db')), rates=FakeRates())
    f.set_cash('owner', 'AUD', '3250')  # the data already on this instance
    return create_app(f, background=False)


def test_existing_data_is_claimed_only_with_the_owner_token(app):
    with TestClient(app) as stranger, TestClient(app) as owner, TestClient(app) as friend:
        assert owner.get('/health').json()['accounts'] is False
        assert owner.post('/auth/register', json={'email': 'me@example.com', 'password': 'correct horse'}).status_code == 403  # same-origin header
        # being first is not ownership: a stranger who signs up first gets an empty space
        stranger.post('/auth/register', headers=H, json={'email': 'first@example.com', 'password': 'correct horse'})
        assert stranger.get('/overview/money').json()['position']['currencies'] == []
        assert stranger.post('/auth/claim', headers=H, json={'owner_token': 'x' * 32}).json()['code'] == 'auth_token'
        assert owner.post('/auth/register', headers=H, json={'email': 'me@example.com', 'password': 'correct horse', 'owner_token': 'nope'}).json()['code'] == 'auth_token'
        r = owner.post('/auth/register', headers=H, json={'email': 'Me@Example.com', 'password': 'correct horse', 'name': 'Tom', 'owner_token': 'o' * 32})
        assert r.status_code == 200 and r.json()['user'] == {'email': 'me@example.com', 'name': 'Tom'}
        assert 'HttpOnly' in r.headers['set-cookie']
        assert owner.get('/overview/money').json()['position']['currencies'][0]['amount'] == 325000  # the owner token proves it
        assert stranger.post('/auth/claim', headers=H, json={'owner_token': 'o' * 32}).json()['code'] == 'auth_claimed'  # only once
        r = friend.post('/auth/register', headers=H, json={'email': 'friend@example.com', 'password': 'another secret'})
        assert r.status_code == 200
        assert friend.get('/overview/money').json()['position']['currencies'] == []  # a fresh, empty workspace
        assert friend.put('/cash', headers=H, json={'currency': 'CNY', 'amount': '900'}).status_code == 200
        assert [c['currency'] for c in owner.get('/overview/money').json()['position']['currencies']] == ['AUD']  # never mixed
        assert friend.get('/session').json()['user']['email'] == 'friend@example.com'
        assert owner.get('/health').json()['accounts'] is True


def test_claim_after_signing_up(app):
    with TestClient(app) as c:
        c.post('/auth/register', headers=H, json={'email': 'me@example.com', 'password': 'correct horse'})
        assert c.get('/overview/money').json()['position']['currencies'] == []
        assert c.post('/auth/claim', headers=H, json={'owner_token': 'o' * 32}).json()['claimed'] is True
        assert c.get('/overview/money').json()['position']['currencies'][0]['amount'] == 325000
        c.delete('/session', headers=H)
        c.post('/auth/login', headers=H, json={'email': 'me@example.com', 'password': 'correct horse'})
        assert c.get('/overview/money').json()['position']['currencies'][0]['amount'] == 325000  # kept across sign-ins


def test_sign_in_rules(app):
    with TestClient(app) as c:
        assert c.post('/auth/register', headers=H, json={'email': 'me@example.com', 'password': 'short'}).json()['code'] == 'auth_password_short'
        assert c.post('/auth/register', headers=H, json={'email': 'me@example.com', 'password': 'aaaaaaaaaa'}).json()['code'] == 'auth_password_weak'
        assert c.post('/auth/register', headers=H, json={'email': 'not-an-email', 'password': 'correct horse'}).json()['code'] == 'auth_email'
        assert c.post('/auth/register', headers=H, json={'email': 'me@example.com', 'password': 'correct horse'}).status_code == 200
        assert c.post('/auth/register', headers=H, json={'email': 'me@example.com', 'password': 'correct horse'}).json()['code'] == 'auth_exists'
        c.delete('/session', headers=H)
        assert c.get('/session').status_code == 401
        assert c.post('/auth/login', headers=H, json={'email': 'me@example.com', 'password': 'correct horse'}).status_code == 200
        assert c.get('/session').json()['role'] == 'owner'
        c.delete('/session', headers=H)
        for _ in range(5):
            assert c.post('/auth/login', headers=H, json={'email': 'me@example.com', 'password': 'wrong one'}).json()['code'] == 'auth_failed'
        locked = c.post('/auth/login', headers=H, json={'email': 'me@example.com', 'password': 'correct horse'})
        assert locked.json()['code'] == 'auth_locked'  # even the right password waits after five misses
        assert c.post('/auth/login', headers=H, json={'email': 'nobody@example.com', 'password': 'x'}).json()['code'] == 'auth_failed'


def test_sign_up_can_be_closed(app, monkeypatch):
    with TestClient(app) as c:
        c.post('/auth/register', headers=H, json={'email': 'me@example.com', 'password': 'correct horse'})
        monkeypatch.setenv('ALLOW_SIGNUP', 'false')
        assert c.post('/auth/register', headers=H, json={'email': 'b@example.com', 'password': 'correct horse'}).json()['code'] == 'auth_closed'
        assert c.get('/health').json()['signup'] is False
        # closed means closed, even before the first account; only the owner (with the token) can set up
        r = c.post('/auth/register', headers=H, json={'email': 'own@example.com', 'password': 'correct horse', 'owner_token': 'o' * 32})
        assert r.status_code == 200


def test_the_demo_never_opens_real_data(app, monkeypatch):
    monkeypatch.setenv('ENABLE_DEMO_LOGIN', 'true')
    with TestClient(app) as c:
        assert c.post('/session/demo', headers=H).status_code == 200
        assert c.get('/overview/money').json()['position']['currencies'] == []  # not the owner's 3,250 AUD
        c.put('/cash', headers=H, json={'currency': 'USD', 'amount': '10'})
    with TestClient(app) as other:
        other.post('/session/demo', headers=H)
        assert other.get('/overview/money').json()['position']['currencies'] == []  # every demo visitor has their own space
    with TestClient(app) as owner:
        owner.post('/auth/register', headers=H, json={'email': 'me@example.com', 'password': 'correct horse', 'owner_token': 'o' * 32})
        assert [x['currency'] for x in owner.get('/overview/money').json()['position']['currencies']] == ['AUD']
