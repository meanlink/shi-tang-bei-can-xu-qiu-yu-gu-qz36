from conftest import auth
from helpers import create_dataset

def test_dataset_listing_carries_withdrawn_flag(app_env):
    env = app_env
    c = env['client']
    d1 = create_dataset(c, env['admin'], '标记批次一')
    d2 = create_dataset(c, env['admin'], '标记批次二')
    r = c.post('/api/withdrawals', headers=auth(env['admin']),
               json={'dataset_id': d1['id'], 'reason': '列表标记验证原因足够长'})
    assert r.status_code == 201
    rows = {d['id']: d for d in c.get('/api/datasets', headers=auth(env['viewer'])).json()}
    assert rows[d1['id']]['withdrawn'] is True
    assert rows[d2['id']]['withdrawn'] is False
    detail = c.get(f"/api/datasets/{d1['id']}", headers=auth(env['viewer'])).json()
    assert detail['withdrawn'] is True and 'records' in detail
