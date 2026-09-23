// FFXIV Mod 管理器助手 —— 后台：跟本地管理器说话 + 用自己的登录态下载 + 队列调度
const PORTS = Array.from({ length: 36 }, (_, i) => 8765 + i);
const QKEY = 'queue';
let BASE = null;
let RUNNING = false;

/* ---------------- 跟管理器通信 ---------------- */
async function ping(b, ms) {
  const ac = ('AbortController' in self) ? new AbortController() : null;
  const timer = ac ? setTimeout(() => ac.abort(), ms || 900) : null;
  try {
    const r = await fetch(b + '/api/state', { cache: 'no-store', signal: ac ? ac.signal : undefined });
    return r.ok;
  } catch (e) { return false; }
  finally { if (timer) clearTimeout(timer); }
}
async function findBase(force) {
  if (BASE && !force) return BASE;
  const st = await chrome.storage.local.get(['port']);
  if (st.port) {
    const b = 'http://127.0.0.1:' + st.port;
    if (await ping(b, 1200)) { BASE = b; return BASE; }
  }
  const bases = PORTS.map((p) => 'http://127.0.0.1:' + p);
  const hit = await new Promise((res) => {
    let left = bases.length, done = false;
    bases.forEach((b) => {
      ping(b, 900).then((ok) => {
        if (ok && !done) { done = true; res(b); }
        if (--left === 0 && !done) res(null);
      });
    });
  });
  if (!hit) { BASE = null; return null; }
  BASE = hit;
  try { await chrome.storage.local.set({ port: parseInt(hit.split(':').pop(), 10) }); } catch (e) { }
  return BASE;
}
async function api(path, opts) {
  const b = await findBase();
  if (!b) throw new Error('没找到 Mod 管理器 —— 先在管理器里点「启动Web版」');
  const r = await fetch(b + path, Object.assign({ cache: 'no-store' }, opts || {}));
  const t = await r.text();
  let j = {};
  try { j = JSON.parse(t); } catch (e) { }
  if (!r.ok) throw new Error((j && j.error) || ('HTTP ' + r.status));
  return j;
}
const jpost = (path, body) => api(path, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {})
});

/* ---------------- 队列（存在 storage：后台被回收、页面关掉都不丢） ---------------- */
async function getQ() { const o = await chrome.storage.local.get([QKEY]); return o[QKEY] || []; }
async function setQ(q) {
  await chrome.storage.local.set({ [QKEY]: q });
  try { chrome.runtime.sendMessage({ type: 'queueChanged' }); } catch (e) { }
}
async function patch(id, p) {
  const q = await getQ();
  const i = q.findIndex((t) => t.id === id);
  if (i >= 0) { Object.assign(q[i], p); await setQ(q); }
  return q[i];
}
async function enqueue(msg) {
  const page = msg.page || {};
  if (!page.dl) throw new Error('这个页面上没有下载链接（先在这个浏览器里登录 XIVModArchive）');
  const q = await getQ();
  const key = (page.modid || '') + '|' + (page.dl || '');
  const dup = q.filter((t) => ((t.modid || '') + '|' + (t.page && t.page.dl || '')) === key
    && ['queued', 'downloading', 'importing'].indexOf(t.state) >= 0);
  if (dup.length) return { ok: true, dup: true, id: dup[0].id };
  const it = {
    id: String(Date.now()) + '-' + Math.random().toString(36).slice(2, 7),
    modid: page.modid || '', name: page.name || page.title || page.url || '(未命名)',
    category: msg.category || '', zone: msg.zone || 'SFW', subdir: msg.subdir || '',
    tags: msg.tags || page.tags || [], page: page,
    state: 'queued', pct: 0, detail: '排队中…', ts: Date.now()
  };
  q.push(it);
  await setQ(q);
  pump();
  return { ok: true, id: it.id };
}

async function runOne(it) {
  try {
    await patch(it.id, { state: 'downloading', pct: 0, detail: '推页面信息…' });
    await jpost('/api/inbox/page', it.page);
    await patch(it.id, { detail: '开始下载…' });
    const dlId = await chrome.downloads.download({
      url: it.page.dl, conflictAction: 'uniquify', saveAs: false
    });
    await patch(it.id, { dlId: dlId });
    const doneDl = await waitDownload(dlId, it.id, 60 * 60);
    if (!doneDl) { await patch(it.id, { state: 'error', error: '下载被取消' }); return; }

    await patch(it.id, { state: 'importing', pct: 100, detail: '交给管理器入库…' });
    // 管理器一次只能跑一个任务：等它空下来
    for (let i = 0; i < 1800; i++) {
      let s = null;
      try { s = await api('/api/job'); } catch (e) { }
      if (!s || s.state !== 'running') break;
      await new Promise((r) => setTimeout(r, 1000));
    }
    await jpost('/api/push/downloaded', {
      file: doneDl.filename, page: it.page, tags: it.tags || it.page.tags || [],
      name: it.page.name || '', author: it.page.author || '', addr: it.page.addr || '',
      cover_url: it.page.cover || '', category: it.category, zone: it.zone,
      subdir: it.subdir, export: true
    });
    let snap = null;
    for (let i = 0; i < 1800; i++) {
      await new Promise((r) => setTimeout(r, 700));
      try { snap = await api('/api/job'); } catch (e) { }
      if (snap && snap.kind === 'importfile') {
        await patch(it.id, { pct: (snap.pct == null ? 100 : snap.pct), detail: snap.text || '入库中…' });
        if (['done', 'error', 'cancelled'].indexOf(snap.state) >= 0) break;
      }
    }
    if (snap && snap.state === 'done') {
      const res = snap.result || {};
      await patch(it.id, { state: 'done', pct: 100, detail: '', result: res });
    } else {
      await patch(it.id, { state: 'error', error: (snap && snap.error) || '入库没成功' });
    }
  } catch (e) {
    await patch(it.id, { state: 'error', error: String((e && e.message) || e) });
  }
}

async function waitDownload(id, itemId, secs) {
  const t0 = Date.now();
  let seen = false, lastPct = 0;
  for (;;) {
    let it = null;
    try { const r = await chrome.downloads.search({ id }); it = r && r[0]; } catch (e) { }
    if (it && it.state) {
      seen = true;
      const tot = it.totalBytes || it.fileSize || 0;
      const got = it.bytesReceived || 0;
      const pct = tot > 0 ? Math.min(99, Math.floor(got * 100 / tot)) : (lastPct || 0);
      lastPct = pct;
      await patch(itemId, {
        pct: pct,
        detail: '下载中… ' + pct + '%（' + mb(got) + (tot ? ' / ' + mb(tot) : '') + '）'
      });
      if (it.state === 'complete') return it;
      if (it.state === 'interrupted') throw new Error('下载被中断：' + (it.error || '未知原因'));
    } else if (!seen && (Date.now() - t0) / 1000 > 20) {
      throw new Error('浏览器没能开始下载（可以自己点页面上的下载按钮，再用「监视下载目录」）');
    }
    if ((Date.now() - t0) / 1000 > secs) throw new Error('等下载完成超时');
    await new Promise((r) => setTimeout(r, 800));
  }
}
function mb(n) { return n > 1048576 ? (n / 1048576).toFixed(1) + 'MB' : Math.max(1, Math.round(n / 1024)) + 'KB'; }

async function pump() {
  if (RUNNING) return;
  RUNNING = true;
  try {
    for (;;) {
      const q = await getQ();
      const next = q.filter((t) => t.state === 'queued')[0];
      if (!next) break;
      await runOne(next);
    }
  } finally { RUNNING = false; }
}

/* ---------------- 消息 ---------------- */
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  (async () => {
    try {
      if (msg.type === 'options') {
        const cats = await api('/api/categories');
        let state = null;
        try { state = await api('/api/state'); } catch (e) { }
        reply({ ok: true, cats: cats.cats || [], state: state, base: await findBase() });
      } else if (msg.type === 'push') {
        reply({ ok: true, r: await jpost('/api/inbox/page', msg.page) });
      } else if (msg.type === 'enqueue') {
        reply(await enqueue(msg));
      } else if (msg.type === 'queue') {
        reply({ ok: true, queue: await getQ(), base: await findBase() });
      } else if (msg.type === 'queueClear') {
        const q = (await getQ()).filter((t) => ['queued', 'downloading', 'importing'].indexOf(t.state) >= 0);
        await setQ(q);
        reply({ ok: true, queue: q });
      } else if (msg.type === 'queueRemove') {
        const q = await getQ();
        const it = q.filter((t) => t.id === msg.id)[0];
        if (it) {
          if (it.state === 'downloading' && it.dlId) { try { await chrome.downloads.cancel(it.dlId); } catch (e) { } }
          if (it.state === 'importing') { try { await jpost('/api/job/cancel', {}); } catch (e) { } }
        }
        const left = q.filter((t) => t.id !== msg.id);
        await setQ(left);
        reply({ ok: true, queue: left });
      } else if (msg.type === 'retry') {
        const q = await getQ();
        const i = q.findIndex((t) => t.id === msg.id);
        if (i >= 0) { q[i].state = 'queued'; q[i].pct = 0; q[i].detail = '排队中…'; q[i].error = ''; await setQ(q); pump(); }
        reply({ ok: true, queue: q });
      } else if (msg.type === 'status') {
        reply({ ok: true, base: await findBase(msg.force) });
      } else if (msg.type === 'setPort') {
        await chrome.storage.local.set({ port: Number(msg.port) || 0 });
        BASE = null;
        reply({ ok: true, base: await findBase(true) });
      } else {
        reply({ ok: false, error: '不认识的消息：' + msg.type });
      }
    } catch (e) {
      reply({ ok: false, error: String((e && e.message) || e) });
    }
  })();
  return true;
});

// 后台被回收后，再被唤醒时如果还有排队中的任务就接着跑
chrome.storage.onChanged.addListener((ch, area) => { if (area === 'local' && ch[QKEY]) pump(); });
pump();
