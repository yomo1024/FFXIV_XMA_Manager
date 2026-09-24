<script setup>
import { ref, computed, h, inject, onMounted, onUnmounted, nextTick, watch } from 'vue'

import {
  NButton, NInput, NSelect, NDataTable, NTag, NCard, NDescriptions, NDescriptionsItem,
  NImage, NModal, NForm, NFormItem, NInputNumber, NSwitch, NRadioGroup, NRadioButton,
  NSpace, NAlert, NEmpty, NTooltip, NDivider, NButtonGroup, NDynamicTags,
  NCheckboxGroup, NCheckbox, NTabs, NTabPane, NSpin, NProgress, useMessage, useDialog,
} from 'naive-ui'
import { api } from '../api'

const props = defineProps({ mods: { type: Array, default: () => [] } })
const emit = defineEmits(['changed'])
const { state, startJob, bus } = inject('mm')
const msg = useMessage()
const dialog = useDialog()

const cur = ref(null)
// 详情宽度三档：narrow=右栏窄栏(400px) / half=半屏(列表与详情各一半，展开的默认档) / full=全屏
const detmode = ref('narrow')
function setDetmode(m) {
  detmode.value = m
}
function detBack() {
  detmode.value = detmode.value === 'full' ? 'half' : 'narrow'
}

// ---- 详情右下的「描述 / 文件 / 历史」页签（对应 XMA 的 Info / Files / History）----
const dtabs = ref('desc')
const filesMap = ref({})          // folder -> {ok, items, count, total, error}
const histMap = ref({})           // folder -> {ok, items, error}
const tabBusy = ref('')
const descEdit = ref(false)
const descText = ref('')

function humanSize(n) {
  const v = Number(n || 0)
  if (v >= 1048576) return (v / 1048576).toFixed(2) + ' MB'
  if (v >= 1024) return (v / 1024).toFixed(0) + ' KB'
  return v + ' B'
}

async function loadFiles(folder) {
  if (!folder || filesMap.value[folder]) return
  tabBusy.value = 'files'
  try {
    const r = await api.files(folder)
    filesMap.value = { ...filesMap.value, [folder]: r }
  } catch (e) {
    filesMap.value = { ...filesMap.value, [folder]: { ok: false, error: e.message } }
  } finally {
    tabBusy.value = ''
  }
}

async function loadHistory(folder) {
  if (!folder || histMap.value[folder]) return
  tabBusy.value = 'hist'
  try {
    const r = await api.history(folder)
    histMap.value = { ...histMap.value, [folder]: r }
  } catch (e) {
    histMap.value = { ...histMap.value, [folder]: { ok: false, error: e.message } }
  } finally {
    tabBusy.value = ''
  }
}

function ensureTab() {
  const f = cur.value && cur.value.folder
  if (!f) return
  if (dtabs.value === 'files') loadFiles(f)
  else if (dtabs.value === 'hist') loadHistory(f)
}

watch([dtabs, () => (cur.value ? cur.value.folder : '')], ensureTab, { immediate: true })

function openDescEdit() {
  if (!cur.value) return
  descText.value = cur.value.desc || ''
  descEdit.value = true
}

async function saveDesc() {
  if (!cur.value) return
  try {
    const r = await api.setDesc(cur.value.folder, descText.value)
    cur.value.desc = r.desc
    descEdit.value = false
    msg.success(r.desc ? '内容描述已保存' : '已清空内容描述')
    emit('changed')
  } catch (e) {
    msg.error('保存内容描述失败：' + e.message)
  }
}

/** 种族 / 性别：手工改（站点读完也会自动带过来） */
async function saveSiteMeta(kind, list) {
  if (!cur.value) return
  const txt = (list || []).map((x) => String(x).trim()).filter(Boolean).join(', ')
  if (txt === String(cur.value[kind] || '').trim()) return
  try {
    const body = { folder: cur.value.folder }
    body[kind] = txt
    const r = await api.setSiteMeta(body)
    cur.value[kind] = r[kind] || ''
    msg.success((kind === 'races' ? '种族' : '性别') + '：' + (r[kind] || '（空）'))
    emit('changed')
  } catch (e) {
    msg.error('保存失败：' + e.message)
  }
}
const q = ref('')
const cat = ref('')
const zone = ref('')
const sub = ref('')
const cats = ref([])
const pending = ref([])
const busy = ref(false)

// ------------------------------------------------------------------ 表单
const form = ref(blank())
const showForm = ref(false)
const mode = ref('edit')

function blank() {
  return { src: '', folder: '', category: '', zone: 'SFW', subcat: '', seq: null,
           author: '', name: '', addr: '', affects: '', move: true }
}

const catOptions = computed(() =>
  (cats.value || []).map((c) => ({ label: `${c.name}（${c.count}）`, value: c.name })),
)
const subOptions = computed(() => {
  const c = (cats.value || []).find((x) => x.name === form.value.category)
  const names = new Set((c?.subcats || []).map((s) => s.name))
  ;(c?.disk_subcats || []).forEach((n) => names.add(n))
  return [...names].map((n) => ({ label: n, value: n }))
})
const zoneOptions = [
  { label: 'SFW', value: 'SFW' },
  { label: 'NSFW', value: 'NSFW' },
]
const pendingOptions = computed(() =>
  (pending.value || []).map((p) => ({
    label: `${p.file}（${p.where} · ${p.size_h}）`, value: p.src,
  })),
)

async function loadMeta() {
  try {
    cats.value = (await api.categories()).cats
    pending.value = (await api.pending()).items
  } catch (e) {
    msg.error(e.message)
  }
}
checkBridge()
loadTags()
loadAffects()
bus.refresh = loadMeta
onMounted(() => {
  // ?q=xxx 可以直接带搜索词打开（方便收藏特定 Mod 的筛选视图）
  const k = new URLSearchParams(location.search).get('q')
  if (k) q.value = k
  loadMeta()
})
// 从「下载工作台」带过来的地址 → 打开添加对话框并预填
watch(
  () => bus.prefillAdd,
  (v) => {
    if (!v) return
    bus.prefillAdd = null
    openAdd()
    form.value.addr = v.addr || ''
    form.value.name = v.name || ''
    form.value.author = v.author || ''
    form.value.affects = v.affects || ''
  },
)

const pickOnce = ref(null)

// 这个 Mod 的全部图片（大图下面那条缩略图）
const shots = ref([])
const shotPath = ref('')
const shotsLoading = ref(false)
const shotsFor = ref('')
// 键盘焦点：'table'（列表）/ 'strip'（缩略图条）—— 决定 Delete / Enter 作用于谁
const focusArea = ref('table')
const fixing = ref(false)          // 补预览图进行中
const installing = ref(false)      // 送到游戏进行中
const bridgeOk = ref(null)         // 游戏内插件是否连得上：null 未知 / true / false
const bridgeVer = ref('')           // 插件的版本号（版本监控用）
const bridgeVerOld = ref(false)     // 插件版本低于管理器要求

// ---------------- 高级搜索 ----------------
const advOpen = ref(false)
// 高级搜索（照 XMA 那个表单来：几个填空 + 几个下拉，够用就好）
const fName = ref('')               // 名称包含
const fAuthor = ref('')             // 作者包含
const fAffectsText = ref('')        // 影响/替换 包含
const fTagsText = ref('')           // 标签 包含
const fCats = ref([])               // 分类（可多选）
const fInst = ref('')               // '' / yes / no / unknown
const fImg = ref('')                // '' / yes / no
const fTagState = ref('')           // '' / has / none
const sortBy = ref('default')       // default / name / author / seq / updated / category
const sortDir = ref('asc')
const allTags = ref([])             // [{tag, count}]  ← 给批量条/编辑窗做候选用
const allAffects = ref([])          // [{affects, count}]
const advCount = computed(() =>
  (fName.value.trim() ? 1 : 0) + (fAuthor.value.trim() ? 1 : 0) + (fAffectsText.value.trim() ? 1 : 0) +
  (fTagsText.value.trim() ? 1 : 0) + (fCats.value.length ? 1 : 0) +
  (fInst.value ? 1 : 0) + (fImg.value ? 1 : 0) + (fTagState.value ? 1 : 0) +
  (sortBy.value !== 'default' ? 1 : 0))

const sortOptions = [
  { label: '默认（分类 + 序号）', value: 'default' },
  { label: '名称', value: 'name' }, { label: '作者', value: 'author' },
  { label: '序号', value: 'seq' }, { label: '更新时间', value: 'updated' },
  { label: '分类', value: 'category' },
]
const sortDirOptions = [{ label: '升序 ↑', value: 'asc' }, { label: '降序 ↓', value: 'desc' }]

async function loadTags() {
  try {
    const r = await api.tags()
    allTags.value = r.tags || []
  } catch (e) {
    console.warn('读标签失败', e)
  }
}

const tagOptions = computed(() => allTags.value.map((t) => ({ label: `${t.tag}（${t.count}）`, value: t.tag })))
const affectsOptions = computed(() =>
  allAffects.value.map((t) => ({ label: `${t.affects}（${t.count}）`, value: t.affects })))

async function loadAffects() {
  try {
    const r = await api.affects()
    allAffects.value = r.items || []
  } catch (e) {
    console.warn('读影响/替换取值失败', e)
  }
}

/** 「影响/替换」在库里是一整串（可能含多项），按逗号拆成一个个，方便像标签那样显示/编辑 */
function splitList(text) {
  return String(text || '')
    .split(/[,，、；;]+/)
    .map((x) => x.trim())
    .filter(Boolean)
}
/** 详情面板改「影响/替换」：拆开的数组 → 存回逗号分隔的字符串 */
async function saveAffectsList(list) {
  if (!cur.value) return
  const want = (list || []).map((x) => String(x).trim()).filter(Boolean)
  const txt = want.join(', ')
  if (txt === String(cur.value.affects || '').trim()) return
  try {
    const r = await api.setAffects(cur.value.folder, txt)
    cur.value.affects = r.affects
    await loadAffects()
    msg.success(r.affects ? `已保存影响/替换：${r.affects}` : '已清空影响/替换')
    emit('changed')
  } catch (e) {
    msg.error('保存影响/替换失败：' + e.message)
  }
}

const instOptions = [
  { label: '已安装', value: 'yes' }, { label: '未安装', value: 'no' }, { label: '未知', value: 'unknown' },
]
const imgOptions = [{ label: '有预览图', value: 'yes' }, { label: '没有预览图', value: 'no' }]
const tagStateOptions = [{ label: '有标签', value: 'has' }, { label: '没有标签', value: 'none' }]
function clearAdv() {
  fName.value = ''; fAuthor.value = ''; fAffectsText.value = ''; fTagsText.value = ''
  fCats.value = []; fInst.value = ''; fImg.value = ''; fTagState.value = ''
  sortBy.value = 'default'; sortDir.value = 'asc'
  q.value = ''; cat.value = ''; sub.value = ''; zone.value = ''; onlyUpd.value = false
}

/** 顶部搜索框：所有字段一起找（不再让用户选「关键字范围」，太绕） */
function fieldHit(m, needle) {
  const parts = [m.name, m.author, m.addr, m.rel || m.folder, m.category, m.subcat, m.affects,
                 (m.tags || []).join(' ')]
  return parts.some((v) => String(v || '').toLowerCase().includes(needle))
}

async function saveTags(list) {   // 单条：整条覆盖
  if (!cur.value) return
  const want = (list || []).map((s) => String(s).trim()).filter(Boolean)
  try {
    await api.setTags(cur.value.folder, want)
    cur.value.tags = want
    await loadTags()
    msg.success(want.length ? `已保存标签：${want.join('、')}` : '已清空标签')
    emit('changed')
  } catch (e) {
    msg.error('保存标签失败：' + e.message)
  }
}

// ---------------- 检查更新 / 更新 Mod ----------------
const onlyUpd = ref(false)              // 只看「有新版」
const updateChecking = ref(false)
const updating = ref(false)
const replaceMode = ref('same_name')
const updCount = computed(() => (props.mods || []).filter((m) => m.update_avail).length)
const updFolders = computed(() =>
  (checked.value.length ? checked.value : [])
    .filter((f) => { const m = (props.mods || []).find((x) => x.folder === f); return m && m.update_avail }))

async function checkUpdates() {
  const folders = checked.value.length ? [...checked.value] : []
  updateChecking.value = true
  try {
    await startJob('update_check', { folders })
    msg.info(folders.length ? `开始检查选中的 ${folders.length} 条…` : '开始检查全部（有站点地址的）…')
    setTimeout(() => { updateChecking.value = false }, 4000)
  } catch (e) {
    updateChecking.value = false
    msg.error('启动检查失败：' + e.message)
  }
}

// ---------------- 与网盘对账：以云端实况为准重建归档状态 ----------------
function askReconcile(folders) {
  const list = (folders && folders.length) ? folders : cloudTargets()
  dialog.warning({
    title: '与网盘对账',
    content: '拿**云端实况**核对每条 Mod 到底归档没有，并重建「已归档」状态与云端载荷清单。\n'
      + '用在：换电脑后 / 索引库丢了云状态 / 你在网盘里手工整理过。\n'
      + (list.length ? `只对选中的 ${list.length} 条对账。` : '没勾选 → 对全部 Mod 对账。')
      + '\n不下载、不删除任何文件，只改索引库里的记录。',
    positiveText: '对账并修正（写回索引）',
    negativeText: '只看不改（预览）',
    onPositiveClick: () => {
      startJob('cloud_reconcile', { folders: list, write: true })
      msg.info('开始对账并写回索引库；跑完列表会自动刷新，没变就 Ctrl+F5', { duration: 12000 })
    },
    onNegativeClick: () => {
      startJob('cloud_reconcile', { folders: list, write: false })
      msg.info('只看不改：跑完会告诉你云端有多少条、哪些对不上，不会动索引库')
    },
  })
}

// ---------------- 云端文件下载（带进度条）----------------
const dl = ref(null)               // {name, done, total, pct, speed, state, error}
let dlCtl = null                   // AbortController，取消用

function cancelDownload() {
  try { if (dlCtl) dlCtl.abort() } catch (e) { /* 忽略 */ }
}

/** 点云端文件 → 流式下载到本地，界面上给进度/速度；能「另存为」就直接流式落盘 */
async function downloadCloud(folder, rel) {
  const url = api.cloudFileUrl(folder, rel)
  const name = String(rel).split('/').pop() || 'download.bin'
  let handle = null
  if (window.showSaveFilePicker) {
    try {
      handle = await window.showSaveFilePicker({ suggestedName: name })
    } catch (e) {
      if (e && e.name === 'AbortError') return    // 用户自己取消了「另存为」
      handle = null                                // 其它情况退回内存 Blob 下载
    }
  }
  dlCtl = new AbortController()
  dl.value = { name, done: 0, total: 0, pct: 0, speed: 0, state: 'running', error: '' }
  const t0 = Date.now()
  const tick = (n, total) => {
    const d = dl.value
    if (!d) return
    d.done = n
    d.total = total
    d.pct = total ? Math.min(100, Math.round((n * 100) / total)) : 0
    d.speed = n / Math.max(0.3, (Date.now() - t0) / 1000)
  }
  try {
    const resp = await fetch(url, { signal: dlCtl.signal })
    if (!resp.ok) throw new Error('HTTP ' + resp.status)
    const total = Number(resp.headers.get('Content-Length') || 0)
    const reader = resp.body.getReader()
    if (handle) {
      const w = await handle.createWritable()
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        await w.write(value)
        tick((dl.value ? dl.value.done : 0) + value.length, total)
      }
      await w.close()
    } else {
      const chunks = []
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        chunks.push(value)
        tick((dl.value ? dl.value.done : 0) + value.length, total)
      }
      const blob = new Blob(chunks)
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = name
      a.click()
      setTimeout(() => URL.revokeObjectURL(a.href), 60000)
    }
    if (dl.value) dl.value.state = 'done'
    msg.success('已下载：' + name)
  } catch (e) {
    if (dl.value) {
      dl.value.state = (e && e.name === 'AbortError') ? 'cancelled' : 'error'
      dl.value.error = (e && e.message) || String(e)
    }
  } finally {
    dlCtl = null
  }
}

// ---------------- 云盘归档 / 取回 ----------------
const shareUrl = ref('')            // 设置里可选填的「云端分享链接」（文件页签/详情里跳网盘用）
onMounted(async () => {
  try {
    const cfg = await api.settings()
    shareUrl.value = String(cfg.cloud_share_url || '')
  } catch (e) { /* 没填就为空，不影响 */ }
})
const cloudBusy = ref(false)
function cloudTargets() {
  return checked.value.length ? [...checked.value] : (cur.value ? [cur.value.folder] : [])
}
function humanMB(n) {
  const v = Number(n || 0)
  return v >= 1048576 ? (v / 1048576).toFixed(1) + ' MB' : (v / 1024).toFixed(0) + ' KB'
}

/** 归档：上传到夸克 → 逐文件校验 → 通过才删本地载荷（所以要先确认一次） */
async function archiveCloud(folders) {
  const list = (folders && folders.length) ? folders : cloudTargets()
  if (!list.length) return msg.warning('先勾选（或点一条）要归档的 Mod')
  const rows = props.mods.filter((m) => list.includes(m.folder))
  const total = rows.reduce((s2, m) => s2 + (m.payload_size || 0), 0)
  const already = rows.filter((m) => (m.archived_files || 0) && !(m.payload_size || 0)).length
  dialog.warning({
    title: '归档到云盘',
    content: `把 ${list.length} 条 Mod 的载荷（约 ${humanMB(total)}）上传到夸克；`
      + `上传并逐个校验通过后，会删掉本地载荷（进回收站，可还原）。`
      + `预览图会跟载荷**一起上云**（换机/新电脑才有图可推给游戏，本地也各留一份）；地址.txt 和元信息只留本地。`
      + (already ? `\n其中 ${already} 条已经在云端了，会自动走秒传、不用重传。` : ''),
    positiveText: '开始归档',
    negativeText: '取消',
    onPositiveClick: async () => {
      cloudBusy.value = true
      try {
        await startJob('cloud_archive', { folders: list, delete_local: true })
        msg.info('已开始归档，进度看上面的任务条')
      } catch (e) {
        msg.error('启动归档失败：' + e.message)
      } finally {
        cloudBusy.value = false
      }
    },
  })
}
/** 校验：把云端那份下载回来逐文件比 sha1（只下载体检，不动本地 Mod 库） */
async function verifyCloud(folders) {
  const list = (folders && folders.length) ? folders : cloudTargets()
  const rows = props.mods.filter((m) => list.includes(m.folder) && (m.archived_files || 0))
  if (!rows.length) return msg.warning('选中的里面没有「已归档」的 Mod')
  const total = rows.reduce((s2, m) => s2 + (m.cloud_size || 0), 0)
  dialog.info({
    title: '校验云端文件',
    content: `会把云端这 ${rows.length} 条（约 ${humanMB(total)}）下载回来逐个比对 sha1 ——`
      + `只做体检，不动本地的东西，但**要花时间和流量**。`,
    positiveText: '开始校验',
    negativeText: '取消',
    onPositiveClick: async () => {
      cloudBusy.value = true
      try {
        await startJob('cloud_verify', { folders: rows.map((m) => m.folder) })
        msg.info('已开始校验，进度看上面的任务条')
      } catch (e) {
        msg.error('启动校验失败：' + e.message)
      } finally {
        cloudBusy.value = false
      }
    },
  })
}

/** 取回：把云端载荷下载回本地（逐文件校验大小 + sha1） */
async function restoreCloud(folders) {
  const list = (folders && folders.length) ? folders : cloudTargets()
  if (!list.length) return msg.warning('先勾选（或点一条）要取回的 Mod')
  const rows = props.mods.filter((m) => list.includes(m.folder) && (m.archived_files || 0))
  if (!rows.length) return msg.warning('选中的里面没有「已归档」的 Mod')
  cloudBusy.value = true
  try {
    await startJob('cloud_restore', { folders: rows.map((m) => m.folder) })
    msg.info(`开始从云盘取回 ${rows.length} 条…`)
  } catch (e) {
    msg.error('启动取回失败：' + e.message)
  } finally {
    cloudBusy.value = false
  }
}

// heliosphere 的下载是页面上的按钮（接口没公开）→ 打开页面让他自己点，再上传替换
function isHelio(m) {
  return !!(m && /heliosphere\.app/i.test(String(m.addr || '')))
}
async function updateOne(m) {
  if (!m) return msg.warning('先在左边选一条 Mod')
  if (!isHelio(m)) return doUpdate([m.folder])
  try {
    await api.open('addr', m.folder)
    msg.info('已用你的浏览器打开 heliosphere 页面：点「Download as PMP」下好，' +
      '回来用「上传新文件替换」覆盖这条（它的下载按钮调的是站内接口，管理器拿不到直链）',
      { duration: 15000 })
  } catch (e) {
    msg.error(e.message)
  }
}

function doUpdate(folders) {
  const list = (folders && folders.length) ? folders : updFolders.value
  if (!list.length) return msg.warning('先勾选「有新版」的 Mod，或点某条详情里的「从站点更新」')
  const names = list.map((f) => ((props.mods || []).find((m) => m.folder === f) || {}).name || f)
  dialog.warning({
    title: '从站点下载最新版并覆盖',
    content: `将更新 ${list.length} 条：\n${names.slice(0, 6).map((n) => '· ' + n).join('\n')}` +
      (names.length > 6 ? `\n… 还有 ${names.length - 6} 条` : '') +
      '\n\n旧文件会移入回收站（能还原）；地址.txt、预览图、编号、标签、影响/替换 都保留。' +
      `\n替换方式：${replaceMode.value === 'all_payload' ? '清掉旧文件再放新的' : '只替换同名文件'}`,
    positiveText: '开始更新',
    negativeText: '取消',
    onPositiveClick: () => {
      updating.value = true
      startJob('mod_update', { folders: list, mode: replaceMode.value, export: true })
        .catch((e) => msg.error('启动更新失败：' + e.message))
        .finally(() => setTimeout(() => { updating.value = false }, 4000))
    },
  })
}

// 手动上传 / 指定新文件替换
const showReplace = ref(false)
const repReplacing = ref(false)
const repForm = ref({ folder: '', name: '', mode: 'same_name', src: '', file: null, upName: '' })
function openReplace() {
  const m = cur.value
  if (!m) return msg.warning('先在左边选一条 Mod')
  repForm.value = { folder: m.folder, name: m.name, mode: 'same_name', src: '', file: null, upName: '' }
  showReplace.value = true
}
function pickRepFile(e) {
  const f = e && e.target && e.target.files && e.target.files[0]
  repForm.value.file = f || null
  repForm.value.upName = f ? f.name : ''
}
async function submitReplace() {
  const f = repForm.value
  if (!f.file && !String(f.src || '').trim()) return msg.warning('选一个新文件（也可以填本地路径）')
  repReplacing.value = true
  try {
    let r
    if (f.file) {
      const fd = new FormData()
      fd.append('folder', f.folder); fd.append('mode', f.mode); fd.append('file', f.file)
      r = await api.replaceModUpload(fd)
    } else {
      r = await api.replaceMod({ folder: f.folder, src: String(f.src).trim(), mode: f.mode })
    }
    msg.success(`已替换：换掉 ${(r.removed || []).length} 个旧文件，放入 ${(r.added || []).join('、')}` +
      ((r.kept || []).length ? `（保留 ${r.kept.length} 个）` : ''))
    showReplace.value = false
    emit('changed')
    await loadMeta()
  } catch (e) {
    msg.error('替换失败：' + e.message)
  } finally {
    repReplacing.value = false
  }
}

async function batchTag(add = true) {
  const folders = checked.value.length ? [...checked.value] : (cur.value ? [cur.value.folder] : [])
  const tags = batch.value.tags || []
  if (!folders.length) return msg.warning('先选几条 Mod')
  if (!tags.length) return msg.warning('先选或输入要处理的标签')
  try {
    const r = add ? await api.addTags(folders, tags) : await api.removeTags(folders, tags)
    const n = add ? r.added : r.removed
    msg.success(`${add ? '加' : '去'}标签完成：作用于 ${folders.length} 条 Mod，实际${add ? '新增' : '删除'} ${n} 条标签`)
    batch.value.tags = []
    await loadTags()
    emit('changed')
  } catch (e) {
    msg.error('批量标签失败：' + e.message)
  }
}
const inboxPage = ref(null)        // 你自己浏览器推来的页面信息
const inboxAt = ref(0)
const shotIdx = ref(0)

function selectShot(i) {
  if (!shots.value.length) return
  const n = Math.max(0, Math.min(shots.value.length - 1, i))
  shotIdx.value = n
  shotPath.value = shots.value[n].path
  focusArea.value = 'strip'
  const el = document.querySelectorAll('.shots .shot')[n]
  el && el.scrollIntoView({ block: 'nearest', inline: 'nearest' })
}

async function loadShots(folder) {
  if (!folder) {
    shots.value = []
    shotPath.value = ''
    return
  }
  shotsLoading.value = true
  try {
    const d = await api.images(folder)
    shots.value = d.images || []
    const cur0 = shots.value.find((x) => x.is_current)
    shotPath.value = cur0 ? cur0.path : (shots.value[0]?.path || '')
    shotIdx.value = Math.max(0, shots.value.findIndex((x) => x.path === shotPath.value))
  } catch (e) {
    shots.value = []
    shotPath.value = ''
  } finally {
    shotsLoading.value = false
  }
}

// ---------- 追加图片 ----------
const showAddImg = ref(false)
const imgUrl = ref('')
const adding = ref(false)
const fileEl = ref(null)

function pickFiles() {
  fileEl.value && fileEl.value.click()
}

async function onFiles(e) {
  const fs = [...(e.target.files || [])]
  e.target.value = ''
  if (!fs.length || !cur.value) return
  adding.value = true
  try {
    const files = []
    for (const f of fs) {
      const data = await new Promise((res, rej) => {
        const r = new FileReader()
        r.onload = () => res(String(r.result).split(',')[1] || '')
        r.onerror = rej
        r.readAsDataURL(f)
      })
      files.push({ name: f.name, data })
    }
    const r = await api.addImage({ folder: cur.value.folder, files })
    afterAdd(r)
  } catch (e2) {
    msg.error('添加失败：' + e2.message)
  } finally {
    adding.value = false
  }
}

async function addByUrl() {
  const u = imgUrl.value.trim()
  if (!u) return msg.warning('粘一个图片网址')
  if (!cur.value) return msg.warning('先在左边选一条 Mod')
  adding.value = true
  try {
    const r = await api.addImage({ folder: cur.value.folder, url: u })
    afterAdd(r)
    imgUrl.value = ''
  } catch (e) {
    msg.error('添加失败：' + e.message)
  } finally {
    adding.value = false
  }
}

async function addFromPage() {
  if (!cur.value) return msg.warning('先在左边选一条 Mod')
  adding.value = true
  try {
    const r = await api.addImage({ folder: cur.value.folder, page: true })
    afterAdd(r)
  } catch (e) {
    msg.error('抓取失败：' + e.message)
  } finally {
    adding.value = false
  }
}

function delImage(im) {
  if (!cur.value || !im) return
  const isCur = im.is_current
  dialog.warning({
    title: '删除图片',
    content: `要删掉「${im.name}」吗？会移入回收站（可以还原）。` +
      (isCur ? '\n这是当前预览图，删完会自动换一张（没有就变成没预览图）。' : ''),
    positiveText: '移入回收站',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        const r = await api.delImage(cur.value.folder, im.path)
        msg.success(`${r.name} ${r.how}`)
        await loadShots(cur.value.folder)
        emit('changed')
      } catch (e) {
        msg.error('删除失败：' + e.message, { duration: 12000 })
      }
    },
  })
}

function afterAdd(r) {
  const n = (r && r.ok) ? r.ok.length : 0
  const notes = (r && r.notes) || []
  if (notes.length) msg.info(notes.join('\n'), { duration: 12000 })
  if (n) {
    msg.success(`加了 ${n} 张图` + (r.failed?.length ? `，${r.failed.length} 张失败` : ''))
    if (r.failed?.length) console.warn('部分失败', r.failed)
    loadShots(cur.value.folder)
    emit('changed')
    showAddImg.value = false
  } else {
    msg.error('没加上：' + ((r && r.failed && r.failed[0]) || '没读到图片'))
  }
}

const inboxAge = computed(() => {
  if (!inboxPage.value || !inboxAt.value) return ''
  const s = Math.max(0, Math.round(Date.now() / 1000 - inboxAt.value))
  return s < 60 ? s + ' 秒前' : Math.round(s / 60) + ' 分钟前'
})

async function readInbox() {
  try {
    const r = await api.inboxPage()
    if (r && r.page) {
      inboxPage.value = r.page
      inboxAt.value = r.at || 0
      if (!r.page.imgs) r.page.imgs = []
      msg.info(`收到你浏览器推来的：${r.page.name || r.page.title || '(没读到名称)'}` +
               `（画廊 ${(r.page.imgs || []).length} 张，${inboxAge.value}）`)
    } else if (r) {
      inboxPage.value = null
      msg.warning('还没收到你浏览器推来的信息：先在 Mod 页面点一下书签小工具')
    }
    return r
  } catch (e) {
    msg.error('读推来的信息失败：' + e.message)
  }
}

async function addFromInbox() {
  if (!cur.value) return msg.warning('先在左边选一条 Mod')
  const r0 = await readInbox()
  if (!inboxPage.value) return
  adding.value = true
  try {
    const r = await api.addImage({ folder: cur.value.folder, use_inbox: true })
    afterAdd(r)
  } catch (e) {
    msg.error('添加失败：' + e.message, { duration: 12000 })
  } finally {
    adding.value = false
  }
}

async function useAsPreview(im) {
  if (!cur.value || !im) return
  busy.value = true
  try {
    const r = await api.setPreview(cur.value.folder, im.path)
    if (r && r.name) console.log('预览图已写入', r.saved)
    msg.success('已设为预览图：' + im.name)
    await loadShots(cur.value.folder)
    emit('changed')
  } catch (e) {
    msg.error('设为预览图失败：' + e.message, { duration: 12000 })
    console.warn('set-preview 失败', e)
  } finally {
    busy.value = false
  }
}
watch(showAddImg, (v) => {
  if (v) readInbox()
})

const wall = ref(new URLSearchParams(location.search).has('wall'))   // 表格 / 图片墙
const batch = ref({ category: '', zone: '', subcat: '', tags: [], affectsOn: false, affects: '' })
const searchEl = ref(null)

async function applyBatch() {
  if (!checked.value.length) return
  const f = {}
  if (batch.value.category) f.category = batch.value.category
  if (batch.value.zone) f.zone = batch.value.zone
  if (batch.value.subcat !== '') f.subcat = batch.value.subcat
  if (batch.value.affectsOn) f.affects = batch.value.affects || ''      // 开了开关才动它（空 = 清空）
  if (!Object.keys(f).length) return msg.warning('上面至少选一样要改的')
  busy.value = true
  try {
    const r = await api.batchEdit(checked.value, f)
    msg.success(`批量改了 ${r.ok.length} 个` + (r.failed.length ? `，失败 ${r.failed.length} 个` : ''))
    if (r.failed.length) console.warn(r.failed)
    checked.value = []
    batch.value = { category: '', zone: '', subcat: '', tags: [], affectsOn: false, affects: '' }
    emit('changed')
    await loadMeta()
  } catch (e) {
    msg.error(e.message)
  } finally {
    busy.value = false
  }
}

function moveSel(d) {
  const list = view.value
  if (!list.length) return
  const i = list.findIndex((m) => cur.value && m.folder === cur.value.folder)
  const n = Math.max(0, Math.min(list.length - 1, (i < 0 ? 0 : i) + d))
  cur.value = list[n]
}

function onKey(e) {
  const tag = (e.target?.tagName || '').toLowerCase()
  const typing = tag === 'input' || tag === 'textarea' || e.target?.isContentEditable
  if (e.ctrlKey && e.key.toLowerCase() === 'f') {
    e.preventDefault()
    searchEl.value?.focus()
    return
  }
  if (typing) {
    if (e.key === 'Escape') e.target.blur()
    return
  }
  const hasShots = shots.value.length > 0
  switch (e.key) {
    case 'ArrowDown':
      e.preventDefault(); focusArea.value = 'table'; moveSel(1); break
    case 'ArrowUp':
      e.preventDefault(); focusArea.value = 'table'; moveSel(-1); break
    case 'ArrowLeft':
      if (!hasShots) break
      e.preventDefault(); selectShot(shotIdx.value - 1); break
    case 'ArrowRight':
      if (!hasShots) break
      e.preventDefault(); selectShot(shotIdx.value + 1); break
    case 'Enter':
      e.preventDefault()
      if (focusArea.value === 'strip' && hasShots) useAsPreview(shots.value[shotIdx.value])
      else openEdit()
      break
    case 'Delete':
      e.preventDefault()
      if (focusArea.value === 'strip' && hasShots) delImage(shots.value[shotIdx.value])
      else doDelete()
      break
    case ' ':
      if (focusArea.value !== 'strip' || !hasShots) break
      e.preventDefault()
      useAsPreview(shots.value[shotIdx.value])
      break
    case 'Escape':
      if (detmode.value !== 'narrow') detBack()
      else if (focusArea.value === 'strip') focusArea.value = 'table'
      else q.value = ''
      break
  }
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
watch(
  () => props.mods,
  (list) => {
    if (cur.value) cur.value = list.find((m) => m.folder === cur.value.folder) || null
    if (pickOnce.value === null && list.length &&
        new URLSearchParams(location.search).has('pick')) {
      pickOnce.value = true
      cur.value = list[0]
    }
    if (cur.value?.folder !== shotsFor.value) {
      shotsFor.value = cur.value?.folder || ''
      loadShots(shotsFor.value)
    }
    if (!cur.value) {
      shotsFor.value = ''
      shots.value = []
      shotPath.value = ''
    }
  },
  { immediate: true },
)

// ------------------------------------------------------------------ 表格
const filtered = computed(() =>
  props.mods.filter((m) => {
    if (cat.value && m.category !== cat.value) return false
    if (zone.value && m.nsfw !== zone.value) return false
    if (sub.value && (m.subcat || '') !== sub.value) return false
    const k = q.value.trim().toLowerCase()
    if (k && !fieldHit(m, k)) return false
    // ---------- 高级搜索（就是几个填空/下拉，跟 XMA 那个表单一个思路）----------
    const has = (v, needle) => String(v || '').toLowerCase().includes(String(needle).toLowerCase())
    if (fName.value.trim() && !has(m.name, fName.value.trim())) return false
    if (fAuthor.value.trim() && !has(m.author, fAuthor.value.trim())) return false
    if (fAffectsText.value.trim() && !has(m.affects, fAffectsText.value.trim())) return false
    if (fTagsText.value.trim() &&
        !(m.tags || []).some((t) => has(t, fTagsText.value.trim()))) return false
    if (fCats.value.length && !fCats.value.includes(m.category)) return false
    if (onlyUpd.value && !m.update_avail) return false
    if (fTagState.value === 'has' && !(m.tags || []).length) return false
    if (fTagState.value === 'none' && (m.tags || []).length) return false
    if (fInst.value === 'yes' && m.installed !== true) return false
    if (fInst.value === 'no' && m.installed !== false) return false
    if (fInst.value === 'unknown' && m.installed !== null) return false
    if (fImg.value === 'yes' && !m.has_img) return false
    if (fImg.value === 'no' && m.has_img) return false
    return true
  }),
)
/** 排序（照 XMA 的 Sort by + 升/降序）：默认还是按分类+序号 */
const view = computed(() => {
  const list = [...filtered.value]
  const by = sortBy.value
  const dir = sortDir.value === 'desc' ? -1 : 1
  if (by === 'default') return list
  const val = (m) => {
    if (by === 'seq') return Number(m.seq) || 0
    if (by === 'updated') return String(m.site_latest || m.site_updated || '')
    if (by === 'author') return String(m.author || '').toLowerCase()
    if (by === 'category') return String(m.category || '').toLowerCase()
    return String(m.name || '').toLowerCase()      // name
  }
  return list.sort((a, b) => {
    const x = val(a), y = val(b)
    if (x < y) return -1 * dir
    if (x > y) return 1 * dir
    return 0
  })
})
const subFilterOptions = computed(() => {
  const s = new Set()
  props.mods.forEach((m) => {
    if ((!cat.value || m.category === cat.value) && m.subcat) s.add(m.subcat)
  })
  return [...s].map((x) => ({ label: x, value: x }))
})

const columns = computed(() => [
  {
    type: 'selection',
    width: 40,
  },
  {
    title: '', key: 'thumb', width: 78,
    render: (r) => r.has_img
      ? h('img', { class: 'cell-thumb', src: api.thumb(r.folder, 120, r.ih), loading: 'lazy' })
      : null,
  },
  { title: '分类', key: 'category', width: 76 },
  { title: '子分类', key: 'subcat', width: 104, resizable: true, render: (r) => r.subcat || '' },
  { title: '序号', key: 'seq', width: 84, align: 'center', sorter: (a, b) => a.seq - b.seq },
  { title: '作者', key: 'author', width: 176, minWidth: 140, ellipsis: { tooltip: true }, resizable: true },
  {
    title: '类型', key: 'nsfw', width: 84,
    render: (r) => h(NTag, { size: 'small', bordered: false, type: r.nsfw === 'NSFW' ? 'warning' : 'success' },
      { default: () => r.nsfw }),
  },
  {
    title: '更新时间', key: 'site_updated', width: 168, resizable: true,
    render: (r) => {
      // 优先显示「站点上最后更新时间」（检查更新就能填上）；老数据没查过就退回首行基线
      const v = String(r.site_latest || r.site_updated || '').trim()
      const kids = []
      if (r.update_avail) {
        kids.push(h(NTag, {
          size: 'tiny', bordered: false, type: 'warning',
          style: 'margin-right:4px;cursor:pointer',
          onClick: (e) => { e.stopPropagation(); onlyUpd.value = true },
        }, { default: () => '有新版' }))
      }
      kids.push(h('span', { style: v ? '' : 'opacity:.35' }, v ? v.slice(0, 10) : '—'))
      // 注意：naive-ui 的插槽要作为 h() 的**第三个参数**传；写成 props 会静默渲染成空（踩过）
      return h(NTooltip, null, {
        trigger: () => h('div', { style: 'display:flex;align-items:center;gap:2px' }, kids),
        default: () => [
          `站点上最后更新：${r.site_latest || r.site_updated || '未知'}`,
          r.site_version ? `站点版本：v${r.site_version}` : '',
          r.site_checked ? `上次检查：${r.site_checked}` : '',
          r.site_updated && r.site_latest && r.site_updated !== r.site_latest
            ? `本地这份下载于：${r.site_updated}` : '',
        ].filter(Boolean).join('｜'),
      })
    },
  },
  {
    title: 'Mod 名称', key: 'name', minWidth: 260, resizable: true,
    render: (r) => {
      const kids = []
      if (r.cloud_state === 'archived') {
        kids.push(h(NTag, { size: 'tiny', bordered: false, type: 'info',
                            style: 'margin-right:5px;flex:0 0 auto' }, { default: () => '云' }))
      } else if (r.cloud_state === 'missing') {
        kids.push(h(NTag, { size: 'tiny', bordered: false, type: 'error',
                            style: 'margin-right:5px;flex:0 0 auto' }, { default: () => '云端缺失' }))
      }
      kids.push(h('span', { class: 'cell-name', title: r.name }, r.name))
      return h('div', { style: 'display:flex;align-items:center;min-width:0' }, kids)
    },
  },
  {
    title: '是否安装', key: 'installed', width: 96, align: 'center',
    render: (r) => r.installed === null
      ? h(NTooltip, null, { trigger: () => h('span', { style: 'opacity:.45' }, '?'),
                            default: () => '还没设置 Penumbra 安装目录' })
      : r.installed
        ? h(NTag, { size: 'small', bordered: false, type: 'success' }, { default: () => '已安装' })
        : h('span', { style: 'opacity:.45' }, '未安装'),
  },
])
const checked = ref([])
const rowClassName = (r) => (r.installed ? 'row-installed' : '')
const rowProps = (row) => ({
  style: 'cursor:pointer',
  onClick: () => {
    focusArea.value = 'table'
    cur.value = row
    if (row.folder !== shotsFor.value) {
      shotsFor.value = row.folder
      loadShots(row.folder)
    }
  },
  // 双击一行 = 直接全屏看这条（长内容 / 多图时不用再点按钮）
  onDblclick: () => {
    focusArea.value = 'table'
    cur.value = row
    if (row.folder !== shotsFor.value) {
      shotsFor.value = row.folder
      loadShots(row.folder)
    }
    detmode.value = 'half'
  },
})

// ------------------------------------------------------------------ 增删改
function openAdd() {
  form.value = { ...blank(), category: cat.value || cats.value[0]?.name || '' }
  mode.value = 'add'
  showForm.value = true
}
function openEdit() {
  if (!cur.value) return msg.warning('先在左边选一条')
  const m = cur.value
  form.value = { src: '', folder: m.folder, category: m.category, zone: m.nsfw,
                 subcat: m.subcat || '', seq: m.seq, author: m.author, name: m.name,
                 addr: m.addr || '', affects: m.affects || '', move: false }
  mode.value = 'edit'
  showForm.value = true
}
async function submitForm() {
  const f = form.value
  busy.value = true
  try {
    if (mode.value === 'add') {
      if (!f.src.trim()) throw new Error('请填要导入的文件夹/压缩包路径，或从「待导入」里选一个')
      if (!f.category) throw new Error('请选分类')
      const r = await api.addMod({ ...f, src: f.src.trim() })
      msg.success('已导入：' + r.rel)
    } else {
      const r = await api.editMod({
        folder: f.folder, category: f.category, zone: f.zone, subcat: f.subcat || '',
        author: f.author, name: f.name, seq: f.seq, addr: f.addr, affects: f.affects || '',
      })
      if (cur.value && cur.value.folder === f.folder) cur.value.affects = r.affects ?? (f.affects || '')
      msg.success('已更新：' + r.rel)
    }
    showForm.value = false
    emit('changed')
    await loadMeta()
  } catch (e) {
    msg.error(e.message)
  } finally {
    busy.value = false
  }
}
function doDelete(rows) {
  const src = (rows && rows.length ? rows : cur.value ? [cur.value] : [])
  // ★ 工具栏按钮传的是 checked = **文件夹路径字符串数组**，右侧按钮传的是整条 Mod 对象。
  //   这里统一成 {folder, name}：以前直接按对象读 m.folder/m.name，对字符串全是 undefined，
  //   于是把 undefined 发给后端 → "路径不在 Mod 目录里，拒绝删除"（2026-09 主人报的 bug）。
  const list = src.map((x) => {
    if (typeof x === 'string') {
      const hit = (props.mods || []).find((m) => m.folder === x)
      return hit || { folder: x, name: x.split(/[\\/]/).filter(Boolean).pop() || x }
    }
    return x && x.folder ? x : null
  }).filter(Boolean)
  if (!list.length) return msg.warning('先选要删的 Mod')
  dialog.warning({
    title: '删除 Mod',
    content: `要把这 ${list.length} 个 Mod 移入回收站吗？\n${list.slice(0, 6).map((m) => '· ' + (m.name || m.folder)).join('\n')}` +
      (list.length > 6 ? `\n… 还有 ${list.length - 6} 个` : ''),
    positiveText: '移入回收站',
    negativeText: '取消',
    onPositiveClick: async () => {
      busy.value = true
      const ok = []
      const bad = []
      for (const m of list) {
        try {
          await api.deleteMod({ folder: m.folder })
          ok.push(m.name)
        } catch (e) {
          bad.push(`${m.name || m.folder || '（没有名字）'}：${e.message}`)
        }
      }
      busy.value = false
      if (ok.length) msg.success(`已删除 ${ok.length} 个：${ok[ok.length - 1] || ''}`)
      if (bad.length) {
        msg.error('删除失败 ' + bad.length + ' 个：' + bad[0], { duration: 12000 })
        console.warn('删除失败详情', bad)
      }
      checked.value = []
      cur.value = null
      emit('changed')
      await loadMeta()
    },
  })
}

async function fixCover() {
  if (!cur.value) return msg.warning('先选一条')
  fixing.value = true
  try {
    const r = await api.fixCover({ folder: cur.value.folder })
    if (r && r.img) {
      msg.success(`${r.already ? '本来就有预览图' : '已补上预览图'}：${r.name}` +
                  (r.how ? `（${r.how}）` : ''))
      await loadShots(cur.value.folder)
      emit('changed')
    } else {
      msg.warning('没抓到封面：' + ((r && r.reason) || '未知原因') +
        (r && r.tried && r.tried.length ? '［' + r.tried.slice(0, 2).join('；') + '］' : ''),
        { duration: 15000 })
    }
  } catch (e) {
    msg.error('补预览图失败：' + e.message, { duration: 15000 })
  } finally {
    fixing.value = false
  }
}

async function checkBridge() {
  try {
    const r = await api.bridgeStatus()
    bridgeOk.value = !!r.ok
    bridgeVer.value = r.plugin_version || ''
    bridgeVerOld.value = !!r.plugin_version && r.plugin_ok === false
    return r
  } catch (e) {
    bridgeOk.value = false
    return { ok: false, error: e.message }
  }
}




async function installToGame(direct = false) {
  if (!cur.value) return msg.warning('先在左边选一条 Mod')
  installing.value = true
  try {
    const r = direct ? await api.bridgeInstall(cur.value.folder)
                     : await api.bridgePropose(cur.value.folder)
    bridgeOk.value = true
    const name = (r && r.sent && r.sent.name) || cur.value.name
    if (direct) {
      msg.success(`已让游戏开始安装：${name}（进度在游戏内窗口看）`, { duration: 12000 })
    } else {
      msg.success(`已送到游戏里：${name} —— 请在游戏内窗口点「确认安装」`, { duration: 12000 })
    }
  } catch (e) {
    bridgeOk.value = false
    msg.error('送到游戏失败：' + e.message, { duration: 20000 })
  } finally {
    installing.value = false
  }
}

async function copyPath() {
  if (!cur.value) return
  try {
    await navigator.clipboard.writeText(cur.value.folder)
    msg.success('路径已复制')
  } catch (e) {
    msg.error('复制失败（浏览器权限）')
  }
}
</script>

<template>
  <div class="wrap" :class="'det-' + detmode">
    <div class="left">
      <div class="bar">
        <n-input ref="searchEl" v-model:value="q" placeholder="搜索 名称／作者／标签／影响替换／路径…" size="small"
                 clearable style="width: 230px" />
        <n-select v-model:value="cat" :options="catOptions" size="small" clearable
                  placeholder="全部分类" style="width: 140px" />
        <n-select v-model:value="sub" :options="subFilterOptions" size="small" clearable
                  placeholder="全部子分类" style="width: 120px" />
        <n-select v-model:value="zone" :options="zoneOptions" size="small" clearable
                  placeholder="全部类型" style="width: 104px" />
        <n-button size="small" :type="advCount ? 'primary' : 'default'" @click="advOpen = true">
          高级搜索{{ advCount ? `（${advCount}）` : '' }}
        </n-button>
        <n-button-group size="small">
          <n-button :type="wall ? 'default' : 'primary'" @click="wall = false">表格</n-button>
          <n-button :type="wall ? 'primary' : 'default'" @click="wall = true">图片墙</n-button>
        </n-button-group>
        <span class="dim">共 {{ mods.length }} 条 ｜ 显示 {{ view.length }} 条</span>
        <div class="grow"></div>
        <n-button size="small" type="primary" @click="openAdd">添加 Mod…</n-button>
        <n-button size="small" @click="openEdit" :disabled="!cur">编辑</n-button>
        <n-button size="small" :disabled="!checked.length && !cur" @click="doDelete(checked)">
          删除{{ checked.length ? `（${checked.length}）` : '' }}
        </n-button>
        <n-button size="small" :disabled="!cur" :loading="fixing" @click="fixCover">补预览图</n-button>
      </div>
      <div class="bar row2">
        <n-button size="small" :loading="updateChecking" @click="checkUpdates">检查更新</n-button>
        <n-button size="small" :loading="cloudBusy" @click="archiveCloud()">归档到云盘</n-button>
        <n-button size="small" :loading="cloudBusy" @click="restoreCloud()">从云盘取回</n-button>
        <n-button size="small" :loading="cloudBusy" @click="askReconcile()">与网盘对账</n-button>
        <template v-if="updCount">
          <n-button size="small" :type="onlyUpd ? 'primary' : 'default'"
                    @click="onlyUpd = !onlyUpd">只看有新版（{{ updCount }}）</n-button>
          <n-select v-model:value="replaceMode" size="small" style="width: 148px"
                    :options="[{ label: '只替换同名文件', value: 'same_name' },
                               { label: '清掉旧文件再放', value: 'all_payload' }]" />
          <n-button size="small" :loading="updating" :disabled="!updFolders.length" @click="doUpdate()">
            更新选中{{ updFolders.length ? `（${updFolders.length}）` : '' }}
          </n-button>
        </template>
        <span v-else class="dim">检查到站点有新版本时，这里会出现「只看有新版 / 更新选中」</span>
      </div>
      <div v-if="checked.length" class="batchbar">
        <b>已选 {{ checked.length }} 个</b>
        <n-select v-model:value="batch.category" :options="catOptions" size="small" clearable
                  placeholder="改成分类" style="width: 150px" />
        <n-select v-model:value="batch.zone" size="small" clearable placeholder="改成类型"
                  style="width: 120px"
                  :options="[{ label: 'SFW', value: 'SFW' }, { label: 'NSFW', value: 'NSFW' }]" />
        <n-checkbox v-model:checked="batch.affectsOn" size="small">影响/替换</n-checkbox>
        <n-select v-model:value="batch.affects" :options="affectsOptions" :disabled="!batch.affectsOn"
                  size="small" filterable tag clearable
                  :placeholder="batch.affectsOn ? '填/选替换对象（留空 = 清空）' : '勾上左边才改'"
                  style="width: 210px" />
        <n-input v-model:value="batch.subcat" size="small" placeholder="改成子分类（可留空）"
                 style="width: 150px" />
        <n-button size="small" type="primary" @click="applyBatch">应用到选中</n-button>
        <n-select v-model:value="batch.tags" :options="tagOptions" multiple filterable tag
                  size="small" placeholder="标签（可新建）" style="width: 190px" />
        <n-button size="small" @click="batchTag(true)">加标签</n-button>
        <n-button size="small" @click="batchTag(false)">去标签</n-button>
        <n-button size="small" @click="checked = []">取消选择</n-button>
        <div class="grow"></div>
        <span class="dim">快捷键：↑↓ 选中 ／ Enter 编辑 ／ Delete 删除 ／ Ctrl+F 搜索 ／ Esc 清空搜索</span>
      </div>
      <div class="table">
        <div v-if="wall && mods.length" class="wall">
          <div v-for="m in view" :key="m.folder" class="cell"
               :class="{ sel: cur && cur.folder === m.folder, ins: m.installed }"
               @click="cur = m">
            <img v-if="m.has_img" :src="api.thumb(m.folder, 320, m.ih)" loading="lazy" alt="" />
            <div v-else class="noimg">无预览图</div>
            <div class="cap">
              <b>{{ m.seq }}. {{ m.name }}
                <span v-if="m.cloud_state === 'archived'" class="cchip"
                      :title="'载荷已归档到云端：' + (m.archived_files || 0) + ' 个文件 ｜ '
                              + humanMB(m.cloud_size || 0) + ' ｜ 本地没有载荷副本'">☁ 云</span>
                <span v-else-if="m.cloud_state === 'missing'" class="cchip bad"
                      title="本地和云端都找不到载荷">⚠ 缺失</span>
              </b>
              <span class="dim">{{ m.author || '—' }} · {{ m.category }}{{ m.subcat ? ' / ' + m.subcat : '' }}</span>
            </div>
          </div>
        </div>
        <n-data-table
          v-else-if="mods.length"
          :columns="columns" :data="view" :row-class-name="rowClassName" :row-props="rowProps"
          :row-key="(r) => r.folder" :checked-row-keys="checked"
          @update:checked-row-keys="(k) => (checked = k)"
          :max-height="'100%'" :scroll-x="1220" size="small" striped flex-height
        />
        <n-empty v-else style="margin: auto" description="还没有索引数据，点右上角「重新扫描」" />
      </div>
    </div>

    <aside class="right">
      <!-- 顶部通栏：游戏内插件状态（XMA 那条兼容性横幅的位置） -->
      <div class="bridge-bar"
           :class="bridgeOk === true ? 'ok' : (bridgeOk === false ? 'bad' : '')">
        <span class="dot"></span>
        <span class="txt">
          {{ bridgeOk === true
             ? ('游戏内插件已连接' + (bridgeVer ? '（v' + bridgeVer + '）' : '') +
                (bridgeVerOld ? ' ⚠ 版本过旧，去「设置 → 版本」看怎么更新' : ' · 可以一键送到游戏里确认'))
             : (bridgeOk === false ? '游戏内插件没连上' : '正在检查游戏内插件…') }}
        </span>
        <span class="grow"></span>
        <n-button size="tiny" quaternary @click="checkBridge">重测</n-button>
        <n-button v-if="bridgeOk === false" size="tiny" type="primary" ghost
                  :disabled="!cur" :loading="installing" @click="installToGame(false)">
          查看原因
        </n-button>
      </div>

      <div class="col-main">
        <!-- ① 标题区（XMA 左上）：Mod 名称 + 版本 / 分类说明 + 站点链接 -->
        <div v-if="detmode !== 'narrow'" class="dtitle">
          <div class="r1">
            <h2>{{ cur?.name || '未选择 Mod' }}</h2>
            <span class="ver">
              {{ cur?.site_version ? 'v' + cur.site_version : '' }}
              {{ cur?.site_latest || cur?.site_updated
                 ? ' · 更新于 ' + (cur.site_latest || cur.site_updated) : '' }}
            </span>
          </div>
          <div class="r2">
            <span v-if="cur?.nsfw" class="badge">{{ cur.nsfw }}</span>
            <span v-if="cur?.cloud_state === 'archived'" class="badge cloud"
                  :title="'载荷已归档到云端（本地没有文件）：' + (cur.archived_files || 0) + ' 个文件 ｜ '
                          + humanMB(cur.cloud_size || 0)
                          + (cur.cloud_synced ? ' ｜ ' + cur.cloud_synced : '')
                          + (cur.cloud_path ? '\n' + cur.cloud_path : '')">
              ☁ 载荷在云端</span>
            <span v-else-if="cur?.cloud_state === 'missing'" class="badge bad"
                  title="本地和云端都找不到载荷">⚠ 载荷缺失</span>
            <span class="cat">{{ cur?.category || '—' }}<template v-if="cur?.subcat"> · {{ cur.subcat }}</template></span>
            <span>by</span>
            <span class="au">{{ cur?.author || '—' }}</span>
            <span class="grow"></span>
            <a v-if="cur?.addr" class="lnk" :href="cur.addr" target="_blank" rel="noreferrer">
              [ 站点页面 ]
            </a>
          </div>
        </div>

        <!-- ② 大图轮播（XMA 左侧中部）：‹ › 切图 + 计数 + 缩略图条 -->
        <n-card size="small" :title="detmode === 'narrow' && cur ? cur.name : '预览'" class="pv-card">
          <template #header-extra>
            <n-button size="tiny" :disabled="!cur" @click="showAddImg = true">添加图片…</n-button>
          </template>
          <input ref="fileEl" type="file" accept="image/*" multiple
                 style="display: none" @change="onFiles" />
          <div class="preview">
            <n-image v-if="shotPath || (cur && cur.has_img)"
                     :src="shotPath ? api.imgUrl(shotPath, 1000)
                                   : api.thumb(cur.folder, 900, cur.ih)"
                     object-fit="contain" class="pv-img"
                     :img-props="{ style: 'width:100%;height:100%;object-fit:contain' }" />
            <div v-else class="ph">← 左侧点一条看预览图</div>
            <template v-if="shots.length > 1">
              <button class="navbtn prev" title="上一张（← 键）" @click.stop="selectShot(shotIdx - 1)">‹</button>
              <button class="navbtn next" title="下一张（→ 键）" @click.stop="selectShot(shotIdx + 1)">›</button>
              <span class="navcnt">{{ shotIdx + 1 }} / {{ shots.length }}</span>
            </template>
          </div>
          <div v-if="shots.length" class="shots" :class="{ kbfocus: focusArea === 'strip' }">
            <div v-for="im in shots" :key="im.path" class="shot"
                 :class="{ active: im.path === shotPath, current: im.is_current }"
                 :title="im.rel + ' · ' + im.human" @click="selectShot(shots.indexOf(im))">
              <img :src="im.thumb" loading="lazy" alt="" />
              <button class="delbtn" title="删除这张图（进回收站）"
                      @click.stop="delImage(im)">✕</button>
              <span v-if="im.is_current" class="tag">当前</span>
              <button v-else class="setbtn" @click.stop="useAsPreview(im)">设为预览图</button>
            </div>
            <span class="count">共 {{ shots.length }} 张</span>
          </div>
          <div v-if="shots.length" class="strip-hint">
            {{ focusArea === 'strip' ? '← → 选图 ｜ Enter 设为预览图 ｜ Delete 删图 ｜ Esc 回到列表'
                                     : '← → 选图后，Enter/Delete 就作用于图片' }}
          </div>
        </n-card>

        <!-- ③ 内容描述区（XMA 左下）：描述 / 文件 / 历史 —— 只在展开时给，窄栏不占地方 -->
        <n-card v-if="detmode !== 'narrow'" size="small" class="descbox-card">
          <n-tabs v-model:value="dtabs" size="small" type="line" animated>
            <n-tab-pane name="desc" tab="描述">
              <div v-if="cur?.desc" class="desctext">{{ cur.desc }}</div>
              <div v-else class="descempty">
                还没有内容描述。点下面「编辑描述…」自己写一段；以后从站点导入时会自动带过来。
              </div>
              <n-button size="tiny" quaternary :disabled="!cur" style="margin-top: 4px"
                        @click="openDescEdit">编辑描述…</n-button>
            </n-tab-pane>

            <n-tab-pane name="files" tab="文件">
              <n-spin v-if="tabBusy === 'files'" size="small" />
              <template v-else-if="cur && filesMap[cur.folder]">
                <template v-if="filesMap[cur.folder].ok">
                  <div class="flist">
                    <template v-for="f in filesMap[cur.folder].items" :key="f.name">
                      <!-- 文件：整行就是下载链接（点文件名直接存盘） -->
                      <a v-if="!f.dir" class="frow link" :href="api.modFileUrl(cur.folder, f.name)"
                         :download="f.name" :title="'下载 ' + f.name">
                        <span class="fname">{{ f.name }}</span>
                        <span class="fsize">{{ humanSize(f.size) }}</span>
                        <span class="ftime">{{ f.mtime }}</span>
                        <span class="fdl">⤓</span>
                      </a>
                      <div v-else class="frow">
                        <span class="fname">{{ f.name }}</span>
                        <span class="fsize">文件夹</span>
                        <span class="ftime">{{ f.mtime }}</span>
                      </div>
                    </template>
                  </div>
                  <div class="ftotal">
                    共 {{ filesMap[cur.folder].count }} 项 ｜ 合计 {{ humanSize(filesMap[cur.folder].total) }}
                    ｜ 点文件名就能下载
                  </div>

                  <!-- 云端载荷：归档后本地没有这些文件了，列出来、点了直接从云端下载 -->
                  <template v-if="(filesMap[cur.folder].cloud || []).length">
                    <div class="clabel">云端载荷（本地已归档 —— 点文件名从云端下载）</div>

                    <!-- 下载进度条 -->
                    <div v-if="dl" class="dlbox">
                      <div class="dlhead">
                        <span class="dlname" :title="dl.name">{{ dl.name }}</span>
                        <span class="grow"></span>
                        <n-button v-if="dl.state === 'running'" size="tiny" quaternary
                                  @click="cancelDownload">取消</n-button>
                        <n-button v-else size="tiny" quaternary @click="dl = null">关闭</n-button>
                      </div>
                      <n-progress type="line" size="small" :percentage="dl.pct"
                                  :status="dl.state === 'error' ? 'error'
                                           : (dl.state === 'done' ? 'success' : 'default')"
                                  :show-indicator="false" style="margin-top: 4px" />
                      <div class="dlstat">
                        <template v-if="dl.state === 'running'">
                          {{ humanSize(dl.done) }} / {{ dl.total ? humanSize(dl.total) : '?' }}
                          ｜ {{ dl.pct }}% ｜ {{ humanSize(dl.speed) }}/s
                        </template>
                        <template v-else-if="dl.state === 'done'">✓ 完成（{{ humanSize(dl.done) }}）</template>
                        <template v-else-if="dl.state === 'cancelled'">已取消</template>
                        <template v-else>✗ {{ dl.error }}</template>
                      </div>
                    </div>

                    <div class="flist">
                      <a v-for="c in filesMap[cur.folder].cloud" :key="c.rel_path"
                         class="frow link" href="#" :title="'从云端下载 ' + c.rel_path"
                         @click.prevent="downloadCloud(cur.folder, c.rel_path)">
                        <n-tag size="tiny" :bordered="false" type="info"
                               style="flex:0 0 auto;margin-right:4px">云</n-tag>
                        <span class="fname">{{ c.rel_path }}</span>
                        <span class="fsize">{{ humanSize(c.size) }}</span>
                        <span class="fdl">⤓</span>
                      </a>
                    </div>
                    <div class="ftotal">
                      云端 {{ filesMap[cur.folder].cloud.length }} 个载荷文件
                      ｜ <a :href="filesMap[cur.folder].open_url || '#/'" target="_blank"
                            rel="noreferrer">在网盘里打开这个目录</a>
                      <template v-if="filesMap[cur.folder].share_url">
                        ｜ <a :href="filesMap[cur.folder].share_url" target="_blank"
                              rel="noreferrer">分享页</a>
                      </template>
                    </div>
                  </template>
                </template>
                <div v-else class="descempty">{{ filesMap[cur.folder].error || '读不到文件清单' }}</div>
              </template>
              <div v-else class="descempty">选中一条 Mod 后，这里列出它文件夹里的文件。</div>
            </n-tab-pane>

            <n-tab-pane name="hist" tab="历史">
              <n-spin v-if="tabBusy === 'hist'" size="small" />
              <template v-else-if="cur && histMap[cur.folder]">
                <template v-if="(histMap[cur.folder].items || []).length">
                  <div v-for="(h, hi) in histMap[cur.folder].items" :key="hi" class="hrow">
                    <div class="hline">
                      <b>v{{ h.version }}</b>
                      <span v-if="h.prev" class="dim">（上一版 v{{ h.prev }}）</span>
                      <span class="grow"></span>
                      <span class="ftime">{{ h.time }}</span>
                    </div>
                    <div v-if="h.notes" class="hnotes">{{ h.notes }}</div>
                  </div>
                </template>
                <div v-else class="descempty">
                  {{ histMap[cur.folder].error || '站点上没有版本历史' }}
                  <a v-if="cur?.addr" :href="cur.addr" target="_blank" rel="noreferrer">去站点看更新记录</a>
                </div>
              </template>
              <div v-else class="descempty">选中一条 Mod 后，这里显示它在站点上的版本更新记录。</div>
            </n-tab-pane>
          </n-tabs>
        </n-card>
      </div>

      <div class="col-side">
        <!-- ④ 操作区（XMA 右上）：作者 → 主按钮 → 次按钮 → 统计 -->
        <n-card size="small" title="操作" class="act-card">
          <template #header-extra>
            <n-button-group size="tiny">
              <n-button :type="detmode === 'narrow' ? 'primary' : 'default'"
                        title="窄栏：详情固定在右侧 400px" @click="setDetmode('narrow')">窄栏</n-button>
              <n-button :type="detmode === 'half' ? 'primary' : 'default'"
                        title="半屏：详情占大半（双击列表某一行也是这个）"
                        @click="setDetmode('half')">半屏</n-button>
              <n-button :type="detmode === 'full' ? 'primary' : 'default'"
                        title="全屏：详情铺满窗口" @click="setDetmode('full')">全屏</n-button>
            </n-button-group>
          </template>

          <div v-if="cur" class="who">
            <span class="ava">{{ (cur.author || '?').slice(0, 1).toUpperCase() }}</span>
            <span class="wname">{{ cur.author || '未知作者' }}</span>
            <n-tag v-if="cur.nsfw" size="tiny" :bordered="false" class="wtag">{{ cur.nsfw }}</n-tag>
          </div>

          <div class="opgrid">
            <n-button class="opmain" block size="small" type="primary" ghost :disabled="!cur || !cur.addr"
                      @click="updateOne(cur)">
              {{ isHelio(cur) ? '打开页面下载' : '从站点更新' }}
            </n-button>
            <n-button block size="small" type="primary" :disabled="!cur" :loading="installing"
                      @click="installToGame(false)">安装到游戏</n-button>
            <n-button block size="small" :disabled="!cur" @click="openReplace">上传新文件替换…</n-button>
          </div>

          <div class="oplinks">
            <n-button text size="tiny" :disabled="!cur" @click="cur && api.open('folder', cur.folder)">
              打开文件夹
            </n-button>
            <span class="sep">·</span>
            <n-button text size="tiny" :disabled="!cur" @click="copyPath">复制路径</n-button>
            <template v-if="cur?.has_img">
              <span class="sep">·</span>
              <n-button text size="tiny" tag="a" :href="api.raw(cur.folder)" target="_blank">查看原图</n-button>
            </template>
          </div>

          <div v-if="cur" class="opcloud">
          <!-- 归档 / 取回 只放在列表上方那个工具栏（能作用于选中项或全部），这里不再重复 -->
          <n-button size="tiny" quaternary :loading="cloudBusy" :disabled="!cur.archived_files"
                    @click="verifyCloud([cur.folder])">校验云端</n-button>
          <a v-if="cur.archived_files" class="oplink" target="_blank" rel="noreferrer"
             :href="'/api/cloud/open?folder=' + encodeURIComponent(cur.folder)">在网盘里打开</a>
          <span class="cl" :title="cur.cloud_path || ''">
            <template v-if="cur.cloud_state === 'archived'">
              已归档 {{ cur.archived_files }} 个文件 ｜ {{ humanMB(cur.cloud_size) }}
              <template v-if="cur.cloud_synced"> ｜ {{ cur.cloud_synced.slice(5, 16) }}</template>
            </template>
            <template v-else-if="cur.cloud_state === 'missing'">
              ⚠ 云端有文件找不到，取回可能失败
            </template>
            <template v-else-if="cur.payload_size">
              本地载荷 {{ humanMB(cur.payload_size) }}（未归档）
            </template>
            <template v-else>本地没有载荷</template>
          </span>
        </div>

        <div v-if="cur && !cur.addr" class="opnote">没有站点地址，这条只能手动替换</div>

          <div v-if="cur" class="stats" :class="{ compact: detmode !== 'full' }">
            <div class="st"><b>{{ shots.length }}</b><span>张图</span></div>
            <div class="st"><b>{{ humanSize(cur.payload_size) }}</b><span>{{ cur.payload_files || 0 }} 个文件</span></div>
            <div class="st"><b>{{ cur.site_version ? 'v' + cur.site_version : '—' }}</b><span>站点版本</span></div>
          </div>
        </n-card>

        <!-- ⑤ 元信息（XMA 右下）：分类 / 更新时间 / 发布日期 / 影响替换 / 种族 / 性别 / 标签 / 地址 -->
        <n-card size="small" class="desc-card">
          <n-descriptions :column="detmode === 'narrow' ? 2 : 1"
                          label-placement="left" size="small" label-width="52"
                          style="margin-bottom: 2px">
            <n-descriptions-item label="分类" :span="detmode === 'narrow' ? 2 : 1">
              {{ cur?.category || '—' }}<template v-if="cur?.subcat"> · {{ cur.subcat }}</template>
              ｜ 序号 {{ cur?.seq ?? '—' }}
            </n-descriptions-item>
            <n-descriptions-item label="更新时间" :span="detmode === 'narrow' ? 2 : 1">
              {{ cur?.site_latest || cur?.site_updated || '—' }}
              <n-tag v-if="cur?.update_avail" size="tiny" type="warning" :bordered="false"
                     style="margin-left:6px;cursor:pointer" @click="onlyUpd = true">有新版</n-tag>
              <n-tag v-if="cur?.site_version" size="tiny" :bordered="false"
                     :title="'站点上的最新版本号'" style="margin-left:6px">v{{ cur.site_version }}</n-tag>
              <div v-if="cur?.site_updated && cur?.site_latest && cur.site_updated !== cur.site_latest"
                   class="dim">本地这份下载于 {{ cur.site_updated }}</div>
            </n-descriptions-item>
            <n-descriptions-item label="发布日期" :span="detmode === 'narrow' ? 2 : 1">
              {{ cur?.released || '—' }}
            </n-descriptions-item>
            <n-descriptions-item label="类型" :span="detmode === 'narrow' ? 2 : 1">
              {{ cur?.nsfw || '—' }}
            </n-descriptions-item>
          </n-descriptions>

          <div class="tagedit">
            <span class="lbl" title="这条 Mod 替换/影响游戏里的哪些东西（XMA 的 Affects / Replaces）">
              影响/替换
            </span>
            <n-dynamic-tags :value="splitList(cur && cur.affects)" size="small"
                            :disabled="!cur" @update:value="saveAffectsList" />
          </div>
          <div class="tagedit">
            <span class="lbl" title="XMA 的 Races（种族）：检查更新时自动带过来，也能自己改">
              种族
            </span>
            <n-dynamic-tags :value="splitList(cur && cur.races)" size="small"
                            :disabled="!cur" @update:value="(v) => saveSiteMeta('races', v)" />
          </div>
          <div class="tagedit">
            <span class="lbl" title="XMA 的 Genders（性别）：检查更新时自动带过来，也能自己改">
              性别
            </span>
            <n-dynamic-tags :value="splitList(cur && cur.genders)" size="small"
                            :disabled="!cur" @update:value="(v) => saveSiteMeta('genders', v)" />
          </div>
          <div class="tagedit">
            <span class="lbl">标签</span>
            <n-dynamic-tags :value="(cur && cur.tags) || []" size="small"
                            :disabled="!cur" @update:value="saveTags" />
          </div>

          <n-descriptions :column="1" label-placement="left" size="small" label-width="56">
            <n-descriptions-item label="地址">
              <a v-if="cur?.addr" class="addr" :href="cur.addr" target="_blank"
                 rel="noreferrer">{{ cur.addr }}</a>
              <span v-else>—</span>
            </n-descriptions-item>
          </n-descriptions>
        </n-card>
      </div>

      <!-- 内容描述编辑 -->
      <n-modal v-model:show="descEdit" preset="card" style="width: 640px" title="编辑内容描述">
        <n-input v-model:value="descText" type="textarea" :rows="8"
                 placeholder="写这条 Mod 是做什么的、装了会怎样、注意事项…（留空 = 清空）" />
        <template #footer>
          <n-space justify="end">
            <n-button size="small" @click="descEdit = false">取消</n-button>
            <n-button size="small" type="primary" @click="saveDesc">保存</n-button>
          </n-space>
        </template>
      </n-modal>
    </aside>

    <!-- 追加图片 -->
    <n-modal v-model:show="showAddImg" preset="card" style="width: 560px" title="给这条 Mod 加图片">
      <n-alert type="info" :show-icon="false" style="margin-bottom: 10px">
        图片会存进这个 Mod 的文件夹里（名字自动编号），下面那条缩略图里就能看到、也能点「设为预览图」。
      </n-alert>
      <n-space vertical size="medium">
        <div>
          <div class="secttl">① 从本机选文件（可多选）</div>
          <n-button size="small" :loading="adding" @click="pickFiles">选择图片…</n-button>
        </div>
        <div>
          <div class="secttl">② 粘贴图片网址</div>
          <n-space>
            <n-input v-model:value="imgUrl" size="small" style="width: 330px"
                     placeholder="https://.../xxx.jpg" @keyup.enter="addByUrl" />
            <n-button size="small" :loading="adding" @click="addByUrl">添加</n-button>
          </n-space>
        </div>
        <div>
          <div class="secttl">③ 抓内置浏览器当前页面上的全部图片（Mod 页面的画廊）</div>
          <n-space align="center">
            <n-button size="small" :loading="adding" @click="addFromPage">抓取当前页面全部图片</n-button>
            <span class="dim">需要先在内置浏览器里打开这条 Mod 的页面</span>
          </n-space>
        </div>
        <div>
          <div class="secttl">④ 用你在自己浏览器里推来的信息（书签小工具）</div>
          <n-space align="center" style="flex-wrap: wrap">
            <n-button size="small" :loading="adding" :disabled="!inboxPage" @click="addFromInbox">
              添加推来的图片
            </n-button>
            <n-button size="small" quaternary @click="readInbox">刷新推来的信息</n-button>
            <span v-if="inboxPage" class="dim">
              {{ inboxPage.name || inboxPage.title || '(没读到名称)' }} ·
              画廊 {{ (inboxPage.imgs || []).length }} 张 · {{ inboxAge }}
            </span>
            <span v-else class="dim">还没收到你浏览器推来的页面信息</span>
          </n-space>
          <div v-if="inboxPage && cur && inboxPage.modid && String(cur.addr || '').indexOf(inboxPage.modid) < 0"
               style="color: #e88080; font-size: 12px; margin-top: 4px">
            ⚠ 推来的页面（modid {{ inboxPage.modid }}）和这条 Mod 的地址对不上，确认没推错再加
          </div>
          <div v-if="inboxPage && inboxPage.old_bookmarklet"
               style="color: #e8b060; font-size: 12px; margin-top: 4px">
            ⚠ 你用的书签小工具是<b>旧版</b>（只推封面、没有画廊图）。点「添加推来的图片」我会
            自动开内置浏览器去那条页面现抓；想以后一次拿全，请回「下载工作台」<b>重新拖一次书签小工具</b>。
          </div>
        </div>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button size="small" @click="showAddImg = false">关闭</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 添加 / 编辑 -->
    <n-modal v-model:show="showForm" preset="card" style="width: 560px"
             :title="mode === 'add' ? '添加 Mod' : '编辑 Mod'">
      <n-form label-placement="left" label-width="86" size="small">
        <template v-if="mode === 'add'">
          <n-form-item label="来源">
            <n-select v-model:value="form.src" :options="pendingOptions" filterable clearable
                      placeholder="从「待导入」里选一个，或直接粘路径到下面" />
          </n-form-item>
          <n-form-item label="或手填路径">
            <n-input v-model:value="form.src" placeholder="D:\下载\xxx 或 D:\下载\mod.zip" />
          </n-form-item>
        </template>
        <n-form-item label="分类">
          <n-select v-model:value="form.category" :options="catOptions" filterable
                    placeholder="选分类（要新建请去「分类管理」）" />
        </n-form-item>
        <n-form-item label="类型">
          <n-radio-group v-model:value="form.zone">
            <n-radio-button value="SFW">SFW</n-radio-button>
            <n-radio-button value="NSFW">NSFW</n-radio-button>
          </n-radio-group>
        </n-form-item>
        <n-form-item label="子分类">
          <n-select v-model:value="form.subcat" :options="subOptions" filterable clearable tag
                    placeholder="可留空；也可直接输入新名字" />
        </n-form-item>
        <n-space>
          <n-form-item label="序号" label-width="86">
            <n-input-number v-model:value="form.seq" :min="1" style="width: 110px"
                            placeholder="自动" />
          </n-form-item>
          <n-form-item label="作者" label-width="52">
            <n-input v-model:value="form.author" placeholder="[Arte] 里的 Arte" />
          </n-form-item>
        </n-space>
        <n-form-item label="Mod 名称">
          <n-input v-model:value="form.name" placeholder="中括号后面的名字" />
        </n-form-item>
        <n-form-item label="Mod 地址">
          <n-input v-model:value="form.addr" placeholder="https://www.xivmodarchive.com/modid/12345" />
        </n-form-item>
        <n-form-item label="影响/替换">
          <n-select v-model:value="form.affects" :options="affectsOptions" filterable clearable tag
                    placeholder="它替换游戏里的什么（留空 = 不设置；下载/解析时会自动填）" />
        </n-form-item>
        <n-form-item v-if="mode === 'add'" label="处理方式">
          <n-switch v-model:value="form.move" />
          <span class="dim" style="margin-left: 8px">
            {{ form.move ? '移动到库里（删除原文件）' : '复制到库里（保留原文件）' }}
          </span>
        </n-form-item>
      </n-form>
      <n-alert v-if="mode === 'edit'" type="info" :show-icon="false" style="margin-top: 4px">
        改名字 / 序号 / 分类会真的重命名文件夹，库里的路径会跟着变。
      </n-alert>
      <template #footer>
        <n-space justify="end">
          <n-button size="small" @click="showForm = false">取消</n-button>
          <n-button size="small" type="primary" :loading="busy" @click="submitForm">
            {{ mode === 'add' ? '导入' : '保存' }}
          </n-button>
        </n-space>
      </template>
    </n-modal>
    <!-- 高级搜索（工具条按钮点进来） -->
    <n-modal v-model:show="advOpen" preset="card" style="width: 780px" title="高级搜索">
      <n-alert type="default" :show-icon="false" style="margin-bottom: 12px">
        就是几个填空 + 下拉：<b>留空 = 不看这个条件</b>，改完<b>立即生效</b>（后面的列表实时跟着变）。
        标签也可以用这里的「标签」框筛，不再占表格一列。
      </n-alert>
      <div class="advgrid">
        <span class="lbl">名称</span>
        <n-input v-model:value="fName" size="small" clearable placeholder="名称包含…" />
        <span class="lbl">作者</span>
        <n-input v-model:value="fAuthor" size="small" clearable placeholder="作者包含…" />
        <span class="lbl">影响/替换</span>
        <n-input v-model:value="fAffectsText" size="small" clearable placeholder="它替换的对象包含…" />
        <span class="lbl">标签</span>
        <n-select v-model:value="fTagsText" :options="tagOptions" size="small" filterable tag clearable
                  placeholder="选已有标签或直接输入（包含匹配）" />
        <span class="lbl">分类</span>
        <n-select v-model:value="fCats" :options="catOptions" multiple filterable clearable
                  size="small" placeholder="可多选" />
        <span class="lbl">安装状态</span>
        <n-select v-model:value="fInst" :options="instOptions" size="small" clearable placeholder="全部" />
        <span class="lbl">标签有无</span>
        <n-select v-model:value="fTagState" :options="tagStateOptions" size="small" clearable
                  placeholder="全部" />
        <span class="lbl">预览图</span>
        <n-select v-model:value="fImg" :options="imgOptions" size="small" clearable placeholder="全部" />
        <span class="lbl">排序</span>
        <n-select v-model:value="sortBy" :options="sortOptions" size="small" />
        <span class="lbl">方向</span>
        <n-select v-model:value="sortDir" :options="sortDirOptions" size="small" />
      </div>
      <template #footer>
        <n-space justify="space-between" align="center" style="width: 100%">
          <n-space align="center">
            <n-button size="small" @click="clearAdv">清空条件</n-button>
            <n-button size="small" quaternary @click="loadTags">刷新标签列表</n-button>
            <span class="dim">当前显示 {{ view.length }} / {{ mods.length }} 条</span>
          </n-space>
          <n-button size="small" type="primary" @click="advOpen = false">完成</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 手动上传 / 指定新文件替换 -->
    <n-modal v-model:show="showReplace" preset="card" style="width: 600px" title="上传新文件替换">
      <n-alert v-if="repForm.name" type="info" :show-icon="false" style="margin-bottom: 10px">
        目标：<b>{{ repForm.name }}</b><br />
        文件夹里的 <b>地址.txt、预览图、编号、作者、名称、标签、影响/替换</b> 都会保留；
        被换下来的旧文件进回收站，能还原。
      </n-alert>
      <n-form label-placement="left" label-width="92">
        <n-form-item label="选新文件">
          <input type="file" @change="pickRepFile" />
          <span v-if="repForm.upName" class="dim" style="margin-left: 8px">{{ repForm.upName }}</span>
        </n-form-item>
        <n-form-item label="或填路径">
          <n-input v-model:value="repForm.src" size="small" clearable
                   placeholder="D:\下载\xxx.pmp ／ 也可以先用「待导入」，再填那个路径" />
        </n-form-item>
        <n-form-item label="替换方式">
          <n-radio-group v-model:value="repForm.mode" size="small">
            <n-radio-button value="same_name">只替换同名文件（推荐）</n-radio-button>
            <n-radio-button value="all_payload">清掉旧文件再放新的</n-radio-button>
          </n-radio-group>
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button size="small" @click="showReplace = false">取消</n-button>
          <n-button size="small" type="primary" :loading="repReplacing" @click="submitReplace">开始替换</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.wrap {
  height: 100%;
  min-height: 0;
  display: grid;
  grid-template-columns: 1fr 400px;
  grid-template-rows: minmax(0, 1fr);
  gap: 14px;
  padding: 14px 18px 16px;
}
.left {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.bar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.grow {
  flex: 1 1 auto;
}
.table {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
}
.dim {
  font-size: 12px;
  opacity: 0.6;
}
.batchbar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 8px;
  background: rgba(47, 111, 235, 0.08);
  flex-wrap: wrap;
}
.wall {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  /* 关键：行高必须按内容撑开（max-content）。
     只写 auto 时，一旦总数把容器撑满，行会被压到只有图片那么高(153px)，
     而标题块有 52px，被 .cell 的 overflow:hidden 整块裁掉 —— mod 名就看不见了。 */
  grid-auto-rows: max-content;
  gap: 10px;
  align-content: start;
  padding-right: 4px;
}
.wall .cell {
  border: 1px solid rgba(128, 128, 128, 0.2);
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
  background: rgba(128, 128, 128, 0.04);
}
.wall .cell.sel {
  outline: 2px solid #2f6feb;
  outline-offset: -1px;
}
.wall .cell.ins {
  background: rgba(60, 200, 120, 0.12);
}
.wall img,
.wall .noimg {
  width: 100%;
  height: 150px;
  object-fit: cover;
  display: block;
}
.wall .noimg {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  opacity: 0.45;
}
.wall .cap {
  padding: 6px 8px;
  font-size: 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.wall .cap b {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wall .cap .cchip {
  margin-left: 5px;
  padding: 0 4px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 400;
  background: rgba(32, 128, 240, 0.16);
  color: #2080f0;
  white-space: nowrap;
}
.wall .cap .cchip.bad {
  background: rgba(208, 48, 80, 0.16);
  color: #d03050;
}
.right {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  /* 实在放不下时滚动，绝不把内容裁掉 */
  overflow: auto;
}
/* ---- 详情展开：半屏 / 全屏。排布照 XMA mod 页的五个分区 ----
   左列 = ① 标题 ② 大图轮播 ③ 描述/文件/历史 ；右列 = ④ 操作 ⑤ 元信息
   两列各自独立堆叠（列内不留空档），列宽比 5:2 ---- */
.wrap.det-half {
  /* 半屏 = 列表让出大半，详情拿 60%：这样内部才排得下两列 */
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.5fr);
}
.wrap.det-full {
  grid-template-columns: minmax(0, 1fr);
}
.wrap.det-full .left {
  display: none;
}
.wrap.det-half .right,
.wrap.det-full .right {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(220px, 2fr);   /* 两列 5:2 */
  grid-template-areas:
    'bar bar'
    'main side';
  gap: 10px;
  align-items: start;
  /* 关键：不写这句，栅格默认 align-content:stretch 会把 auto 行平摊撑高 ——
     实测窗口高 1500 时状态条那行从 40px 涨到 121px，标题上方就空出一大块 */
  align-content: start;
  min-height: 0;
}
.wrap.det-half .bridge-bar,
.wrap.det-full .bridge-bar {
  grid-area: bar;
}
.wrap.det-half .col-main,
.wrap.det-full .col-main {
  grid-area: main;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}
.wrap.det-half .col-side,
.wrap.det-full .col-side {
  grid-area: side;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}
/* 窄栏：两列包装层不参与布局，按 order 排成单列（操作在最上、描述在最下） */
.wrap.det-narrow .col-main,
.wrap.det-narrow .col-side {
  display: contents;
}
.wrap.det-narrow .bridge-bar { order: 0; }
.wrap.det-narrow .act-card { order: 1; }
.wrap.det-narrow :deep(.pv-card) { order: 2; }
.wrap.det-narrow .desc-card { order: 3; }
.wrap.det-narrow .descbox-card { order: 4; }
/* 展开后图片填满可用空间（等比，不裁切不拉伸） */
.wrap.det-half :deep(.pv-card .n-card__content),
.wrap.det-full :deep(.pv-card .n-card__content) {
  min-height: 0;
}
.wrap.det-half :deep(.preview) {
  flex: 1 1 auto;
  min-height: 40vh;
}
.wrap.det-full :deep(.preview) {
  flex: 1 1 auto;
  min-height: 48vh;
}
.wrap.det-half :deep(.preview .n-image),
.wrap.det-full :deep(.preview .n-image),
.wrap.det-half :deep(.preview .pv-img),
.wrap.det-full :deep(.preview .pv-img) {
  width: 100%;
  height: 100%;
}
.wrap.det-half :deep(.preview img),
.wrap.det-full :deep(.preview img) {
  width: 100%;
  height: 100%;
  max-width: 100%;
  max-height: none;
  object-fit: contain;
}
/* 主按钮整行突出（对应 XMA 那颗大 Download Mod） */
.wrap.det-half .opgrid .opmain,
.wrap.det-full .opgrid .opmain {
  grid-column: 1 / -1;
}
/* 侧栏窄 → 其余动作改单列堆叠（XMA 侧栏就是竖着排的） */
.wrap.det-half .opgrid,
.wrap.det-full .opgrid {
  grid-template-columns: 1fr;
}

/* ---- ① 标题条 ---- */
.dtitle {
  flex: 0 0 auto;
  padding: 10px 14px;
  border-radius: 8px;
  background: rgba(128, 128, 128, 0.07);
}
.dtitle .r1 {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.dtitle h2 {
  margin: 0;
  font-size: 19px;
  font-weight: 600;
  line-height: 1.3;
  word-break: break-word;
}
.dtitle .ver {
  margin-left: auto;
  font-size: 12px;
  opacity: 0.6;
  white-space: nowrap;
}
.dtitle .r2 {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 6px;
  font-size: 12px;
  opacity: 0.85;
}
.dtitle .r2 .cat {
  font-weight: 600;
}
.dtitle .r2 .au,
.dtitle .r2 .lnk {
  color: #63a4ff;
}
.dtitle .r2 .grow {
  flex: 1 1 auto;
}
.dtitle .r2 .badge {
  padding: 0 5px;
  border-radius: 4px;
  font-size: 11px;
  background: rgba(128, 128, 128, 0.22);
}
.dtitle .r2 .badge.cloud {
  background: rgba(32, 128, 240, 0.16);
  color: #2080f0;
  cursor: help;
}
.dtitle .r2 .badge.bad {
  background: rgba(208, 48, 80, 0.16);
  color: #d03050;
  cursor: help;
}

/* ---- ② 大图轮播：‹ › 切图 + 右下角计数 ---- */
.preview {
  position: relative;
}
.navbtn {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 30px;
  height: 48px;
  border: 0;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.42);
  color: #fff;
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
  opacity: 0.5;
  transition: opacity 0.15s;
}
.navbtn:hover {
  opacity: 0.95;
}
.navbtn.prev {
  left: 6px;
}
.navbtn.next {
  right: 6px;
}
.navcnt {
  position: absolute;
  right: 8px;
  bottom: 8px;
  padding: 1px 7px;
  border-radius: 10px;
  font-size: 11px;
  background: rgba(0, 0, 0, 0.45);
  color: #fff;
}

/* ---- ③ 描述 / 文件 / 历史 ---- */
.descbox-card {
  flex: 0 0 auto;
}
.desctext {
  white-space: pre-wrap;
  line-height: 1.6;
  font-size: 13px;
}
.descempty {
  font-size: 12.5px;
  opacity: 0.55;
  line-height: 1.65;
}
.flist {
  display: flex;
  flex-direction: column;
}
.frow {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 2px;
  font-size: 12.5px;
  border-bottom: 1px dashed rgba(128, 128, 128, 0.18);
}
.frow:last-child {
  border-bottom: 0;
}
/* 可下载的文件行：整行可点，悬停高亮 + 右侧出现下载箭头 */
.frow.link {
  text-decoration: none;
  color: inherit;
  cursor: pointer;
  border-radius: 4px;
  padding-left: 4px;
  padding-right: 4px;
}
.frow.link:hover {
  background: rgba(128, 128, 128, 0.14);
}
.frow .fdl {
  flex: 0 0 auto;
  width: 14px;
  text-align: center;
  font-size: 12px;
  opacity: 0.35;
}
.frow.link:hover .fdl {
  opacity: 1;
}
.fname {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fsize,
.ftime {
  flex: 0 0 auto;
  opacity: 0.6;
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}
.ftime {
  min-width: 92px;
  text-align: right;
}
.ftotal {
  margin-top: 6px;
  font-size: 11.5px;
  opacity: 0.6;
}
.hrow {
  padding: 5px 2px;
  border-bottom: 1px dashed rgba(128, 128, 128, 0.18);
}
.hrow:last-child {
  border-bottom: 0;
}
.hline {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
}
.hline b {
  font-weight: 600;
}
.hnotes {
  margin-top: 3px;
  font-size: 12px;
  opacity: 0.72;
  white-space: pre-wrap;
  line-height: 1.5;
}

/* ---- 云状态一行 ---- */
.opcloud {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 7px;
  padding-top: 7px;
  border-top: 1px dashed rgba(128, 128, 128, 0.2);
}
.opcloud .cl {
  font-size: 11.5px;
  opacity: 0.62;
}
.cell-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 文件页签里「云端载荷」分组的小标题 */
.clabel {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed rgba(128, 128, 128, 0.22);
  font-size: 11.5px;
  opacity: 0.65;
}
/* 下载进度面板 */
.dlbox {
  margin-top: 8px;
  padding: 7px 9px;
  border: 1px solid rgba(128, 128, 128, 0.22);
  border-radius: 6px;
  background: rgba(128, 128, 128, 0.05);
}
.dlbox .dlhead {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
.dlbox .dlname {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dlbox .dlstat {
  margin-top: 3px;
  font-size: 11.5px;
  opacity: 0.65;
  font-variant-numeric: tabular-nums;
}
.opcloud .oplink {
  font-size: 11.5px;
  color: #63a4ff;
  text-decoration: none;
}

/* ---- ④ 操作区：作者行 + 统计格 ---- */
/* 窄栏里把三格压成一行，别让它把操作卡撑高 */
.stats.compact {
  display: flex;
  gap: 0;
  justify-content: flex-start;
  align-items: center;
  margin-top: 7px;
}
.stats.compact .st {
  border: 0;
  padding: 0;
  flex-direction: row;
  align-items: baseline;
  gap: 3px;
}
.stats.compact .st + .st::before {
  content: '·';
  margin: 0 7px 0 4px;
  opacity: 0.45;
}
/* 作者：做成 XMA 那样的作者小卡（圆头像 + 名字 + 类型靠右），别再挤成一团 */
.who {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 9px;
  padding: 6px 9px;
  border: 1px solid rgba(128, 128, 128, 0.22);
  border-radius: 8px;
  background: rgba(128, 128, 128, 0.06);
}
.who .ava {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #6aa9ff, #4c7bd9);
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  line-height: 1;
}
.who .wname {
  flex: 1 1 auto;
  min-width: 0;
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.who .wtag {
  flex: 0 0 auto;
}
.stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  margin-top: 9px;
}
.stats .st {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  padding: 5px 2px;
  border: 1px solid rgba(128, 128, 128, 0.25);
  border-radius: 6px;
}
.stats .st b {
  font-size: 12.5px;
  font-weight: 600;
}
.stats .st span {
  font-size: 10.5px;
  opacity: 0.6;
}
/* 窗口不够宽：展开时两列并排不下 → 退回单列 */
@media (max-width: 1320px) {
  .wrap.det-half .right,
  .wrap.det-full .right {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: 'bar' 'main' 'side';
    overflow: auto;
  }
  .wrap.det-half .opgrid,
  .wrap.det-full .opgrid {
    grid-template-columns: 1fr 1fr;
  }
}

/* 预览卡片：按内容高度（图 + 缩略图条），不会撑出一块空白 */
:deep(.pv-card) {
  flex: 0 0 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
:deep(.pv-card .n-card__content) {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
}
/* 大图下面的缩略图条：把这个 Mod 里的图都列出来，点一张看一张 */
.shots {
  flex: 0 0 auto;
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding-bottom: 2px;
  align-items: center;
}
.shot {
  position: relative;
  width: 78px;
  height: 54px;
  flex: 0 0 auto;
  border-radius: 6px;
  overflow: hidden;
  cursor: pointer;
  border: 2px solid transparent;
  background: rgba(128, 128, 128, 0.08);
}
.shot img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.shot.active {
  border-color: #2f6feb;
}
.shot.current img {
  opacity: 0.72;
}
.shot .delbtn {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 16px;
  height: 16px;
  line-height: 14px;
  padding: 0;
  border: 0;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  color: #fff;
  background: rgba(208, 48, 80, 0.85);
  opacity: 0;
  transition: opacity 0.15s;
}
.shot:hover .delbtn {
  opacity: 1;
}
.shot .tag {
  position: absolute;
  right: 2px;
  bottom: 2px;
  font-size: 10px;
  line-height: 15px;
  padding: 0 4px;
  border-radius: 4px;
  background: rgba(47, 111, 235, 0.9);
  color: #fff;
}
.shot .setbtn {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  border: 0;
  font-size: 10px;
  line-height: 16px;
  padding: 0;
  cursor: pointer;
  color: #fff;
  background: rgba(0, 0, 0, 0.55);
  opacity: 0;
  transition: opacity 0.15s;
}
.shot:hover .setbtn {
  opacity: 1;
}
.shots.kbfocus {
  box-shadow: 0 0 0 2px rgba(47, 111, 235, 0.35);
  border-radius: 8px;
}
.strip-hint {
  font-size: 11px;
  opacity: 0.55;
  padding: 2px 2px 0;
}
.shots .count {
  flex: 0 0 auto;
  font-size: 11px;
  opacity: 0.55;
  padding-left: 2px;
}
/* 预览框：高度跟着图片走（图多大框多高），不再留一大块空 */
.preview {
  flex: 0 0 auto;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  overflow: hidden;
  background: repeating-conic-gradient(rgba(128, 128, 128, 0.06) 0 25%, transparent 0 50%) 0 0/22px 22px;
}
/* 图片：等比铺满可用宽度，最高 46vh，不变形不裁切 */
:deep(.preview .n-image),
:deep(.preview .pv-img) {
  max-width: 100%;
  width: auto;
}
:deep(.preview img) {
  display: block;
  width: auto;
  height: auto;
  max-width: 100%;
  max-height: 30vh;
  object-fit: contain;
}
.ph {
  padding: 24px 10px;
  font-size: 13px;
  opacity: 0.45;
}
/* 说明卡片：按内容高度（不藏内容、不内部滚动），剩下的高度都给预览图 */
:deep(.desc-card) {
  flex: 0 0 auto;
  min-height: 0;
  max-height: none;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
:deep(.desc-card .n-card__content) {
  min-height: 0;
  overflow: auto;
  padding-bottom: 6px;
}
/* 游戏内插件状态条（面板顶部） */
/* 高级搜索面板 */
.advbar {
  flex: 0 0 auto;
  border: 1px solid rgba(128, 128, 128, 0.18);
  border-radius: 8px;
  padding: 8px 10px;
  margin: 0 0 8px;
  background: rgba(128, 128, 128, 0.055);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.advbar .row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.advbar .lbl {
  font-size: 12px;
  opacity: 0.7;
  min-width: 46px;
}
.advbar .tagcloud {
  max-height: 76px;
  overflow: auto;
}
/* 详情里的标签编辑 */
.tagedit {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 2px 0 6px;
}
.tagedit .lbl {
  font-size: 12px;
  opacity: 0.7;
  padding-top: 3px;
  white-space: nowrap;
}
.tagedit :deep(.n-dynamic-tags) {
  flex: 1 1 auto;
  min-width: 0;
}
/* 长取值必须换行显示，不能顶出面板（实测最长 535px，容器只有 296px） */
.tagedit :deep(.n-tag) {
  max-width: 100%;
  height: auto;
  min-height: 22px;
  white-space: normal;
  align-items: flex-start;
  padding-top: 2px;
  padding-bottom: 2px;
}
.tagedit :deep(.n-tag__content) {
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
  line-height: 1.45;
}
.tagedit :deep(.n-tag__close) {
  margin-top: 2px;
}
.bridge-bar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 5px 8px;
  margin-bottom: 8px;
  border-radius: 6px;
  border-left: 3px solid #999;
  background: rgba(128, 128, 128, 0.1);
}
.bridge-bar .txt {
  opacity: 0.75;
}
.bridge-bar .grow {
  flex: 1 1 auto;
}
.bridge-bar .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #999;
  flex: 0 0 auto;
}
.bridge-bar.ok {
  border-left-color: #2ecc71;
}
.bridge-bar.ok .dot {
  background: #2ecc71;
  box-shadow: 0 0 6px rgba(46, 204, 113, 0.7);
}
.bridge-bar.bad {
  border-left-color: #e74c3c;
}
.bridge-bar.bad .dot {
  background: #e74c3c;
}
.bridge-bar.bad .txt {
  opacity: 1;
  color: #e88080;
}
.ellip {
  display: block;
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.addr {
  word-break: break-all;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
/* 空档：把动作按钮顶到面板底部，多余空间留在最下面 */
.pane-spacer {
  flex: 1 1 auto;
  min-height: 8px;
}
/* 操作卡片：主动作两列等宽网格 + 文件类收成一行小字按钮（省高度，不挤） */
.act-card {
  flex: 0 0 auto;
  margin-top: 2px;
}
.act-card :deep(.n-card-header) {
  padding: 8px 12px 4px;
}
.act-card :deep(.n-card__content) {
  padding: 4px 12px 10px;
}
.opgrid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
}
.opgrid :deep(.n-button) {
  justify-content: center;
}
.oplinks {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 3px;
  margin-top: 6px;
}
.oplinks .sep {
  opacity: 0.28;
  font-size: 11px;
}
.opnote {
  margin-top: 4px;
  font-size: 12px;
  opacity: 0.55;
}
/* 动作按钮：固定高度，永远完整可见 */
.secttl {
  font-size: 12px;
  opacity: 0.7;
  margin-bottom: 4px;
}
.pane-actions {
  flex: 0 0 auto;
  padding-bottom: 2px;
}
/* 窄窗口：改成上下单列，并且整块可滚动（否则下面那块会被外层裁掉、够不着） */
@media (max-width: 1100px) {
  .wrap {
    grid-template-columns: 1fr;
    grid-template-rows: auto;
    overflow: auto;
  }
  .left {
    min-height: 58vh;
  }
  .right {
    max-height: none;
    overflow: visible;
  }
  :deep(.preview img) {
    max-height: 34vh;
  }
  :deep(.desc-card) {
    flex: 0 0 auto;
  }
  .table {
    min-height: 40vh;
  }
}
</style>

<style>
.bar.row2 {
  margin-top: 4px;
  padding-top: 4px;
  border-top: 1px dashed rgba(128, 128, 128, 0.25);
}
.oprow {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.advgrid {
  display: grid;
  grid-template-columns: auto minmax(150px, 1fr) auto minmax(150px, 1fr);
  gap: 6px 10px;
  align-items: center;
}
.advgrid .lbl {
  color: #888;
  font-size: 13px;
  white-space: nowrap;
}
.n-data-table .row-installed td {
  background: rgba(60, 200, 120, 0.1) !important;
}
</style>
