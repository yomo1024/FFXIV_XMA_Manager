// 统一的接口调用：失败时抛出后端返回的中文错误
import { reactive } from 'vue'

// ★ 全局「正在加载」反馈：任何接口在飞的时候都能让界面显示条 + 名字 + 已用秒数。
//   为什么要全局做：以前只有「任务」（job）有进度条，而**同步接口**（索引体检、云端索引恢复、
//   云盘体检、查重、检查报告……）点下去界面一点动静都没有 —— 主人 2026-09 说「像卡死」。
//   有了它：新加的接口自动就有反馈，不用每个按钮各写一遍 loading。
export const busy = reactive({ n: 0, label: '', t0: 0, visible: false, dialog: '', dlgT0: 0, dlgLabel: '' })
let busyTimer = null

/** 弹窗类按钮专用：动作期间显示**弹窗自己的**进度浮层（任务=真进度，同步接口=动画条）
 *
 *  用法：await withDialogProgress('正在从云端索引恢复', () => api.cloudIndexRestore(false))
 *  为什么不用 busy.t0 计时：任务轮询会不停重置 busy.t0，浮层要用自己的 dlgT0 才走得准。
 */
export async function withDialogProgress(label, fn) {
  busy.dialog = label || '正在处理'
  busy.dlgLabel = label || '正在处理'      // 浮层里显示的「在等什么」用这个，
  busy.dlgT0 = Date.now()                  // 别用 busy.label（那是所有请求共用的，会被后台轮询刷掉）
  try {
    return await fn()
  } finally {
    busy.dialog = ''
    busy.dlgLabel = ''
  }
}

/** 进「加载中」：第一个请求开始计时，超过 300ms 才真的显示条（秒回的接口不闪） */
function beginBusy(label) {
  if (busy.n === 0) {
    busy.t0 = Date.now()
    busy.label = label || ''
    busyTimer = setTimeout(() => { busy.visible = true }, 300)
  }
  busy.n += 1
}

/** 出「加载中」：全部请求都回来了才收起 */
function endBusy() {
  busy.n -= 1
  if (busy.n <= 0) {
    busy.n = 0
    busy.visible = false
    busy.label = ''
    if (busyTimer) { clearTimeout(busyTimer); busyTimer = null }
  }
}

/** 接口路径 → 中文名（点下去要看懂在等什么）；带 ?xxx 的会先切掉再查 */
const BUSY_LABELS = {
  '/api/state': '读取状态',
  '/api/mods': '读取 Mod 列表',
  '/api/categories': '读取分类',
  '/api/pending': '读取待处理项',
  '/api/dupes': '查重（比对文件）',
  '/api/install': '安装检查',
  '/api/check': '检查报告',
  '/api/settings': '读取/保存设置',
  '/api/inspect': '读取包内容',
  '/api/mod/files': '读取文件清单',
  '/api/bridge': '查询游戏插件',
  '/api/bridge/propose': '送到游戏里',
  '/api/bridge/install': '装进游戏',
  '/api/cloud/state': '云盘状态统计',
  '/api/cloud/check': '云盘体检（会真下载）',
  '/api/cloud/index-restore': '从云端索引恢复',
  '/api/cloud/index-preview': '云端索引预览',
  '/api/cloud/discover': '扫描网盘新内容（同步，可能几十秒）',
  '/api/cloud/claim': '把云端内容认领进库',
  '/api/mod/replace': '上传替换载荷',
  '/api/index/health': '索引体检',
  '/api/index/repair': '索引修复',
  '/api/inbox/page': '读取浏览器推来的页面',
  '/api/tags': '读取标签',
  '/api/affects': '读取影响/替换',
  '/api/backups': '读取备份列表',
  '/api/fetch/parse': '解析页面信息',
  '/api/browser/capture': '抓取内置浏览器当前页',
  '/api/log': '读取日志',
  '/api/logs': '列出日志文件',
  '/api/quit': '退出服务',
}

async function req(path, opts = {}, label) {
  const key = String(path).split('?')[0]
  beginBusy(label || BUSY_LABELS[key] || key)
  try {
    const r = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      ...opts,
    })
    const ct = r.headers.get('content-type') || ''
    const body = ct.includes('application/json') ? await r.json().catch(() => ({})) : await r.text()
    if (!r.ok) throw new Error((body && body.error) || 'HTTP ' + r.status)
    return body
  } finally {
    endBusy()
  }
}

// ---- 让「长动作」当任务跑：起任务 → 轮询 → 返回最终 result ----
// 为什么要它：有些动作要几十秒（从云端索引恢复实测 33 秒），走同步接口时前端只能干等、
// 界面**一点反馈都没有**（主人 2026-09：「都应该有个进度条让我知道系统没卡死」）。
// 走任务就有真进度条（标题/进度/文字/取消都由任务机制给），调用点的写法完全不用变。
export async function runJob(kind, params, opts = {}) {
  const timeoutMs = opts.timeoutMs || 30 * 60 * 1000
  // 起任务本身是秒回的；失败（比如已有任务在跑）会抛后端那句中文错误
  await req('/api/job', { method: 'POST', body: JSON.stringify({ kind, params: params || {} }) },
    JOB_TITLES[kind] || kind)
  const t0 = Date.now()
  for (;;) {
    await new Promise((r) => setTimeout(r, 400))
    const s = await req('/api/job')
    if (s && s.state === 'running') {
      if (Date.now() - t0 > timeoutMs) throw new Error('任务超时（可在任务条上点取消）')
      continue
    }
    if (!s || s.state === 'idle') throw new Error('任务不见了（服务可能重启过）')
    if (s.state === 'error') throw new Error(s.error || '任务失败')
    if (s.state === 'cancelled') throw new Error('已取消')
    return s.result
  }
}

export const api = {
  get: (p) => req(p),
  post: (p, body) => req(p, { method: 'POST', body: JSON.stringify(body || {}) }),

  state: () => req('/api/state'),
  mods: () => req('/api/mods'),
  categories: () => req('/api/categories'),
  dupes: () => req('/api/dupes'),
  install: () => req('/api/install'),
  backups: () => req('/api/backups'),
  backupDelete: (files, permanent) => req('/api/backup/delete',
    { method: 'POST', body: JSON.stringify({ files, permanent: !!permanent }) }),
  reveal: (f) => req('/api/open', { method: 'POST', body: JSON.stringify({ kind: 'reveal', f }) }),
  pending: () => req('/api/pending'),
  check: () => req('/api/check'),
  settings: () => req('/api/settings'),
  inspect: (f) => req('/api/inspect?f=' + encodeURIComponent(f)),
  job: () => req('/api/job'),

  startJob: (kind, params) => req('/api/job', { method: 'POST', body: JSON.stringify({ kind, params }) }),
  cancelJob: () => req('/api/job/cancel', { method: 'POST', body: '{}' }),
  renumberPreview: (body) => req('/api/renumber/preview', { method: 'POST', body: JSON.stringify(body) }),

  addMod: (body) => req('/api/mod/add', { method: 'POST', body: JSON.stringify(body) }),
  editMod: (body) => req('/api/mod/edit', { method: 'POST', body: JSON.stringify(body) }),
  batchEdit: (folders, fields) => req('/api/mod/batch-edit',
    { method: 'POST', body: JSON.stringify({ folders, fields }) }),
  deleteMod: (body) => req('/api/mod/delete', { method: 'POST', body: JSON.stringify(body) }),
  fixCover: (body) => req('/api/mod/fix-cover', { method: 'POST', body: JSON.stringify(body) }),
  // 按「作者 + 标签」从库里历史推荐 分类/类型（只建议，前端预选；主人一改就不覆盖）
  suggestCategory: (body) => req('/api/suggest/category', { method: 'POST', body: JSON.stringify(body || {}) }),

  // ---- 游戏内插件（Mod Bridge）：送到游戏里等确认 / 直接装 / 查待确认 ----
  bridgeStatus: () => req('/api/bridge'),
  bridgePropose: (folder) =>
    req('/api/bridge/propose', { method: 'POST', body: JSON.stringify({ folder }) }),
  bridgeInstall: (folder) =>
    req('/api/bridge/install', { method: 'POST', body: JSON.stringify({ folder }) }),
  bridgeRequests: () => req('/api/bridge/requests'),
  bridgeDecide: (requestId, approve) =>
    req('/api/bridge/decide', { method: 'POST', body: JSON.stringify({ requestId, approve }) }),
  bridgeAutopair: () => req('/api/bridge/autopair', { method: 'POST', body: '{}' }),

  // ---- 标签 ----
  tags: () => req('/api/tags'),
  setTags: (folder, tags) =>
    req('/api/mod/tags', { method: 'POST', body: JSON.stringify({ folder, tags }) }),
  addTags: (folders, tags) =>
    req('/api/mod/tags/add', { method: 'POST', body: JSON.stringify({ folders, tags }) }),
  removeTags: (folders, tags) =>
    req('/api/mod/tags/remove', { method: 'POST', body: JSON.stringify({ folders, tags }) }),

  // ---- 详情：内容描述 / 种族性别 / 文件清单 / 版本历史 ----
  setDesc: (folder, desc) =>
    req('/api/mod/desc', { method: 'POST', body: JSON.stringify({ folder, desc }) }),
  setSiteMeta: (body) => req('/api/mod/site-meta', { method: 'POST', body: JSON.stringify(body) }),
  files: (folder) => req('/api/mod/files?folder=' + encodeURIComponent(folder)),
  cloudCheck: () => req('/api/cloud/check'),
  cloudState: () => req('/api/cloud/state'),
  cloudFileUrl: (folder, rel) => '/api/cloud/file?folder=' + encodeURIComponent(folder)
    + '&rel=' + encodeURIComponent(rel),
  cloudArchive: (body) => req('/api/cloud/archive', { method: 'POST', body: JSON.stringify(body || {}) }),
  cloudRestore: (body) => req('/api/cloud/restore', { method: 'POST', body: JSON.stringify(body || {}) }),
  cloudVerify: (body) => req('/api/cloud/verify', { method: 'POST', body: JSON.stringify(body || {}) }),
  cloudDiscover: () => req('/api/cloud/discover'),          // 扫网盘（同步，几十秒）
  cloudIndexRestore: (write) => runJob('cloud_index_restore', { write: !!write }),  // 走任务：有真进度条
  cloudClaim: (items) => req('/api/cloud/claim',             // 把云端多的认领进索引库
    { method: 'POST', body: JSON.stringify({ items }) }),
  cloudReconcile: (folders, write) => req('/api/cloud/reconcile',
    { method: 'POST', body: JSON.stringify({ folders: folders || [], write: !!write }) }),
  // 检查报告里每条问题的处置（{kind, folder} 单条 / {kind, all:true} 这一类全做）
  checkFix: (kind, opts) => req('/api/check/fix',
    { method: 'POST', body: JSON.stringify({ kind, ...(opts || {}) }) }),
  // 索引体检 / 修复（「重排序号后一个 Mod 变两条」那类历史遗留）
  indexHealth: () => req('/api/index/health'),
  indexRepair: (write, alignCloud) => req('/api/index/repair',
    { method: 'POST', body: JSON.stringify({ write: !!write, align_cloud: !!alignCloud }) }),
  modFileUrl: (folder, name) => '/api/mod/download?folder=' + encodeURIComponent(folder)
    + '&name=' + encodeURIComponent(name),
  history: (folder) => req('/api/mod/history?folder=' + encodeURIComponent(folder)),

  // ---- 检查更新 / 更新 Mod ----
  replaceMod: (body) => req('/api/mod/replace', { method: 'POST', body: JSON.stringify(body) }),
  // 浏览器上传新文件替换：走 FormData，别手动设 Content-Type（要让浏览器自己带 boundary）
  // 上传可能很久（几十 MB 到几百 MB）→ 也要进全局加载条
  replaceModUpload: async (form) => {
    beginBusy('上传替换载荷')
    try {
      const r = await fetch('/api/mod/replace', { method: 'POST', body: form })
      const j = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(j.error || 'HTTP ' + r.status)
      return j
    } finally {
      endBusy()
    }
  },

  // ---- 影响/替换（这条 Mod 替换游戏里的哪些装备/部位） ----
  affects: () => req('/api/affects'),
  setAffects: (folder, affects) =>
    req('/api/mod/affects', { method: 'POST', body: JSON.stringify({ folder, affects }) }),
  category: (body) => req('/api/category', { method: 'POST', body: JSON.stringify(body) }),
  saveSettings: (body) => req('/api/settings', { method: 'POST', body: JSON.stringify(body) }),
  open: (kind, f) => req('/api/open', { method: 'POST', body: JSON.stringify({ kind, f }) }),
  quit: () => req('/api/quit', { method: 'POST', body: '{}' }),

  browser: () => req('/api/browser'),
  fetchParse: (body) => req('/api/fetch/parse', { method: 'POST', body: JSON.stringify(body) }),
  inboxPage: () => req('/api/inbox/page'),
  browserOpen: (url) => req('/api/browser/open', { method: 'POST', body: JSON.stringify({ url }) }),
  browserClose: () => req('/api/browser/close', { method: 'POST', body: '{}' }),
  browserCapture: () => req('/api/browser/capture', { method: 'POST', body: '{}' }),
  // 把它改成「用我自己的浏览器」：先关掉它、再带调试端口启动（会关掉正在用的浏览器）
  browserTakeover: () => req('/api/browser/takeover', { method: 'POST', body: '{}' }),
  grabCover: (folder) => req('/api/browser/grab-cover', { method: 'POST', body: JSON.stringify({ folder }) }),
  browserLoginState: () => req('/api/browser/login-state'),
  browserLoginDiag: () => req('/api/browser/login-diag'),   // 同步前的体检（无副作用）
  browserSyncLogin: (closeUser) => req('/api/browser/sync-login',
    { method: 'POST', body: JSON.stringify({ close_user: !!closeUser }) }),
  images: (f) => req('/api/images?f=' + encodeURIComponent(f)),
  imgUrl: (p, w = 200) => `/api/img?p=${encodeURIComponent(p)}&w=${w}`,
  rawImgUrl: (p) => `/api/rawimg?p=${encodeURIComponent(p)}`,
  addImage: (body) => req('/api/mod/add-image', { method: 'POST', body: JSON.stringify(body) }),
  delImage: (folder, path) => req('/api/mod/delete-image',
    { method: 'POST', body: JSON.stringify({ folder, path }) }),
  setPreview: (folder, path) =>
    req('/api/mod/set-preview', { method: 'POST', body: JSON.stringify({ folder, path }) }),

  thumb: (folder, w = 900, v = '') =>
    `/api/thumb?f=${encodeURIComponent(folder)}&w=${w}&v=${v || ''}`,
  raw: (folder) => `/api/raw?f=${encodeURIComponent(folder)}`,

  // ---- 运行日志 ----
  logs: () => req('/api/logs'),
  log: (opts = {}) => {
    const p = new URLSearchParams()
    if (opts.file) p.set('file', opts.file)
    p.set('n', String(opts.n || 300))
    if (opts.q) p.set('q', opts.q)
    return req('/api/log?' + p.toString())
  },
}

export const JOB_TITLES = {
  scan: '扫描目录',
  export: '生成 Excel',
  run: '扫描并生成 Excel',
  backup: '打包备份',
  restore: '导入备份',
  import: '导入下载',
  renumber: '重排序号',
  download: '从页面下载',
  watch: '监视下载',
  fetch: '解析并下载入库',
  update_check: '检查更新',
  mod_update: '更新 Mod（覆盖下载）',
  cloud_index_sync: '同步索引到网盘',
  cloud_index_restore: '从云端索引恢复',
  cloud_discover: '扫描网盘新内容',
  cloud_claim: '认领到库',
  // ★ 补齐（以前缺这几个 → 进度条上直接显示英文 kind，如 cloud_archive）。
  //   真正的来源是后端 job.title（Job.snap 里给），这里只是老后端/兜底用。
  cover_inject: '封面插包',
  selfdownload: '在自己浏览器里下载 → 自动入库',
  importfile: '入库（浏览器下好的文件）',
  cloud_archive: '归档到云盘',
  cloud_restore: '从云盘取回',
  cloud_verify: '校验云端文件',
  cloud_reconcile: '与网盘对账（重建归档状态）',
}

// ---- 更新能力的共享判据（原来只写在 ModsView 里，待办页也要用 → 提到这里做唯一来源）----

// 来源判据：XMA = xivmodarchive.com，Heliosphere = heliosphere.app
export function isHelio(m) {
  return !!(m && /heliosphere\.app/i.test(String(m.addr || '')))
}

// 能自动更新的：有新版 + 填了站点地址（两家都能自动下 ——
// heliosphere 由管理器自己读 GraphQL 清单 + 打包成 .pmp，见 manager/heliosphere.py）
export function canAutoUpdate(m) {
  return !!m && !!m.update_avail && !!(m.addr || '').trim()
}

// 「导入后自动装进游戏」的结果尾巴（四个入库入口共用）
function aiNote(r) {
  const a = r && r.auto_install
  if (!a) return ''
  if (a.skipped) return ` ｜ 没自动装（${a.skipped}）`
  if (a.error) return ` ｜ 自动装失败（看日志）`
  if (!a.done) return ''
  const bad = (a.items || []).filter((x) => !x.ok)
  return ` ｜ 已推给游戏 ${a.ok || 0}/${a.done} 条` +
    (a.mode === 'direct' ? '（直接装）' : '（游戏内待确认）') +
    (bad.length ? `，${bad.length} 条没推成功（看日志）` : '')
}

// 「导入后自动归档」的结果尾巴：四个入库入口（导入/解析下载/自己浏览器下/拓展推送）共用
function aaNote(r) {
  const a = r && r.auto_archive
  if (!a) return ''
  if (a.skipped) return ` ｜ 没自动归档（${a.skipped}）`
  if (a.error) return ` ｜ 自动归档失败（看日志）`
  if (!a.done) return ''
  const mb = Math.round((a.bytes || 0) / 1048576)
  return ` ｜ 已自动归档 ${a.ok || 0}/${a.done} 条（载荷 ${mb} MB 上云` +
    (a.deleted ? `，本地删了 ${a.deleted} 个进回收站` : '') + '）'
}

export function jobResultText(s) {
  const r = s.result || {}
  if (s.state === 'cancelled') return '已取消'
  if (s.state === 'error') return '出错：' + (s.error || '')
  switch (s.kind) {
    case 'update_check': {
      const n = (r.has_update || []).length
      const un = (r.unknown || []).length
      const sk = (r.skipped || []).length
      return `检查更新：共 ${r.checked || 0} 条（只查 XMA / heliosphere）｜ 有新版 ${n} 条 ｜ 已是最新 ${r.up_to_date || 0} 条` +
        (un ? ` ｜ ${un} 条读不到（可能被站点挡了）` : '') +
        (sk ? ` ｜ 跳过 ${sk} 条（来源不是 XMA / heliosphere）` : '') +
        (n ? '（表格里带「有新版」标记，勾上点「更新选中」即可）' : '')
    }
    case 'cloud_reconcile': {
      const f = (r.found || []).length
      const mi = (r.missing || []).length
      const lo = (r.local_only || []).length
      const cov = r.total_covers ?? (r.found || []).reduce((s, x) => s + (x.covers || 0), 0)
      return `${r.write ? '对账完成' : '对账预览（没改任何东西）'}：共 ${r.checked || 0} 条 ｜ ` +
        `云端有载荷 ${f} 条（${r.total_files || 0} 个文件 / ${Math.round((r.total_size || 0) / 1048576)} MB）` +
        (cov ? ` ｜ 封面 ${cov} 张` : '') +
        (mi ? ` ｜ 云端找不到 ${mi} 条` : '') + (lo ? ` ｜ 本地有云端没有 ${lo} 条` : '')
    }
    case 'cloud_index_sync': {
      const mb = Math.round((r.meta || 0))
      return `索引已同步：上传 ${r.meta || 0} 条` +
        (r.skipped ? `、跳过 ${r.skipped} 条（没变化）` : '') +
        ` ｜ 云端索引 ${r.index_cloud ? '已写' : '**失败**'}` +
        ((r.failed_n || 0) ? ` ｜ ${r.failed_n} 条没传上去（看日志）` : '') +
        `\n本地副本：${r.local || ''}`
    }
    case 'cloud_archive': {
      const items = r.items || []
      const cov = r.covers ?? items.reduce((s, x) => s + (x.covers || 0), 0)
      const cfail = items.reduce((s, x) => s + ((x.covers_failed || []).length), 0)
      const mb = Math.round((r.bytes || 0) / 1048576)
      return `归档完成：${r.ok || 0}/${r.done || 0} 条 ｜ 载荷 ${mb} MB ｜ 封面 ${cov} 张已上云（换机/新电脑靠它出图）` +
        (r.deleted ? ` ｜ 删本地 ${r.deleted} 个` : '') +
        (cfail ? ` ｜ ${cfail} 张封面没传上去（看日志）` : '')
    }
    case 'mod_update': {
      const ok = (r.ok || []).length
      const bad = (r.failed || []).length
      const why = (r.failed || []).slice(0, 2).map((x) => String(x).split('：')[0]).join('、')
      return `更新完成：成功 ${ok} 条` +
        (bad ? `，失败 ${bad} 条${why ? `（${why}${bad > 2 ? '…' : ''}）` : '（看日志）'}` : '')
    }
    case 'scan':
      return `扫描完成：${r.mods} 个 Mod` + (r.pruned ? `（清理失效 ${r.pruned} 条）` : '')
    case 'export':
      return `Excel 已生成：${r.sheets} 个工作表 / ${r.mods} 条 / ${r.images} 张预览图`
    case 'run':
      return `完成：${r.mods} 条，Excel ${r.sheets} 个工作表 / ${r.images} 张图`
    case 'backup':
      return `备份完成：${r.human || ''}（${r.files} 个文件）`
    case 'restore':
      return `恢复完成：新增 ${r.mods_new ?? 0}，跳过 ${r.mods_skipped ?? 0}，` +
        `覆盖 ${r.mods_overwritten ?? 0}，另存 ${r.mods_renamed ?? 0}`
    case 'import':
      return `导入完成：成功 ${(r.ok || []).length} 个` +
        ((r.failed || []).length ? `，失败 ${r.failed.length} 个` : '') + aiNote(r) + aaNote(r)
    case 'renumber':
      return `序号重排完成：改了 ${r.changed ?? 0} 个`
    case 'download':
      return `下载完成：${r.name}（${r.human}）→ 暂存目录`
    case 'watch':
      return `监视结束：搬走 ${(r.moved || []).length} 个文件`
    case 'fetch':
      return `已入库：${r.mod}（${r.human}）${r.cover ? '，封面已抓' : ''}` + aiNote(r) + aaNote(r)
    case 'importfile':
    case 'selfdownload':
      return (r.mod ? `已入库：${r.mod}` : `已放到待导入：${r.file || ''}`) + aiNote(r) + aaNote(r)
    default:
      return '完成'
  }
}
