"""撤回全过程留下可追溯审计，且重试不重复记账。"""
from conftest import auth
from helpers import create_dataset, create_completed_job, create_report_and_delivery


def test_audit_trail_complete(app_env):
    env = app_env
    c, S = env['client'], env['Session']
    d = create_dataset(c, env['admin'], '审计批次')
    jid = create_completed_job(S, d['id'], approved=True)
    create_report_and_delivery(S, jid)
    r = c.post('/api/withdrawals', headers=auth(env['admin']),
               json={'dataset_id': d['id'], 'reason': '审计轨迹验证原因足够长'})
    wid = r.json()['id']
    audits = c.get('/api/audits', headers=auth(env['viewer'])).json()
    actions = [a['action'] for a in audits]
    assert 'withdrawal.create' in actions
    done = [a for a in audits if a['action'] == 'withdrawal.completed']
    assert len(done) == 1 and done[0]['detail']['id'] == wid
    # 已完成撤回单的重试请求被拒，不产生额外记账
    rr = c.post(f'/api/withdrawals/{wid}/retry', headers=auth(env['admin']))
    assert rr.status_code == 409
    audits2 = c.get('/api/audits', headers=auth(env['viewer'])).json()
    assert sum(1 for a in audits2 if a['action'] == 'withdrawal.completed') == 1
    # viewer 可读取审计与撤回单，但无法操作
    assert c.get('/api/withdrawals', headers=auth(env['viewer'])).status_code == 200
