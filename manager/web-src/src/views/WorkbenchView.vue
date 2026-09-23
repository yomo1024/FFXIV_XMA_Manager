<script setup>
import { ref, computed, inject, onMounted, onUnmounted } from 'vue'
import {
  NButton, NCard, NSpace, NAlert, NTag, NSelect, NInput, NInputNumber, NDataTable,
  NEmpty, NSpin, NSwitch, NCollapse, NCollapseItem, NImage, NCheckbox, useMessage,
} from 'naive-ui'
import { api } from '../api'

const props = defineProps({ mods: { type: Array, default: () => [] } })
const emit = defineEmits(['changed'])
const { startJob, bus } = inject('mm')
const msg = useMessage()

const info = ref(null)
const busy = ref(false)
const pending = ref([])
const cats = ref([])
const checked = ref([])
const target = ref({ category: '', zone: 'SFW', move: true })

// ---------- ① 粘贴链接 → 一键下载入库 ----------
const urlInput = ref('')
const parsing = ref(false)
const parsed = ref(null)          // 解析出来的页面信息
const autoOpen = ref(false)       // 需要时自动打开内置浏览器（默认关闭）
const advSecs = ref(600)

// ---------- 内置浏览器的登录状态（NSFW 的 Mod 必须登录才看得到下载） ----------
const login = ref({ running: false, logged: false, count: 0, names: [] })
const syncing = ref(false)
const browserName = computed(() => {
  const e = (info.value && info.value.exe) || ''
  const n = e.split(/[\\/]/).pop() || ''
  return n ? n.replace(/\.exe$/i, '') : '你的浏览器'
})
async function loadLogin() {
  try { login.value = (await api.browserLoginState()).login || {} } catch (e) { /* 忽略 */ }
}
async function syncLogin() {
  syncing.value = true
  try {
    const r = await api.browserSyncLogin()
    login.value = (r && r.login) || {}
    const n = (r && r.synced && r.synced.files) || 0
    if (login.value.logged) {
      msg.success(`已同步 ${n} 个 Cookie 文件 —— 内置浏览器现在是「已登录」状态 ✓`)
    } else {
      msg.warning(`复制了 ${n} 个 Cookie 文件，但没检测到站点的登录 Cookie。` +
        `可以直接在内置浏览器里登录一次 XIVModArchive（一次就够）。`, { duration: 12000 })
    }
  } catch (e) {
    msg.warning(e.message, { duration: 15000 })
  } finally {
    syncing.value = false
  }
}

// ---------- 用「你自己的浏览器」读取 ----------
const inboxPage = ref(null)
const inboxAt = ref(0)

// 注意：Vue 模板里访问不到 location 等浏览器全局对象，必须在这里取好再用
const port = (typeof location !== 'undefined' && location.port) || '8765'

const bookmarklet = computed(() => {
  const code = '(function(){'
    + 'var d=document;'
    + "var dl=d.querySelector('#mod-download-link')||[].slice.call(d.querySelectorAll('a'))"
    + ".filter(function(e){return (e.getAttribute('href')||'').indexOf('/files/')>-1})[0];"
    + 'var img=d.querySelector(\'img[src*="/mod-images/"]\');'
    + "var au='';[].slice.call(d.querySelectorAll('a')).forEach(function(e){"
    + "if(!au&&(e.getAttribute('href')||'').indexOf('/user/')===0){au=e.innerText.trim()}});"
    + 'var h=d.querySelector("h1");'
    + "var m=(location.href.split('/modid/')[1]||'').split(/[\\/?#]/)[0];"
    + "var g=[];[].slice.call(d.querySelectorAll('img')).forEach(function(e){"
    + "var s=e.src||e.getAttribute('data-src')||e.getAttribute('data-original')||'';"
    + "if(s.indexOf('/mod-images/')>-1&&g.indexOf(s)<0){g.push(s)}});"
    + "if(img&&img.src&&g.indexOf(img.src)<0){g.unshift(img.src)}"
    + "var dh=dl?(dl.getAttribute('href')||''):'';if(dh){try{dh=new URL(dh,location.href).href}catch(e){}}"
    + "var tg=[];[].slice.call(d.querySelectorAll('.mod-meta-block,div,p,li')).forEach(function(e){"
    + "if(tg.length||e.children.length>3)return;var t=(e.innerText||'').trim();"
    + "var mx=t.match(/^Tags\\s*:\\s*([\\s\\S]*)$/i);"
    + "if(mx){mx[1].split(',').forEach(function(x){x=x.trim();if(x&&tg.indexOf(x)<0)tg.push(x)})}});"
    // 「影响/替换」= 站点上的 Affects / Replaces 一栏（这条 mod 替换游戏里的哪件装备/哪个部位）
    + "var af='';[].slice.call(d.querySelectorAll('.mod-meta-block,div,p,li')).forEach(function(e){"
    + "if(af||e.children.length>3)return;var t2=(e.innerText||'').trim();"
    + "var low=t2.toLowerCase();var i=low.indexOf('affects / replaces');"
    + "if(i===0){var j=t2.indexOf(':');if(j>0)af=t2.slice(j+1).trim()}});"
    + 'var o={v:5,url:location.href,modid:m,name:h?h.innerText.trim():document.title,author:au,imgs:g,tags:tg,affects:af,'
    + "cover:img?img.src:'',dl:dh,title:document.title};"
    + "fetch('http://127.0.0.1:" + port + "/api/inbox/page',{method:'POST',mode:'no-cors',"
    + "headers:{'Content-Type':'text/plain'},body:JSON.stringify(o)});"
    + "alert('已发送给 FFXIV Mod 管理器：'+(o.name||o.title)+'（含 '+g.length+' 张画廊图）');"
    + '})()'
  return 'javascript:' + code
})

function extractUrl(t) {
  const m = (t || '').match(/https?:\/\/\S+|\b\d{4,8}\b/)
  return m ? m[0].replace(/[)"'，。]+$/, '') : ''
}

async function fromClipboard() {
  try {
    const t = await navigator.clipboard.readText()
    const u = extractUrl(t)
    if (!u) return msg.warning('剪贴板里没找到 Mod 链接或编号')
    urlInput.value = u
    msg.info('从剪贴板拿到：' + u)
    parse()
  } catch (e) {
    msg.error('读剪贴板失败（浏览器可能要求授权，或者你先按一次 Ctrl+C）：' + e.message)
  }
}

function useInbox() {
  if (!inboxPage.value) return msg.warning('还没有从浏览器收到页面信息')
  applyParsed(inboxPage.value)
  msg.success('已使用浏览器送来的信息')
}

async function readInboxOnce(manual = false) {
  // 只读一次：不轮询
  try {
    const r = await api.inboxPage()
    if (r.page && r.page.old_bookmarklet) {
      msg.warning('你用的书签小工具是旧版（不会带画廊图片），请重新拖一次', { duration: 10000 })
    }
    if (r.page && r.at && r.at > inboxAt.value) {
      inboxAt.value = r.at
      inboxPage.value = r.page
      applyParsed(r.page)
      msg.success('已从你的浏览器收到：' + (r.page.name || r.page.title || '（没读到名称）'))
    } else if (manual) {
      msg.info(inboxPage.value ? '没有新内容（还是上一次那条）' : '还没有从浏览器收到页面')
    }
  } catch (e) {
    if (manual) msg.error('读取失败：' + e.message)
  }
}

// 切回这个标签页时读一次（够用了，不用后台一直轮询）
function onFocus() {
  readInboxOnce()
}
const parseErr = ref('')
const parseWarn = ref('')
const form = ref({ category: '', zone: 'SFW', subcat: '', author: '', name: '', seq: null,
                   affects: '', affectsFromPage: '', cover: true, export: true })

// 封面走后端代理（后端会先直连、再借内置浏览器 cookie）
const coverSrc = (u, w = 400, bust = 0) =>
  '/api/fetch/cover?u=' + encodeURIComponent(u) + '&w=' + w + (bust ? '&t=' + bust : '')

// 封面加载失败：别静默白框，给原因 + 重试
const coverErr = ref(false)
const coverTry = ref(0)
function onCoverErr() {
  coverErr.value = true
  msg.warning('封面没显示出来（多半是站点挡了外链）。点「重试封面」；还不行就先'
    + '「打开内置浏览器」打开这条 Mod 的页面，再点重试。', { duration: 12000 })
}
function retryCover() {
  coverErr.value = false
  coverTry.value = Date.now()
}

const catOptions = computed(() =>
  (cats.value || []).map((c) => ({ label: `${c.name}（${c.count}）`, value: c.name })),
)
const modOptions = computed(() =>
  (props.mods || []).map((m) => ({
    label: `${m.category} / ${m.seq}. ${m.name}${m.author ? ' — ' + m.author : ''}`,
    value: m.folder,
  })),
)
const browserOptions = computed(() =>
  (info.value?.browsers || []).map((b) => ({ label: b.name, value: b.path })),
)

async function toggleAutoOpen(v) {
  autoOpen.value = !!v
  try {
    await api.saveSettings({ auto_open_browser: autoOpen.value })
    msg.success(autoOpen.value
      ? '已开启：需要时（过 Cloudflare / 现抓画廊）才会自动开内置浏览器'
      : '已关闭：解析链接、抓封面、下载都不会再自动开内置浏览器')
  } catch (e) {
    msg.error(e.message)
  }
}

async function load() {
  busy.value = true
  try {
    try {
      autoOpen.value = !!(await api.settings()).auto_open_browser
    } catch (e0) { /* 忽略 */ }
    info.value = await api.browser()
    loadLogin()
    pending.value = (await api.pending()).items || []
    cats.value = (await api.categories()).cats
    if (!form.value.category && cats.value.length) form.value.category = cats.value[0].name
  } catch (e) {
    msg.error(e.message)
  } finally {
    busy.value = false
  }
}
bus.refresh = load
onMounted(async () => {
  await load()
  readInboxOnce()
  window.addEventListener('focus', onFocus)
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) readInboxOnce()
  })
  // ?url=... 可以直接带链接进来并自动解析（方便收藏/分享）
  const u = new URLSearchParams(location.search).get('url')
  if (u) {
    urlInput.value = u
    parse()
  }
})

function applyParsed(page) {
  parsed.value = page
  parseErr.value = ''
  form.value.name = page.name || ''
  form.value.author = page.author || ''
  // 站点上的「Affects / Replaces」：自动填进来，主人仍可改
  form.value.affectsFromPage = String(page.affects || '').trim()
  form.value.affects = form.value.affectsFromPage
}

async function parse() {
  const u = urlInput.value.trim()
  if (!u) return msg.warning('先把 Mod 链接粘进来（也可以只填编号，例如 12345）')
  parsing.value = true
  parseErr.value = ''
  try {
    const r = await api.fetchParse({ url: u })
    if (r.error) {
      parseErr.value = r.error
      parsed.value = r.page && r.page.is_mod ? r.page : null
      if (r.page && r.page.is_mod) applyParsed(r.page)
      else if (r.partial) {
        // 站点不支持自动下载，但读到了名称/作者 —— 填进表单，方便走手动添加
        if (r.partial.name) form.value.name = r.partial.name
        if (r.partial.author) form.value.author = r.partial.author
      }
    } else {
      applyParsed(r.page)
      if (!r.has_download) {
        parseWarn.value = r.warn || '这个页面没找到下载链接'
        msg.warning(r.warn || '这个页面没找到下载链接', { duration: 15000 })
      } else {
        parseWarn.value = ''
        msg.success('解析成功：' + (r.page.name || r.page.title || ''))
      }
      // 分类/类型留空时给个默认
      if (!form.value.category && cats.value.length) form.value.category = cats.value[0].name
    }
  } catch (e) {
    parseErr.value = e.message
  } finally {
    parsing.value = false
  }
}

async function readCurrentPage() {
  try {
    const r = await api.browserCapture()
    if (r.page?.is_mod) {
      applyParsed(r.page)
      msg.success('已读取内置浏览器当前页面')
    } else {
      parseErr.value = r.page?.challenge
        ? '当前页面还在人机验证'
        : '当前页面不是 Mod 详情页'
    }
  } catch (e) {
    msg.error(e.message)
  }
}

function downloadWithMyBrowser() {
  // 全程只用你自己的那个浏览器：让"你的浏览器"用你的登录态下载，
  // 管理器只在下载目录等文件，出现后自动入库（不需要第二个浏览器）
  const p = parsed.value || inboxPage.value || null
  const dl = (p && p.dl) || ''
  if (!dl) {
    return msg.warning('还没拿到下载直链。最简单的做法：在你自己的浏览器里打开这条 Mod 页面，' +
      '点一下书签栏里的「发送到 Mod 管理器」，信息（含直链）会送到这里，然后再点这个按钮。',
      { duration: 20000 })
  }
  // 兜底：万一 dl 还是相对路径，用"Mod 页面地址"当基准补全（绝不能用管理器自己的地址 ✗）
  let dlu = dl
  try { dlu = new URL(dl, p.addr || p.url || 'https://www.xivmodarchive.com/').href } catch (e) { }
  window.open(dlu, '_blank')         // 你的浏览器下载（带着你的登录态）
  startJob('selfdownload', {
    page: Object.assign({}, p, { dl: dlu }),
    name: (p.name || form.value.name || ''),
    author: (p.author || form.value.author || ''),
    addr: (p.addr || p.url || ''),
    cover_url: (p.cover || ''),
    dir: (info.value && info.value.self_download_dir) || '',
    category: form.value.category || '',
    zone: form.value.zone || 'SFW',
    subdir: form.value.subcat || '',
    affects: form.value.affects || '',
    seconds: 900, export: form.value.export,
  })
  msg.info('已让「你自己的浏览器」开始下载；下完我会自动入库到「' +
    (form.value.category || '待导入（没选分类就先放待导入）') + '」—— 看上面的任务进度条。',
    { duration: 12000 })
}

function doFetch() {
  const u = parsed.value?.addr || urlInput.value.trim()
  if (!u) return msg.warning('先解析一个 Mod 链接')
  if (!form.value.category) return msg.warning('选一下导入到哪个分类')
  if (!parsed.value?.dl) {
    return msg.warning(parsed.value?.warn || parseWarn.value ||
      '这个页面没找到下载链接（可能要登录，或作者没上传文件）—— ' +
      '可以在内置浏览器里手动点下载，然后用「监视下载目录」', { duration: 15000 })
  }
  startJob('fetch', {
    url: u, category: form.value.category, zone: form.value.zone,
    subdir: form.value.subcat, author: form.value.author, name: form.value.name,
    seq: form.value.seq, affects: form.value.affects || '',
    cover: form.value.cover, export: form.value.export,
  })
}

onUnmounted(() => window.removeEventListener('focus', onFocus))

// ---------- ③ 手动流程 ----------
async function openBrowser(url) {
  busy.value = true
  try {
    const r = await api.browserOpen(url)
    msg.success('浏览器已就绪（调试端口 ' + r.port + '）')
    await load()
  } catch (e) {
    msg.error(e.message)
  } finally {
    busy.value = false
  }
}
async function closeBrowser() {
  busy.value = true
  try {
    await api.browserClose()
    msg.success('已关闭内置浏览器')
    await load()
  } catch (e) {
    msg.error(e.message)
  } finally {
    busy.value = false
  }
}
async function saveBrowserPath(v) {
  try {
    await api.saveSettings({ browser_path: v })
    msg.success('内置浏览器已切换')
    await load()
  } catch (e) {
    msg.error(e.message)
  }
}
function useAsNewMod() {
  const p = parsed.value || info.value?.page || {}
  if (!p.addr) return msg.warning('当前页面不是 Mod 详情页')
  bus.prefillAdd = { addr: p.addr, name: p.name || p.title || '', author: p.author || '',
                     affects: String(p.affects || form.value.affects || '') }
  msg.info('已带到「添加 Mod」里，去 Mod 列表确认一下')
}
function doImport() {
  if (!checked.value.length) return msg.warning('先勾要导入的文件')
  if (!target.value.category) return msg.warning('先选个分类')
  startJob('import', { files: checked.value, category: target.value.category,
                       zone: target.value.zone, move: target.value.move })
  checked.value = []
}

const pendColumns = [
  { type: 'selection' },
  { title: '文件', key: 'file', ellipsis: { tooltip: true } },
  { title: '来源', key: 'where', width: 66 },
  { title: '大小', key: 'size_h', width: 86 },
  { title: '时间', key: 'mtime_h', width: 100 },
  { title: '推测名称', key: 'name', ellipsis: { tooltip: true } },
]
</script>

<template>
  <div class="pane">
    <n-spin :show="busy">
      <!-- ① 主流程 -->
      <n-card size="small" title="① 粘贴链接 → 一键下载入库">
        <template #header-extra>
          <n-space>
            <n-button size="small" :disabled="!info?.running" @click="readCurrentPage">
              读内置浏览器当前页
            </n-button>
            <n-button size="small" quaternary @click="openBrowser('')">打开内置浏览器</n-button>
          </n-space>
        </template>

        <n-space vertical size="small">
          <n-input v-model:value="urlInput" placeholder="把 Mod 链接粘进来（也支持只填编号，例如 12345）"
                   @keyup.enter="parse" />
          <n-space align="center" wrap>
            <n-button size="small" type="primary" :loading="parsing" @click="parse">
              解析链接
            </n-button>
            <n-button size="small" type="warning" secondary
                      :disabled="!(parsed?.dl || inboxPage?.dl)"
                      @click="downloadWithMyBrowser">
              ⬇ 用我自己的浏览器下载 → 自动入库
            </n-button>
            <n-button size="small" @click="fromClipboard">从剪贴板读链接</n-button>
            <n-button size="small" @click="readInboxOnce(true)">读一次</n-button>
            <n-button size="small" :disabled="!inboxPage" @click="useInbox">
              用浏览器送来的信息
            </n-button>
            <n-tag v-if="inboxPage" type="success" size="small" :bordered="false">
              浏览器送来：{{ inboxPage.name || inboxPage.title }}
            </n-tag>
            <n-switch v-model:value="autoOpen" size="small" @update:value="toggleAutoOpen" />
            <span class="dim">需要时自动打开内置浏览器{{ autoOpen ? '（已开）' : '（关着）' }}</span>
          </n-space>

          <div class="dim" v-if="info?.self_download_dir">
            这个按钮不会另开浏览器：它让你的浏览器下载（文件存到 {{ info.self_download_dir }}，由你浏览器里设置的下载目录决定），
            管理器只负责在下完那一刻自动接住并入库。
          </div>

          <n-space align="center" wrap>
            <n-tag :type="login.logged ? 'success' : 'default'" size="small" :bordered="false">
              内置浏览器{{ login.logged ? '已登录' : '未登录（可选）' }}{{ login.count ? '（' + login.count + ' 条站点 Cookie）' : '' }}
            </n-tag>
            <n-button size="small" :loading="syncing" @click="syncLogin">同步登录状态</n-button>
            <span class="dim">
              （内置浏览器是<strong>可选</strong>的：用上面的「⬇ 用我自己的浏览器下载」完全不需要它 ——
              你自己的浏览器已经登录，NSFW 也能下。只有想让它自动点「解析链接」时才需要在这里登录）
            </span>
          </n-space>

          <n-collapse>
            <n-collapse-item title="不想开内置浏览器？用你自己的浏览器读取（拖一个书签到书签栏）">
              <div class="dim" style="margin-bottom: 6px">
                把下面这个链接拖到浏览器书签栏，然后在任意 xivmodarchive 的 Mod 页面点一下它：
                页面上的 名称 / 作者 / 封面 / 下载直链 就会自动送进这里（解析不用内置浏览器）。注意：真正下载文件时仍需要内置浏览器处于登录状态 —— 点上面的「同步登录状态」即可。
              </div>
              <n-space align="center" style="margin-bottom: 8px">
                <a class="bm" :href="bookmarklet" @click.prevent="msg.info('把这个链接拖到书签栏，然后在 Mod 页面点它')">
                  🔗 发送到 Mod 管理器
                </a>
                <span class="dim">（拖动它，或右键复制链接地址）</span>
              </n-space>
              <n-input :value="bookmarklet" type="textarea" readonly :rows="3" size="small" />
              <div class="dim" style="margin-top: 6px">
                读取时机：打开这一页读一次、切回这个标签页读一次，也可以随时点上面的「读一次」——
                不会在后台一直轮询。<br />
                小提示：书签里写死了当前地址 <b>http://127.0.0.1:{{ port }}</b>，
                换端口的话要重新拖一次。
              </div>
            </n-collapse-item>
          </n-collapse>

          <n-alert v-if="parseErr" type="warning" :show-icon="false">{{ parseErr }}</n-alert>

          <template v-if="parsed">
            <div class="found">
              <div class="coverwrap">
                <img v-if="parsed.cover && !coverErr" class="coverimg"
                     :src="coverSrc(parsed.cover, 400, coverTry)" alt="" @error="onCoverErr" />
                <div v-else class="coverph">
                  <span v-if="parsed.cover">封面没显示出来</span>
                  <span v-else>这条页面没读到封面</span>
                  <n-button v-if="parsed.cover" size="tiny" @click="retryCover">重试封面</n-button>
                </div>
              </div>
              <div class="found-text">
                <div class="big">{{ parsed.name || parsed.title || '(没读到名称)' }}</div>
                <div class="dim">
                  作者：{{ parsed.author || '—' }} ｜ modid：{{ parsed.modid || '—' }}
                </div>
                <div class="dim">
                  下载链接：<b :style="parsed.dl ? 'color:#18a058' : 'color:#d03050'">
                    {{ parsed.dl ? '找到了' : '页面上没有（可能要登录）' }}
                  </b>
                </div>
                <div class="dim">影响/替换：<b>{{ form.affects || '（页面没写，可自己填）' }}</b>
              <span v-if="form.affectsFromPage && form.affects === form.affectsFromPage"
                    style="opacity:.6">（自动读到）</span>
            </div>
            <div class="dim addr">{{ parsed.addr }}</div>
              </div>
            </div>

            <div class="formrow">
              <n-select v-model:value="form.category" :options="catOptions" size="small"
                        placeholder="导入到哪个分类" style="width: 180px" />
              <n-select v-model:value="form.zone" size="small" style="width: 100px"
                        :options="[{ label: 'SFW', value: 'SFW' }, { label: 'NSFW', value: 'NSFW' }]" />
              <n-input v-model:value="form.subcat" size="small" placeholder="子分类（可空）"
                       style="width: 130px" />
              <n-input v-model:value="form.author" size="small" placeholder="作者"
                       style="width: 120px" />
              <n-input v-model:value="form.name" size="small" placeholder="Mod 名称"
                       style="width: 200px" />
              <n-input-number v-model:value="form.seq" size="small" :min="1" placeholder="序号"
                              style="width: 110px" />
            </div>
            <div class="formrow">
              <n-input v-model:value="form.affects" size="small"
                       placeholder="影响/替换：它替换游戏里的什么（自动从页面读，可改）"
                       style="width: 420px" />
              <n-button v-if="form.affectsFromPage" size="tiny" quaternary
                        @click="form.affects = form.affectsFromPage">用页面读到的值</n-button>
            </div>

            <n-space align="center">
              <n-checkbox v-model:checked="form.cover">抓封面当预览图</n-checkbox>
              <n-checkbox v-model:checked="form.export">完事重新生成 Excel</n-checkbox>
              <n-button size="small" type="primary" :disabled="!parsed.dl" @click="doFetch">
                下载并入库
              </n-button>
              <n-button size="small" quaternary @click="useAsNewMod">只用这个地址去手动添加</n-button>
            </n-space>
          </template>
        </n-space>
      </n-card>

      <!-- ② 待导入 -->
      <n-card size="small" title="② 待导入（下载目录 / 暂存目录里的 Mod 文件）"
              style="margin-top: 12px">
        <template #header-extra>
          <n-space>
            <n-button size="small" @click="api.open('downloads')">打开下载目录</n-button>
            <n-button size="small" @click="api.open('inbox')">打开暂存目录</n-button>
            <n-button size="small" @click="load">刷新</n-button>
          </n-space>
        </template>
        <n-empty v-if="!pending.length" description="没有待导入的文件" />
        <template v-else>
          <n-space align="center" style="margin-bottom: 10px">
            <n-select v-model:value="target.category" :options="catOptions" size="small"
                      placeholder="导入到哪个分类" style="width: 200px" />
            <n-select v-model:value="target.zone" size="small" style="width: 110px"
                      :options="[{ label: 'SFW', value: 'SFW' }, { label: 'NSFW', value: 'NSFW' }]" />
            <n-switch v-model:value="target.move" size="small" />
            <span class="dim">{{ target.move ? '移动' : '复制' }}</span>
            <n-button size="small" @click="checked = pending.map((p) => p.src)">全选</n-button>
            <n-button size="small" type="primary" @click="doImport">
              导入选中（{{ checked.length }}）
            </n-button>
          </n-space>
          <n-data-table :columns="pendColumns" :data="pending" size="small" :scroll-x="900"
                        :row-key="(r) => r.src" :checked-row-keys="checked"
                        @update:checked-row-keys="(k) => (checked = k)" :max-height="300" />
        </template>
      </n-card>

      <!-- ③ 手动/进阶 -->
      <n-collapse style="margin-top: 12px">
        <n-collapse-item title="③ 手动流程 / 进阶（内置浏览器、监视下载）" name="adv">
          <n-alert :type="info?.running ? 'success' : 'warning'" :show-icon="false">
            <template v-if="info?.running">
              内置浏览器正在运行 ｜ 调试端口 {{ info.port }} ｜ {{ info.exe }}
            </template>
            <template v-else>
              没在运行。它会用独立配置目录开一个窗口（不碰你平时用的浏览器），
              打开的页面工具能直接读，用来绕过 Cloudflare。
            </template>
          </n-alert>
          <n-space align="center" style="margin: 10px 0">
            <span class="dim">用哪个浏览器</span>
            <n-select :options="browserOptions" :value="info?.exe" size="small" style="width: 240px"
                      @update:value="saveBrowserPath" />
            <n-button size="small" type="error" quaternary :disabled="!info?.running"
                      @click="closeBrowser">关闭浏览器</n-button>
          </n-space>
          <n-space align="center">
            <n-button size="small" :disabled="!info?.running"
                      @click="startJob('download', {})">从当前页面下载</n-button>
            <n-input-number v-model:value="advSecs" :min="10" :max="7200" :step="60" size="small"
                            style="width: 130px" />
            <span class="dim">秒</span>
            <n-button size="small" @click="startJob('watch', { seconds: advSecs })">
              监视下载目录
            </n-button>
            <span class="dim">（你自己在浏览器里下载也行，下完会被搬进暂存目录）</span>
          </n-space>
          <div class="dim" style="margin-top: 8px">
            下载目录：{{ info?.download_dir || '—' }}<br />暂存目录：{{ info?.inbox_dir || '—' }}
          </div>
        </n-collapse-item>
      </n-collapse>
    </n-spin>
  </div>
</template>

<style scoped>
.pane {
  height: 100%;
  overflow: auto;
  padding: 16px 18px 24px;
}
.dim {
  font-size: 12px;
  opacity: 0.65;
}
.found {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 10px;
  border-radius: 8px;
  background: rgba(128, 128, 128, 0.06);
}
.cover {
  flex: 0 0 auto;
  border-radius: 6px;
  overflow: hidden;
}
.coverwrap {
  flex: 0 0 auto;
  width: 132px;
  min-height: 96px;
  border-radius: 6px;
  overflow: hidden;
  background: rgba(128, 128, 128, 0.12);
  display: flex;
  align-items: center;
  justify-content: center;
}
.coverimg {
  width: 132px;
  display: block;
  border-radius: 6px;
}
.coverph {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  opacity: 0.7;
  padding: 10px 6px;
  text-align: center;
}
.found-text {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.found-text .big {
  font-size: 15px;
  font-weight: 600;
}
.addr {
  word-break: break-all;
}
.bm {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 8px;
  border: 1px solid #2f6feb;
  color: #2f6feb;
  text-decoration: none;
  cursor: grab;
  font-size: 13px;
}
.bm:hover {
  background: rgba(47, 111, 235, 0.08);
}
.formrow {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
</style>
