// 统一的接口调用：失败时抛出后端返回的中文错误
async function req(path, opts = {}) {
  const r = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  const ct = r.headers.get('content-type') || ''
  const body = ct.includes('application/json') ? await r.json().catch(() => ({})) : await r.text()
  if (!r.ok) throw new Error((body && body.error) || 'HTTP ' + r.status)
  return body
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
  bridgeCoverCheck: (folder) => req('/api/bridge/cover-check',
    { method: 'POST', body: JSON.stringify({ folder }) }),
  bridgeFixCover: (folder) =>
    req('/api/bridge/fix-cover', { method: 'POST', body: JSON.stringify({ folder }) }),
  bridgeSyncCovers: (dryRun) =>
    req('/api/bridge/sync-covers', { method: 'POST', body: JSON.stringify({ dryRun: !!dryRun }) }),

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
  cloudReconcile: (folders, write) => req('/api/cloud/reconcile',
    { method: 'POST', body: JSON.stringify({ folders: folders || [], write: !!write }) }),
  modFileUrl: (folder, name) => '/api/mod/download?folder=' + encodeURIComponent(folder)
    + '&name=' + encodeURIComponent(name),
  history: (folder) => req('/api/mod/history?folder=' + encodeURIComponent(folder)),

  // ---- 检查更新 / 更新 Mod ----
  replaceMod: (body) => req('/api/mod/replace', { method: 'POST', body: JSON.stringify(body) }),
  // 浏览器上传新文件替换：走 FormData，别手动设 Content-Type（要让浏览器自己带 boundary）
  replaceModUpload: async (form) => {
    const r = await fetch('/api/mod/replace', { method: 'POST', body: form })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(j.error || 'HTTP ' + r.status)
    return j
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
  grabCover: (folder) => req('/api/browser/grab-cover', { method: 'POST', body: JSON.stringify({ folder }) }),
  browserLoginState: () => req('/api/browser/login-state'),
  browserSyncLogin: () => req('/api/browser/sync-login', { method: 'POST', body: '{}' }),
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
      return `${r.write ? '对账完成' : '对账预览（没改任何东西）'}：共 ${r.checked || 0} 条 ｜ ` +
        `云端有载荷 ${f} 条（${r.total_files || 0} 个文件 / ${Math.round((r.total_size || 0) / 1048576)} MB）` +
        (mi ? ` ｜ 云端找不到 ${mi} 条` : '') + (lo ? ` ｜ 本地有云端没有 ${lo} 条` : '')
    }
    case 'mod_update': {
      const ok = (r.ok || []).length
      const bad = (r.failed || []).length
      return `更新完成：成功 ${ok} 条` + (bad ? `，失败 ${bad} 条（看日志）` : '')
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
        ((r.failed || []).length ? `，失败 ${r.failed.length} 个` : '')
    case 'renumber':
      return `序号重排完成：改了 ${r.changed ?? 0} 个`
    case 'download':
      return `下载完成：${r.name}（${r.human}）→ 暂存目录`
    case 'watch':
      return `监视结束：搬走 ${(r.moved || []).length} 个文件`
    case 'fetch':
      return `已入库：${r.mod}（${r.human}）${r.cover ? '，封面已抓' : ''}`
    default:
      return '完成'
  }
}
