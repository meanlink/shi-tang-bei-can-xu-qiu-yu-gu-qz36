from conftest import auth
from helpers import create_dataset, create_completed_job


def test_overview_excludes_withdrawn_approved_count(app_env):
    env = app_env
    c, S = env['client'], env['Session']
    d1 = create_dataset(c, env['admin'], '总览撤回批次')
    d2 = create_dataset(c, env['admin'], '总览正常批次')
    create_completed_job(S, d1['id'], approved=True)  # 撤回后不计入已批准
    j2 = create_completed_job(S, d2['id'], approved=True)
    before = c.get('/api/overview', headers=auth(env['viewer'])).json()
    assert before['approved'] == 2
    c.post('/api/withdrawals', headers=auth(env['admin']),
           json={'dataset_id': d1['id'], 'reason': '总览统计验证原因足够长'})
    after = c.get('/api/overview', headers=auth(env['viewer'])).json()
    assert after['approved'] == 1  # 撤回批次的批准失效，不再统计
    assert after['jobs'] == before['jobs']  # 任务本身不删除
    # jobs 列表仍能查到撤回任务，带 withdrawn 标记
    jobs = {j['id']: j for j in c.get('/api/jobs', headers=auth(env['viewer'])).json()}
    assert j2 in jobs and any(j['withdrawn'] for j in jobs.values())
