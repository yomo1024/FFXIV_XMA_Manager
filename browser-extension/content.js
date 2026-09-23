// FFXIV Mod 管理器助手 —— 页面脚本：Mod 页面右下角的小面板（含队列与进度）
(() => {
  if (window.__ffmm_loaded) return;
  window.__ffmm_loaded = true;

  const send = (msg) => new Promise((res) => {
    try { chrome.runtime.sendMessage(msg, (r) => res(r || { ok: false, error: '扩展没响应' })); }
    catch (e) { res({ ok: false, error: String(e) }); }
  });

  /* ---------------- 读页面 ---------------- */
  function readPage() {
    const abs = (h) => { try { return h ? new URL(h, location.href).href : ''; } catch (e) { return h || ''; } };
    const links = [].slice.call(document.querySelectorAll('a'));
    const cands = [];
    const byId = document.querySelector('#mod-download-link'); if (byId) cands.push(byId);
    const btn = document.querySelector('#download-mod-button');
    if (btn && btn.closest && btn.closest('a')) cands.push(btn.closest('a'));
    links.forEach((e) => { if ((e.getAttribute('href') || '').indexOf('/files/') > -1) cands.push(e); });
    links.forEach((e) => { if (e.hasAttribute('download')) cands.push(e); });
    let dl = '';
    for (let i = 0; i < cands.length; i++) {
      const h = cands[i].getAttribute('href') || '';
      if (h && h !== '#' && h.indexOf('javascript:') !== 0) { dl = abs(h); break; }
    }
    const h1 = document.querySelector('h1');
    const ua = links.filter((e) => (e.getAttribute('href') || '').indexOf('/user/') === 0)[0];
    const img = document.querySelector('img[src*="/mod-images/"]');
    const imgs = [];
    [].slice.call(document.querySelectorAll('img')).forEach((i) => {
      const u = i.src || '';
      if (/mod-images|xmimg|static\.xivmodarchive/i.test(u) && imgs.indexOf(u) < 0) imgs.push(u);
    });
    const text = (document.body ? document.body.innerText : '').slice(0, 1200);
    // 站点标签：页面上是 "Tags : a, b, c" 的纯文本（.mod-meta-block 里）
    const tags = [], meta = { races: '', genders: '', mtype: '' };
    [].slice.call(document.querySelectorAll('.mod-meta-block,div,p,li')).forEach((e) => {
      if (e.children.length > 3) return;
      const t = (e.innerText || '').trim();
      if (!tags.length) {
        const m2 = t.match(/^Tags\s*:\s*([\s\S]*)$/i);
        if (m2) m2[1].split(',').forEach((x) => { x = x.trim(); if (x && tags.indexOf(x) < 0) tags.push(x); });
      }
      let m3;
      if (!meta.races && (m3 = t.match(/^Races?\s*:\s*(.+)$/i))) meta.races = m3[1].trim();
      if (!meta.genders && (m3 = t.match(/^Genders?\s*:\s*(.+)$/i))) meta.genders = m3[1].trim();
      if (!meta.mtype && (m3 = t.match(/^Type\s*:\s*(.+)$/i))) meta.mtype = m3[1].trim();
    });
    const m = location.href.match(/\/modid\/(\d+)/);
    return {
      v: 2, url: location.href, modid: m ? m[1] : '',
      tags: tags, races: meta.races, genders: meta.genders, mtype: meta.mtype,
      name: h1 ? h1.innerText.trim() : document.title.replace(/\s*\|.*$/, ''),
      author: ua ? ua.innerText.trim() : '',
      cover: img ? img.src : (imgs[0] || ''),
      imgs: imgs.slice(0, 60), dl: dl, title: document.title,
      addr: m ? ('https://www.xivmodarchive.com/modid/' + m[1]) : location.href,
      nsfw: /nsfw|adult|18\+/i.test(text)
    };
  }

  /* ---------------- 面板 ---------------- */
  const STATE_TXT = { queued: '排队中', downloading: '下载中', importing: '入库中', done: '已完成', error: '失败' };
  let CATS = [], tagsTouched = false, timerQ = null;

  function panel() {
    let p = document.getElementById('ffmm-panel');
    if (p) return p;
    p = document.createElement('div');
    p.id = 'ffmm-panel';
    p.innerHTML =
      '<div class="mm-head"><span>FFXIV Mod 管理器</span><span class="mm-x" title="收起">×</span></div>' +
      '<div class="mm-body">' +
      '  <div class="mm-name">读取中…</div>' +
      '  <div class="mm-sub"></div>' +
      '  <label>分类 <select id="ffmm-cat"><option value="">（待导入）</option></select></label>' +
      '  <label>子分类 <input id="ffmm-sub" list="ffmm-sublist" placeholder="可空"><datalist id="ffmm-sublist"></datalist></label>' +
      '  <label>类型 <select id="ffmm-zone"><option>SFW</option><option>NSFW</option></select></label>' +
      '  <label>标签 <input id="ffmm-tags" placeholder="自动带出站点标签，可改"></label>' +
      '  <div class="mm-tagsrc"></div>' +
      '  <button id="ffmm-dl" disabled>⬇ 加入队列（下载并导入）</button>' +
      '  <button id="ffmm-push">只送信息到管理器</button>' +
      '  <div class="mm-status"></div>' +
      '  <div class="mm-queue">' +
      '    <div class="mm-qhead"><span>队列 <b id="ffmm-qn">0</b></span>' +
      '      <span><a id="ffmm-qclear">清空已完成</a><a id="ffmm-qhide">收起</a></span></div>' +
      '    <div id="ffmm-qlist"></div>' +
      '  </div>' +
      '</div>';
    document.body.appendChild(p);
    p.querySelector('.mm-x').onclick = () => { p.style.display = 'none'; };

    const $ = (id) => p.querySelector(id);
    const setSt = (t, bad) => { $('.mm-status').innerHTML = t; $('.mm-status').style.color = bad ? '#ff9a9a' : '#9ee6b5'; };
    $('#ffmm-tags').addEventListener('input', () => { tagsTouched = true; });
    $('#ffmm-qhide').onclick = () => {
      const q = $('#ffmm-qlist');
      const hide = q.style.display !== 'none';
      q.style.display = hide ? 'none' : '';
      $('#ffmm-qhide').textContent = hide ? '展开' : '收起';
    };
    $('#ffmm-qclear').onclick = async () => { await send({ type: 'queueClear' }); renderQueue(); };

    (async () => {
      const o = await send({ type: 'options' });
      if (!o.ok) { p.classList.add('mm-off'); setSt('连接不到管理器：' + o.error, true); renderQueue(); return; }
      const cat = $('#ffmm-cat');
      const names = (o.cats || []).map((c) => (c && c.name) ? c.name : String(c || '')).filter(Boolean);
      cat.innerHTML = '<option value="">（待导入）</option>' +
        names.map((n) => '<option>' + n.replace(/</g, '&lt;') + '</option>').join('');
      if (names.length) cat.value = names[0];
      CATS = (o.cats || []);
      const fillSub = () => {
        const one = CATS.filter((x) => x && x.name === cat.value)[0];
        const subs = ((one && one.subcats) || []).concat((one && one.disk_subcats) || [])
          .filter((v, i, a) => a.indexOf(v) === i);
        $('#ffmm-sublist').innerHTML = subs.map((s) => '<option>' + String(s).replace(/</g, '&lt;') + '</option>').join('');
      };
      cat.addEventListener('change', fillSub);
      fillSub();
      setSt('管理器已连接（端口 ' + (o.base || '').split(':').pop() + '）');
      refresh(); renderQueue();
    })();

    function refresh() {
      const info = readPage();
      $('.mm-name').textContent = info.name || '（没读到名称）';
      $('.mm-sub').textContent = (info.author ? '作者：' + info.author + ' ' : '') +
        (info.dl ? '· 已找到下载链接' : '· 没找到下载链接（可能要登录）');
      $('#ffmm-zone').value = info.nsfw ? 'NSFW' : 'SFW';
      if (!tagsTouched) $('#ffmm-tags').value = (info.tags || []).join(', ');
      $('.mm-tagsrc').textContent = (info.tags && info.tags.length)
        ? ('站点标签 ' + info.tags.length + ' 个（已自动填入，可修改）')
        : '这个页面没读到标签（可能要登录）';
      $('#ffmm-dl').disabled = !info.dl;
      return info;
    }

    $('#ffmm-push').onclick = async () => {
      const info = refresh();
      setSt('正在送信息…');
      const r = await send({ type: 'push', page: info });
      setSt(r.ok ? '已送到管理器（去「下载工作台」看）' : ('失败：' + r.error), !r.ok);
    };
    $('#ffmm-dl').onclick = async () => {
      const info = refresh();
      if (!info.dl) return setSt('没有下载链接：先在这个浏览器里登录 XIVModArchive', true);
      const cat = $('#ffmm-cat').value, zone = $('#ffmm-zone').value;
      const subdir = ($('#ffmm-sub').value || '').trim();
      const tags = ($('#ffmm-tags').value || '').split(/[,，、]/).map((s) => s.trim()).filter(Boolean);
      const r = await send({
        type: 'enqueue', page: Object.assign({}, info, { tags: tags }),
        category: cat, zone: zone, subdir: subdir, tags: tags
      });
      if (!r.ok) return setSt('加入队列失败：' + r.error, true);
      setSt(r.dup ? '这条已经在队列里了' : ('已加入队列 ✓ 会自动下载并入库到「' + (cat || '待导入') + '」'));
      renderQueue();
    };

    // 定时刷（按钮状态 + 队列进度）
    setInterval(() => {
      try {
        if (!document.body.contains(p) || p.style.display === 'none') return;
        const info = refresh();
        $('#ffmm-dl').disabled = !info.dl;
      } catch (e) { }
    }, 2500);
    return p;
  }

  /* ---------------- 队列显示 ---------------- */
  async function renderQueue() {
    const p = document.getElementById('ffmm-panel');
    if (!p) return;
    const box = p.querySelector('#ffmm-qlist');
    const r = await send({ type: 'queue' });
    const q = (r && r.queue) || [];
    p.querySelector('#ffmm-qn').textContent = q.length;
    if (!q.length) {
      box.innerHTML = '<div class="mm-qempty">（空）</div>';
      if (timerQ) { clearTimeout(timerQ); timerQ = null; }
      return;
    }
    box.innerHTML = q.map((t) => {
      const pct = Math.max(0, Math.min(100, t.pct || 0));
      const cls = t.state === 'error' ? 'mm-q err' : (t.state === 'done' ? 'mm-q ok' : 'mm-q');
      const right = (t.state === 'done')
        ? '<span class="mm-qact" data-retry="' + t.id + '" style="display:none"></span>'
        : '<span class="mm-qact" data-del="' + t.id + '" title="移除">✕</span>';
      return '<div class="' + cls + '" data-id="' + t.id + '">' +
        '<div class="mm-qrow"><span class="mm-qname">' + esc(t.name) +
        (t.subdir ? '<i> · ' + esc(t.subdir) + '</i>' : '') + '</span>' + right + '</div>' +
        '<div class="mm-qbar"><i style="width:' + pct + '%"></i></div>' +
        '<div class="mm-qinfo">' + STATE_TXT[t.state] + ' ' + pct + '%' +
        (t.state === 'done' && t.result && (t.result.rel || t.result.inbox)
          ? ' · ' + esc(t.result.rel || t.result.inbox) : '') +
        (t.state === 'error' && t.error ? ' · ' + esc(String(t.error).slice(0, 70)) : '') +
        (t.state !== 'done' && t.state !== 'error' && t.detail ? ' · ' + esc(String(t.detail).slice(0, 60)) : '') +
        '</div></div>';
    }).join('');
    box.querySelectorAll('[data-del]').forEach((e) => {
      e.onclick = async () => { await send({ type: 'queueRemove', id: e.getAttribute('data-del') }); renderQueue(); };
    });
    // 有在跑的就 1.5 秒刷新一次
    if (q.some((t) => ['queued', 'downloading', 'importing'].indexOf(t.state) >= 0)) {
      if (!timerQ) timerQ = setTimeout(() => { timerQ = null; renderQueue(); }, 1500);
    }
  }
  function esc(s) { return String(s == null ? '' : s).replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c])); }

  try {
    chrome.runtime.onMessage.addListener((m) => { if (m && m.type === 'queueChanged') renderQueue(); });
  } catch (e) { }

  /* ---------------- 挂载 ---------------- */
  function boot() {
    if (!/\/modid\/\d+/.test(location.href)) {
      const p = document.getElementById('ffmm-panel');
      if (p) p.style.display = 'none';
      return;
    }
    panel();
  }
  boot();
  let last = location.href;
  setInterval(() => {
    if (location.href !== last) {
      last = location.href;
      const p = document.getElementById('ffmm-panel');
      if (p) p.remove();
      boot();
    }
  }, 1200);
})();
