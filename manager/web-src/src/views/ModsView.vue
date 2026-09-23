<script setup>
import { ref, computed, h, inject, onMounted, onUnmounted, nextTick, watch } from 'vue'

import {
  NButton, NInput, NSelect, NDataTable, NTag, NCard, NDescriptions, NDescriptionsItem,
  NImage, NModal, NForm, NFormItem, NInputNumber, NSwitch, NRadioGroup, NRadioButton,
  NSpace, NAlert, NEmpty, NTooltip, NDivider, NButtonGroup, NDynamicTags,
  NCheckboxGroup, NCheckbox, useMessage, useDialog,
} from 'naive-ui'
import { api } from '../api'

const props = defineProps({ mods: { type: Array, default: () => [] } })
const emit = defineEmits(['changed'])
const { state, startJob, bus } = inject('mm')
const msg = useMessage()
const dialog = useDialog()

const cur = ref(null)
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
const fixingCover = ref(false)     // 补封面到游戏进行中
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

/** 点表格里的小标签 = 直接按它筛选 */
function toggleTagFilter(t) {
  const s = String(t || '').trim()
  if (!s) return
  advOpen.value = true
  fTagsText.value = fTagsText.value.trim() === s ? '' : s
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
      if (focusArea.value === 'strip') focusArea.value = 'table'
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
    title: '标签', key: 'tags', width: 168,
    render: (r) => {
      const ts = r.tags || []
      if (!ts.length) return h('span', { style: 'opacity:.35' }, '—')
      const kids = []
      for (const t of ts.slice(0, 3)) {
        kids.push(h(NTag, {
          size: 'tiny', bordered: false, type: 'info',
          style: 'margin:1px 2px 1px 0;cursor:pointer',
          onClick: (e) => { e.stopPropagation(); toggleTagFilter(t) },
        }, { default: () => t }))
      }
      if (ts.length > 3) kids.push(h('span', { style: 'opacity:.5;font-size:11px' }, `+${ts.length - 3}`))
      return h(NTooltip, null, {
        trigger: () => h('div', null, kids),
        default: () => ts.join('、'),
      })
    },
  },
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
  { title: 'Mod 名称', key: 'name', minWidth: 260, ellipsis: { tooltip: true }, resizable: true },
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
  const list = (rows && rows.length ? rows : cur.value ? [cur.value] : [])
  if (!list.length) return msg.warning('先选要删的 Mod')
  dialog.warning({
    title: '删除 Mod',
    content: `要把这 ${list.length} 个 Mod 移入回收站吗？\n${list.slice(0, 6).map((m) => '· ' + m.name).join('\n')}` +
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
          bad.push(`${m.name}：${e.message}`)
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

async function fixCoverToGame() {
  if (!cur.value) return
  fixingCover.value = true
  try {
    const r = await api.bridgeFixCover(cur.value.folder)
    if (r.ok) {
      const w = r.written || 0
      const s = r.skipped || 0
      msg.success(
        `封面已补进游戏（写入 ${w} 条${s ? `，本来就有跳过 ${s} 条` : ''}）：${r.mod}` +
        ' —— 去 Penumbra 那条 mod 的面板看看（不用重启游戏）',
      )
    } else {
      msg.error(r.error || '补封面失败')
    }
    return r
  } catch (e) {
    msg.error(e.message)
  } finally {
    fixingCover.value = false
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
  <div class="wrap">
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
        <n-button size="small" :type="advOpen ? 'primary' : 'default'" @click="advOpen = !advOpen">
          筛选{{ advCount ? `（${advCount}）` : '' }}
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
      <div v-if="advOpen" class="advbar">
        <div class="advgrid">
          <span class="lbl">名称</span>
          <n-input v-model:value="fName" size="small" clearable placeholder="名称包含…" />
          <span class="lbl">作者</span>
          <n-input v-model:value="fAuthor" size="small" clearable placeholder="作者包含…" />
          <span class="lbl">影响/替换</span>
          <n-input v-model:value="fAffectsText" size="small" clearable placeholder="它替换的对象包含…" />
          <span class="lbl">标签</span>
          <n-input v-model:value="fTagsText" size="small" clearable placeholder="标签包含…" />
          <span class="lbl">分类</span>
          <n-select v-model:value="fCats" :options="catOptions" multiple filterable clearable
                    size="small" placeholder="可多选" />
          <span class="lbl">安装状态</span>
          <n-select v-model:value="fInst" :options="instOptions" size="small" clearable
                    placeholder="全部" />
          <span class="lbl">标签有无</span>
          <n-select v-model:value="fTagState" :options="tagStateOptions" size="small" clearable
                    placeholder="全部" />
          <span class="lbl">预览图</span>
          <n-select v-model:value="fImg" :options="imgOptions" size="small" clearable
                    placeholder="全部" />
          <span class="lbl">排序</span>
          <n-select v-model:value="sortBy" :options="sortOptions" size="small" />
          <span class="lbl">方向</span>
          <n-select v-model:value="sortDir" :options="sortDirOptions" size="small" />
        </div>
        <div class="row">
          <n-button size="small" @click="clearAdv">清空条件</n-button>
          <span class="dim">当前显示 {{ view.length }} / {{ mods.length }} 条</span>
          <div class="grow"></div>
          <span class="dim">提示：点表格里的小标签，可以快速按它筛选</span>
        </div>
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
              <b>{{ m.seq }}. {{ m.name }}</b>
              <span class="dim">{{ m.author || '—' }} · {{ m.category }}{{ m.subcat ? ' / ' + m.subcat : '' }}</span>
            </div>
          </div>
        </div>
        <n-data-table
          v-else-if="mods.length"
          :columns="columns" :data="view" :row-class-name="rowClassName" :row-props="rowProps"
          :row-key="(r) => r.folder" :checked-row-keys="checked"
          @update:checked-row-keys="(k) => (checked = k)"
          :max-height="'100%'" :scroll-x="1390" size="small" striped flex-height
        />
        <n-empty v-else style="margin: auto" description="还没有索引数据，点右上角「重新扫描」" />
      </div>
    </div>

    <aside class="right">
      <!-- 游戏内插件状态：放最上面，一眼能看到 -->
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

      <n-card size="small" :title="cur ? cur.name : '预览'" class="pv-card">
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

      <n-card size="small" class="desc-card">
        <n-descriptions :column="2" label-placement="left" size="small" label-width="52"
                        style="margin-bottom: 2px">
          <n-descriptions-item label="分类">{{ cur?.category || '—' }}</n-descriptions-item>
          <n-descriptions-item label="序号">{{ cur?.seq ?? '—' }}</n-descriptions-item>
          <n-descriptions-item label="子分类">{{ cur?.subcat || '—' }}</n-descriptions-item>
        <n-descriptions-item label="更新时间" :span="2">
          {{ cur?.site_latest || cur?.site_updated || '—' }}
          <n-tag v-if="cur?.update_avail" size="tiny" type="warning" :bordered="false"
                 style="margin-left:6px;cursor:pointer" @click="onlyUpd = true">有新版</n-tag>
          <span v-if="cur?.site_version" class="dim">｜ 站点版本 v{{ cur.site_version }}</span>
          <span v-if="cur?.site_updated && cur?.site_latest && cur.site_updated !== cur.site_latest"
                class="dim">｜ 本地这份下载于 {{ cur.site_updated }}</span>
        </n-descriptions-item>
          <n-descriptions-item label="作者">{{ cur?.author || '—' }}</n-descriptions-item>
          <n-descriptions-item label="类型" :span="2">{{ cur?.nsfw || '—' }}</n-descriptions-item>
        </n-descriptions>
        <div class="tagedit">
          <span class="lbl">标签</span>
          <n-dynamic-tags :value="(cur && cur.tags) || []" size="small"
                          :disabled="!cur" @update:value="saveTags" />
        </div>
        <div class="tagedit">
          <span class="lbl" title="从站点重新下载最新版覆盖，或自己上传新文件替换">更新</span>
          <n-button size="tiny" :disabled="!cur || !cur.addr" @click="updateOne(cur)">
            {{ isHelio(cur) ? '打开页面下载' : '从站点更新' }}
          </n-button>
          <n-button size="tiny" :disabled="!cur" @click="openReplace">上传新文件替换…</n-button>
          <span v-if="cur && !cur.addr" class="dim">（没有站点地址，只能手动替换）</span>
        </div>
        <div class="tagedit">
          <span class="lbl" title="这条 Mod 替换/影响游戏里的哪些东西（来自 XMA 的 Affects / Replaces）">
            影响/替换
          </span>
          <n-dynamic-tags :value="splitList(cur && cur.affects)" size="small"
                          :disabled="!cur" @update:value="saveAffectsList" />
        </div>
        <n-descriptions :column="1" label-placement="left" size="small" label-width="56">
          <n-descriptions-item label="地址">
            <a v-if="cur?.addr" class="addr" :href="cur.addr" target="_blank"
               rel="noreferrer">{{ cur.addr }}</a>
            <span v-else>—</span>
          </n-descriptions-item>
          <n-descriptions-item label="预览图">
            <span class="ellip" :title="cur?.img_name || ''">{{ cur?.img_name || '—' }}</span>
          </n-descriptions-item>
          <n-descriptions-item label="文件夹">
            <span class="ellip" :title="cur?.folder || ''" style="cursor: pointer"
                  @click="copyPath">{{ cur?.rel || cur?.folder || '—' }}</span>
          </n-descriptions-item>
        </n-descriptions>
      </n-card>

      <div class="pane-spacer"></div>

      <n-card size="small" title="操作" class="act-card">
        <n-space size="small" class="pane-actions">
        <n-button size="small" :disabled="!cur" @click="api.open('folder', cur.folder)">
          打开文件夹
        </n-button>
        <n-button size="small" :disabled="!cur" @click="copyPath">复制路径</n-button>
        <n-button size="small" type="primary" :disabled="!cur" :loading="installing"
                  @click="installToGame(false)">
          安装到游戏
        </n-button>
        <n-button size="small" :disabled="!cur" :loading="fixingCover" @click="fixCoverToGame">
          补封面到游戏
        </n-button>
        <n-button v-if="cur?.has_img" size="small" tag="a" :href="api.raw(cur.folder)"
                  target="_blank">查看原图</n-button>
        </n-space>
      </n-card>
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
  grid-template-columns: 1fr 380px;
  grid-template-rows: minmax(0, 1fr);
  gap: 14px;
  padding: 14px 18px 18px;
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
.right {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  /* 实在放不下时滚动，绝不把内容裁掉 */
  overflow: auto;
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
  max-height: 46vh;
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
/* 操作卡片：按钮换行排布，窄面板也不挤 */
.act-card {
  flex: 0 0 auto;
  margin-top: 8px;
}
.act-card :deep(.n-card__content) {
  padding: 10px 12px 12px;
}
.act-card :deep(.n-space) {
  flex-wrap: wrap;
  row-gap: 6px;
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
.advbar .advgrid {
  display: grid;
  grid-template-columns: auto minmax(150px, 1fr) auto minmax(150px, 1fr);
  gap: 6px 10px;
  align-items: center;
}
.n-data-table .row-installed td {
  background: rgba(60, 200, 120, 0.1) !important;
}
</style>
