import {datasets,withdrawals} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {WithdrawalStatus,JobStatus} from '../constants/enums.js';
import {esc,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';

const badge=w=>{
 const cls=w.status==='completed'?'ok':(w.status==='failed'?'bad':'run');
 return '<span class="withdrawal-badge '+cls+'">'+esc(WithdrawalStatus[w.status]||w.status)+'</span>';
};
const affectedBlock=w=>{
 const a=w.affected||{};
 const jobs=a.jobs||[],reports=a.reports||[],deliveries=a.deliveries||[];
 return '<div class="affected"><div><strong>关联试算 '+jobs.length+'</strong>'+
   (jobs.map(j=>'<span class="chip '+(j.voided?'void':'')+'">#'+j.id+' '+esc(j.name)+' · '+esc(JobStatus[j.status]||j.status)+(j.approved?' · 已批准':'')+'</span>').join('')||'<span class="muted">无</span>')+'</div>'+
   '<div><strong>分发计划 '+reports.length+'</strong>'+(reports.map(r=>'<span class="chip">#'+r.id+' '+esc(r.name)+'</span>').join('')||'<span class="muted">无</span>')+'</div>'+
   '<div><strong>归档文件 '+deliveries.length+'（保留审计 · 禁下载）</strong>'+(deliveries.map(d=>'<span class="chip blocked">#'+d.id+' '+esc(d.filename||'归档')+'</span>').join('')||'<span class="muted">无</span>')+'</div></div>';
};

export async function withdrawalPage(){
 workspace.datasets=await datasets.list();
 const list=await withdrawals.list();
 const isAdmin=session.user.role==='admin';
 return heading('06 / WITHDRAWAL','领餐批次整批撤回','档口记错时由负责人整批撤回。撤回优先于批准与迟到写回：排队与运行中试算作废、批准失效、分发停用、归档留痕但禁下载，其他批次照常使用。','<button class="button" id="refresh-withdrawals">刷新撤回单 ↻</button>')+
 '<div class="withdrawal-grid"><section class="panel">'+
 (isAdmin?'<div class="section-title"><h2>发起整批撤回</h2></div><form id="withdrawal-form"><label>选择记错档口的领餐批次<select name="dataset_id" required>'+workspace.datasets.map(d=>'<option value="'+d.id+'" '+(d.withdrawn?'disabled':'')+'>'+esc(d.name)+' · '+d.rows+' 条'+(d.withdrawn?' · 已存在撤回单':'')+'</option>').join('')+'</select></label><label>撤回原因（将写入审计与撤回单）<textarea name="reason" rows="4" required minlength="4" maxlength="500" placeholder="例如：11 月第一周批次误记为二楼档口，厨房衍生建议需立即停用"></textarea></label><button type="submit" class="danger" '+(workspace.datasets.length?'':'disabled')+'>确认整批撤回 ↗</button><p class="hint">撤回立即生效且不可恢复；已归档文件保留供审计但拒绝下载。观察员与分析员无此入口。</p></form>':'<p class="hint">仅业务负责人可发起或重试撤回，当前账号只读查看撤回记录。</p>')+
 '</section><section><div class="section-title"><h2>撤回单</h2><span>'+list.length+' 单</span></div><div class="withdrawal-list">'+
 (list.map(w=>'<article class="withdrawal-card"><div class="withdrawal-head"><strong>撤回单 #'+w.id+' · 批次 #'+w.dataset_id+' '+esc((w.affected?.dataset?.name)||'')+'</strong>'+badge(w)+'</div><p class="reason">'+esc(w.reason)+'</p>'+affectedBlock(w)+
   '<div class="withdrawal-meta"><span>提交 '+date(w.created_at)+'</span>'+(w.finished_at?'<span>完成 '+date(w.finished_at)+'</span>':'<span>更新 '+date(w.updated_at)+'</span>')+'</div>'+
   (w.error?'<p class="warning">处理失败：'+esc(w.error)+'</p>':'')+
   (w.status==='failed'&&isAdmin?'<button class="button small danger" data-retry="'+w.id+'">重试失败撤回</button>':'')+
   (w.status==='processing'?'<p class="hint">处理中断将由后台自动恢复，也可稍后刷新。</p>':'')+
   '</article>').join('')||'<p class="empty">尚无撤回单。批次记错档口时，负责人可在此整批撤回。</p>')+
 '</div></section></div>';
}

export function bindWithdrawals(refresh){
 document.querySelector('#refresh-withdrawals').onclick=refresh;
 const form=document.querySelector('#withdrawal-form');
 if(form)submit(form,async f=>{
   if(!confirm('整批撤回不可恢复：关联试算作废、批准失效、分发停用、归档禁下载。确认继续？'))return;
   await withdrawals.create({dataset_id:Number(f.get('dataset_id')),reason:f.get('reason')});
   notify('撤回已生效，关联对象已全部处置');await refresh();
 });
 document.querySelectorAll('[data-retry]').forEach(b=>b.onclick=async()=>{
   try{const w=await withdrawals.retry(b.dataset.retry);notify(w.status==='completed'?'撤回重试成功，已全部处置':'撤回仍在处理中');await refresh();}
   catch(e){notify(e.message,true);}
 });
}
