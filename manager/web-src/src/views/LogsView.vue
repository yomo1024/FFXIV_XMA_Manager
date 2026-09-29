<script setup>
// 运行日志页：把程序目录里的日志在一个地方看（不用去翻文件夹）
// 主人 2026-09：「我需要一个地方页面看日志」
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { NButton, NInput, NSelect, NSwitch, NIcon, useMessage } from 'naive-ui'
import { RefreshOutline, FolderOpenOutline, DocumentOutline } from '@vicons/ionicons5'
import { api } from '../api'

const msg = useMessage()

const files = ref([])            // 可看的日志（/api/logs）
const LOGDIR = ref('')
const file = ref('')             // 当前文件名
const n = ref(300)               // 取多少行
const kw = ref('')               // 关键字（回车/点搜索才查）
const q = ref('')                // 真正提交的关键字
const onlyBad = ref(false)       // 只看错误/警告
const auto = ref(true)           // 自动刷新
const every = ref(2000)          // 自动刷新间隔
const data = ref({ lines: [], first_line: 1, total_lines: 0 })
const busy = ref(false)
const lastAt = ref('')
const follow = ref(true)         // 贴在底部（新日志来了自动跟着滚）
const box = ref(null)
let timer = null

const nOptions = [
  { label: '最近 100 行', value: 100 }, { label: '最近 300 行', value: 300 },
  { label: '最近 1000 行', value: 1000 }, { label: '最近 3000 行', value: 3000 },
  { label: '最近 5000 行', value: 5000 },
]
const everyOptions = [
  { label: '每 2 秒', value: 2000 }, { label: '每 5 秒', value: 5000 },
  { label: '每 10 秒', value: 10000 },
]

/** 给每一行定个性：报错 / 警告 / 正常成功 —— 页面靠它上色、也靠它过滤 */
function levelOf(l) {
  const s = String(l)
  if (/Traceback|Error|ERROR|错误|失败|异常|✗|Exception|拒绝/.test(s)) return 'err'
  if (/警告|WARN|warn|跳过|重试|没能|没有/.test(s)) return 'warn'
  if (/✓|✔|成功|完成|已传|已清/.test(s)) return 'ok'
  return ''
}

const rows = computed(() => {
  const base = data.value.first_line || 1
  return (data.value.lines || []).map((text, i) => ({
    no: base + i, text, lv: levelOf(text),
  }))
})
const shown = computed(() => (onlyBad.value ? rows.value.filter((r) => r.lv === 'err' || r.lv === 'warn') : rows.value))
const badCount = computed(() => rows.value.filter((r) => r.lv === 'err').length)
const warnCount = computed(() => rows.value.filter((r) => r.lv === 'warn').length)

function humanSize(v) {
  const b = Number(v || 0)
  return b >= 1048576 ? (b / 1048576).toFixed(1) + ' MB' : b >= 1024 ? (b / 1024).toFixed(1) + ' KB' : b + ' B'
}

async function loadFiles() {
  try {
    const d = await api.logs()
    files.value = d.files || []
    LOGDIR.value = d.dir || ''
    if (!file.value) {
      const cur = files.value.find((f) => f.name === d.current)
      file.value = (cur || files.value[0] || {}).name || ''
    }
  } catch (e) {
    msg.error('列日志文件失败：' + e.message)
  }
}

async function load(quiet = false) {
  if (!file.value) return
  busy.value = true
  try {
    data.value = await api.log({
      file: file.value, n: n.value, q: q.value,
    })
    lastAt.value = new Date().toLocaleTimeString()
    if (follow.value) {
      await nextTick()
      scrollBottom()
    }
  } catch (e) {
    if (!quiet) msg.error('读日志失败：' + e.message)
  } finally {
    busy.value = false
  }
}

function scrollBottom() {
  const el = box.value
  if (el) el.scrollTop = el.scrollHeight
}

function onScroll() {
  const el = box.value
  if (!el) return
  follow.value = el.scrollHeight - el.scrollTop - el.clientHeight < 40
}

function search() {
  q.value = kw.value.trim()
  load()
}

function pickFile(name) {
  file.value = name
  load()
}

function pickN(v) {
  n.value = v
  load()
}

function toggleAuto(v) {
  auto.value = v
  setupTimer()
  if (v) msg.info('自动刷新已开（' + (every.value / 1000) + ' 秒一次）')
}

function setupTimer() {
  if (timer) { clearInterval(timer); timer = null }
  if (auto.value) timer = setInterval(() => load(true), every.value)
}

onMounted(async () => {
  await loadFiles()
  await load()
  setupTimer()
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <div class="pane">
    <div class="bar">
      <n-select :value="file" :options="files.map((f) => ({ label: f.name, value: f.name }))"
                size="small" style="width: 260px" @update:value="pickFile" />
      <n-select :value="n" :options="nOptions" size="small" style="width: 140px"
                :disabled="!!q" @update:value="pickN" />
      <n-input v-model:value="kw" size="small" class="kw" clearable
               placeholder="按关键字在整个日志里找（回车）" @keyup.enter="search" />
      <n-button size="small" type="primary" ghost @click="search">在日志里找</n-button>
      <n-button v-if="q" size="small" @click="kw = ''; search()">清掉「{{ q }}」</n-button>
    </div>
    <div class="bar">
      <n-button size="small" :loading="busy" @click="load()">
        <template #icon><n-icon><RefreshOutline /></n-icon></template>
        刷新
      </n-button>
      <span class="lab">自动刷新</span>
      <n-switch :value="auto" size="small" @update:value="toggleAuto" />
      <n-select :value="every" :options="everyOptions" size="small" style="width: 110px"
                :disabled="!auto" @update:value="(v) => { every = v; setupTimer() }" />
      <span class="lab">只看错误/警告</span>
      <n-switch v-model:value="onlyBad" size="small" />
      <n-button size="small" @click="api.open('folder', LOGDIR).catch((e) => msg.error(e.message))">
        <template #icon><n-icon><FolderOpenOutline /></n-icon></template>
        打开日志文件夹
      </n-button>
      <n-button size="small" @click="api.log({ file: file, n: 5000, q: q }).then((d) => {
        navigator.clipboard.writeText((d.lines || []).join('\n'))
          .then(() => msg.success('已复制 ' + (d.lines || []).length + ' 行'))
          .catch(() => msg.error('复制失败（浏览器不给权限）')) })">
        <template #icon><n-icon><DocumentOutline /></n-icon></template>
        复制全部
      </n-button>
    </div>

    <div class="meta">
      <span><b>{{ data.file || '-' }}</b></span>
      <span>大小 {{ humanSize(data.size) }}</span>
      <span>改动 {{ data.mtime || '-' }}</span>
      <span>共 {{ data.total_lines || 0 }} 行</span>
      <span v-if="q">匹配 <b>{{ data.matched || 0 }}</b> 行（显示最后 {{ rows.length }} 行）</span>
      <span class="err" v-if="badCount">报错 {{ badCount }}</span>
      <span class="warn" v-if="warnCount">警告 {{ warnCount }}</span>
      <span class="dim">上次刷新 {{ lastAt || '-' }}{{ auto ? '（自动）' : '' }}</span>
      <span class="dim">{{ auto ? '正在自动刷新' : '已暂停自动刷新' }}</span>
    </div>

    <div ref="box" class="logbox" @scroll="onScroll">
      <div v-if="!shown.length" class="empty">
        {{ q ? '没有匹配「' + q + '」的行' : (onlyBad ? '这段时间没有报错/警告' : '日志是空的') }}
      </div>
      <div v-for="r in shown" :key="r.no" class="ln" :class="r.lv">
        <span class="no">{{ r.no }}</span>
        <span class="tx">{{ r.text }}</span>
      </div>
    </div>

    <div class="foot">
      <n-button v-if="!follow" size="tiny" type="primary" ghost @click="follow = true; scrollBottom()">
        回到底部（跟着新日志）
      </n-button>
      <span v-else class="dim">已贴在底部，新日志会自动跟着滚</span>
    </div>
  </div>
</template>

<style scoped>
.pane {
  height: 100%;
  overflow: hidden;
  padding: 12px 16px 14px;
  display: flex;
  flex-direction: column;
}
.bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.bar .kw { width: 300px; }
.lab { font-size: 12px; opacity: 0.7; }
.meta {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 12px;
  opacity: 0.85;
  padding: 4px 2px 6px;
  border-bottom: 1px solid rgba(128, 128, 128, 0.18);
}
.meta .err { color: #d03050; }
.meta .warn { color: #f0a020; }
.dim { opacity: 0.6; }
.logbox {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  margin: 6px 0;
  padding: 6px 8px;
  border: 1px solid rgba(128, 128, 128, 0.18);
  border-radius: 4px;
  background: rgba(128, 128, 128, 0.05);
  font: 12px/1.6 Consolas, "Cascadia Mono", "Microsoft YaHei Mono", monospace;
  white-space: pre-wrap;
  word-break: break-all;
}
.ln { display: flex; gap: 10px; }
.ln .no {
  flex: 0 0 52px;
  text-align: right;
  opacity: 0.35;
  user-select: none;
}
.ln .tx { flex: 1 1 auto; min-width: 0; }
.ln.err .tx { color: #d03050; }
.ln.warn .tx { color: #f0a020; }
.ln.ok .tx { color: #18a058; }
.empty { opacity: 0.5; padding: 12px; }
.foot { display: flex; align-items: center; gap: 8px; font-size: 12px; }
</style>
