const $ = (s) => document.querySelector(s);
const send = (m) => new Promise((r) => chrome.runtime.sendMessage(m, (x) => r(x || { ok: false, error: '扩展没响应' })));
const TXT = { queued: '排队中', downloading: '下载中', importing: '入库中', done: '已完成', error: '失败' };
const esc = (s) => String(s == null ? '' : s).replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));

(async () => {
  const r = await send({ type: 'status', force: true });
  if (r.ok && r.base) { $('#st').innerHTML = '<span class="ok">已连接</span> ' + r.base; $('#port').value = r.base.split(':').pop(); }
  else { $('#st').innerHTML = '<span class="bad">没找到管理器</span> —— 先在管理器里点「启动Web版」'; }
  render();
  setInterval(render, 1500);
})();

async function render() {
  const r = await send({ type: 'queue' });
  const q = (r && r.queue) || [];
  if (!q.length) { $('#queue').innerHTML = '<div class="empty">（队列空）</div>'; return; }
  $('#queue').innerHTML = q.map((t) => {
    const pct = Math.max(0, Math.min(100, t.pct || 0));
    const cls = t.state === 'error' ? 'qi err' : (t.state === 'done' ? 'qi ok' : 'qi');
    return '<div class="' + cls + '">' +
      '<div class="qr"><span class="qn">' + esc(t.name) + (t.subdir ? ' · ' + esc(t.subdir) : '') + '</span>' +
      '<span class="x" data-id="' + t.id + '" title="移除/重试">' +
      (t.state === 'error' ? '↻' : '✕') + '</span></div>' +
      '<div class="qb"><i style="width:' + pct + '%"></i></div>' +
      '<div class="qd">' + TXT[t.state] + ' ' + pct + '%' +
      (t.state === 'done' && t.result && t.result.updated_existing ? ' · 已覆盖更新' : '') +
      (t.state === 'done' && t.result && t.result.rel ? ' · ' + esc(t.result.rel) : '') +
      (t.state === 'error' && t.error ? ' · ' + esc(String(t.error).slice(0, 80)) : '') +
      (t.detail && t.state !== 'done' ? ' · ' + esc(String(t.detail).slice(0, 70)) : '') +
      '</div></div>';
  }).join('');
  document.querySelectorAll('.x').forEach((e) => {
    e.onclick = async () => {
      const id = e.getAttribute('data-id');
      const it = q.filter((x) => x.id === id)[0];
      if (it && it.state === 'error') await send({ type: 'retry', id: id });
      else await send({ type: 'queueRemove', id: id });
      render();
    };
  });
}

$('#clear').onclick = async () => { await send({ type: 'queueClear' }); render(); };
$('#set').onclick = async () => {
  const p = parseInt($('#port').value, 10);
  if (!p) { $('#st').innerHTML = '<span class="bad">端口填数字</span>'; return; }
  const r = await send({ type: 'setPort', port: p });
  $('#st').innerHTML = (r.ok && r.base) ? ('<span class="ok">已连接</span> ' + r.base)
                                        : '<span class="bad">连不上 127.0.0.1:' + p + '</span>';
};
