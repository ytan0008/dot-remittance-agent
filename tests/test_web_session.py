import pytest
from fastapi.testclient import TestClient
from finance.api import create_app, SafeJSONResponse
from finance.domain import Config
from finance.service import Finance
from conftest import FakeRates


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('OWNER_TOKEN', 'o'*32)
    monkeypatch.setenv('AGENT_TOKEN', 'a'*32)
    monkeypatch.setenv('ENABLE_DEMO_LOGIN', 'true')
    with TestClient(create_app(Finance(Config(db=str(tmp_path/'web.db')), rates=FakeRates()), background=False)) as c:
        yield c


def test_demo_cookie_and_csrf(client):
    assert client.post('/session/demo').status_code == 403
    response = client.post('/session/demo', headers={'X-Workspace-Request':'1'})
    assert response.status_code == 200
    assert 'HttpOnly' in response.headers['set-cookie']
    assert 'SameSite=strict' in response.headers['set-cookie']
    assert client.get('/session').json()['role'] == 'owner'
    assert client.get('/balances').status_code == 200
    body = {'recipient_id':'x','name':'X','currency':'CNY'}
    assert client.post('/recipients', json=body).status_code == 403
    assert client.post('/recipients', headers={'X-Workspace-Request':'1'}, json=body).status_code == 200


def test_login_logout_and_invalid_token(client):
    h = {'X-Workspace-Request':'1'}
    assert client.post('/session', headers=h, json={'token':'x'*32}).status_code == 401
    assert client.post('/session', headers=h, json={'token':'a'*32}).json()['role'] == 'agent'
    assert client.get('/audit').status_code == 409
    assert client.delete('/session', headers=h).status_code == 200
    assert client.get('/session').status_code == 401


def test_demo_disabled_with_live_chain(client):
    class Live:
        environment = 'live_chain'
    client.app.state.finance.evm = Live()
    assert client.get('/health').json()['demo_login'] is False
    assert client.post('/session/demo', headers={'X-Workspace-Request':'1'}).status_code == 403


def test_large_wei_not_rounded_in_browser():
    assert SafeJSONResponse({'fee':10000000000000001}).body == b'{"fee":"10000000000000001"}'


def test_request_ids_correlate_audit(client):
    h = {'X-Workspace-Request':'1'}
    client.post('/session/demo', headers=h)
    r = client.post('/recipients', headers=h, json={'recipient_id':'y','name':'Y','currency':'CNY'})
    rid = r.headers['x-request-id']
    events = client.get('/audit', params={'q': rid}).json()
    assert events and events[0]['request_id'] == rid
