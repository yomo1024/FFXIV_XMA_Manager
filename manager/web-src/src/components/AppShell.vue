<script setup>
import { ref, computed, h, onMounted, onUnmounted, provide, watch } from 'vue'
import {
  NLayout, NLayoutSider, NMenu, NButton, NTag, NProgress, NSwitch, NModal, NInput,
  NForm, NFormItem, NAlert, NSpace, NIcon, useMessage, useDialog,
} from 'naive-ui'
import {
  GridOutline, BuildOutline, FolderOpenOutline, ArchiveOutline, GlobeOutline,
  DownloadOutline, SettingsOutline, PowerOutline, MoonOutline, SunnyOutline,
  RefreshOutline, DocumentTextOutline, RocketOutline,
} from '@vicons/ionicons5'
import { api, JOB_TITLES, jobResultText } from '../api'
import ModsView from '../views/ModsView.vue'
import ToolsView from '../views/ToolsView.vue'
import CategoriesView from '../views/CategoriesView.vue'
import BackupView from '../views/BackupView.vue'
import PendingView from '../views/PendingView.vue'
import WorkbenchView from '../views/WorkbenchView.vue'
import SettingsView from '../views/SettingsView.vue'

const props = defineProps({ dark: Boolean })
const emit = defineEmits(['update:dark'])
const msg = useMessage()
const dialog = useDialog()

const build = typeof __BUILD__ !== 'undefined' ? __BUILD__ : 'dev'
// 侧栏太窄，只显示时:分，完整时间挂在 tooltip 上
const buildShort = (function () {
  const m = String(build).match(/(\d{1,2}:\d{2})/)
  return m ? m[1] : String(build).slice(0, 12)
})()
const state = ref(null)
const managerVer = computed(() => (state.value && state.value.manager_version) || '')
const job = ref(null)
const mods = ref([])
const view = ref(new URLSearchParams(location.search).get('view') || 'mods')
const collapsed = ref(false)
let timer = null

const icon = (comp) => () => h(NIcon, null, { default: () => h(comp) })

const MENU = [
  { label: 'Mod 列表', key: 'mods', icon: icon(GridOutline) },
  { label: '检查 / 工具', key: 'tools', icon: icon(BuildOutline) },
  { label: '分类管理', key: 'cats', icon: icon(FolderOpenOutline) },
  { label: '备份 / 恢复', key: 'backup', icon: icon(ArchiveOutline) },
  { label: '下载工作台', key: 'work', icon: icon(GlobeOutline) },
  { label: '待导入', key: 'pending', icon: icon(DownloadOutline) },
  { label: '设置', key: 'settings', icon: icon(SettingsOutline) },
]
const TITLES = {
  mods: ['Mod 列表', '浏览、筛选、批量整理你的 Mod'],
  tools: ['检查 / 工具', '查重、安装检查、体检报告、序号重排'],
  cats: ['分类管理', '分类与子分类的增删改和显示顺序'],
  backup: ['备份 / 恢复', '打包整个 Mod 库，或从备份恢复'],
  work: ['下载工作台', '内置浏览器读页面、抓封面、盯下载'],
  pending: ['待导入', '下载目录 / 暂存目录里还没入库的文件'],
  settings: ['设置', '路径、缩略图、浏览器等偏好'],
}

// bus 必须在 provide 之前声明，否则会 TDZ（压缩后就是那条很难查的
// "Cannot access 'x' before initialization"）
const bus = { refresh: null, prefillAdd: null }
provide('mm', { state, mods, startJob, refreshAll, msg, bus })

async function refreshAll() {
  state.value = await api.state()
  const d = await api.mods()
  mods.value = d.mods || []
}

function pollJob() {
  clearTimeout(timer)
  timer = setTimeout(async () => {
    let s
    try {
      s = await api.job()
    } catch (e) {
      return
    }
    if (s.state === 'idle') {
      job.value = null
      return
    }
    job.value = s
    if (s.state === 'running') return pollJob()
    try {
      await refreshAll()
      await bus.refresh?.()
    } catch (e) {}
    s.state === 'error' ? msg.error(jobResultText(s)) : msg.success(jobResultText(s))
    setTimeout(() => (job.value = null), 6000)
  }, 300)
}

async function startJob(kind, params) {
  try {
    await api.startJob(kind, params)
    job.value = { kind, state: 'running', pct: 0, done: 0, total: 0, text: '准备中…', elapsed: 0 }
    pollJob()
  } catch (e) {
    msg.error(e.message)
  }
}

function doQuit() {
  dialog.warning({
    title: '退出服务',
    content: '关掉后台服务，页面会失效（Mod 数据不受影响）。下次双击「启动Web版」即可。',
    positiveText: '退出服务',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        const r = await api.quit()
        document.body.innerHTML =
          '<div style="display:flex;height:100vh;align-items:center;justify-content:center;' +
          'font:15px/2 system-ui,\'Microsoft YaHei\',sans-serif;color:#666;text-align:center">' +
          '<div>' + r.bye + '<br><span style="font-size:13px;opacity:.7">' +
          'Mod 目录、索引库、汇总表都没有改动</span></div></div>'
      } catch (e) {
        msg.error('退出失败：' + e.message)
      }
    },
  })
}

// 首次使用向导
const wizard = ref(false)
const wiz = ref({ root: '', excel: '' })
watch(
  state,
  (s) => {
    if (s && !s.root_ok) {
      wiz.value.root = s.root || ''
      wiz.value.excel = s.excel || s.excel_suggest || ''
      wizard.value = true
    }
  },
  { immediate: true },
)
async function saveWizard() {
  if (!wiz.value.root.trim()) return msg.warning('先填 Mod 根目录')
  try {
    await api.saveSettings({ root: wiz.value.root.trim(), excel: wiz.value.excel.trim() })
    wizard.value = false
    msg.success('配置好了，开始扫描…')
    await refreshAll()
    startJob('run')
  } catch (e) {
    msg.error(e.message)
  }
}

const title = computed(() => TITLES[view.value] || ['FFXIV Mod 管理', ''])
const meta = computed(() => {
  const s = state.value || {}
  return [
    s.root ? { k: 'Mod 目录', v: s.root, open: 'root' } : null,
    s.excel ? { k: 'Excel', v: s.excel, open: 'excel' } : null,
    s.install_dir ? { k: '安装目录', v: s.install_dir, open: 'install' } : null,
  ].filter(Boolean)
})

onMounted(async () => {
  try {
    await refreshAll()
    const s = await api.job()
    if (s.state === 'running') {
      job.value = s
      pollJob()
    }
  } catch (e) {
    msg.error('加载失败：' + e.message)
  }
})
onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <n-layout has-sider position="absolute" style="height: 100vh">
    <!-- 左侧导航 -->
    <n-layout-sider bordered collapse-mode="width" :collapsed-width="64" :width="200"
                    :collapsed="collapsed" show-trigger
                    @update:collapsed="(v) => (collapsed = v)">
      <div class="sider">
        <div class="brand" :class="{ mini: collapsed }">
          <div class="logo">F</div>
          <div v-if="!collapsed" class="brand-text">
            <b>FFXIV Mod</b>
            <span>管理器 · Web</span>
          </div>
        </div>

        <div class="nav">
          <n-menu :options="MENU" :value="view" :collapsed="collapsed" :collapsed-width="64"
                  :collapsed-icon-size="20" :indent="18" @update:value="(k) => (view = k)" />
        </div>

        <div class="sider-foot" :class="{ mini: collapsed }">
          <div class="foot-top">
            <n-switch :value="props.dark" size="small"
                      @update:value="(v) => emit('update:dark', v)">
              <template #checked><n-icon><moon-outline /></n-icon></template>
              <template #unchecked><n-icon><sunny-outline /></n-icon></template>
            </n-switch>
            <span v-if="!collapsed" class="dim build"
                  :title="'管理器 v' + (managerVer || '?') + '（前端构建 ' + build + '）'">
              v{{ managerVer || '?' }} · {{ buildShort }}
            </span>
          </div>
          <n-button size="small" quaternary type="error" class="quitbtn"
                    :style="collapsed ? 'padding:0 6px' : ''" @click="doQuit">
            <template #icon><n-icon><power-outline /></n-icon></template>
            <span v-if="!collapsed">退出服务</span>
          </n-button>
        </div>
      </div>
    </n-layout-sider>

    <!-- 右侧内容 -->
    <div class="main">
      <header class="hdr">
        <div class="hdr-top">
          <h1>{{ title[0] }}</h1>
          <n-tag size="small" :bordered="false" round>{{ mods.length }} 条</n-tag>
          <span v-if="state?.temp_root" class="warn">临时根目录模式</span>
          <div class="grow"></div>
          <n-button size="small" @click="startJob('scan')">
            <template #icon><n-icon><refresh-outline /></n-icon></template>重新扫描
          </n-button>
          <n-button size="small" @click="startJob('export')">
            <template #icon><n-icon><document-text-outline /></n-icon></template>生成 Excel
          </n-button>
          <n-button size="small" type="primary" @click="startJob('run')">
            <template #icon><n-icon><rocket-outline /></n-icon></template>扫描并生成 Excel
          </n-button>
          <n-button size="small" @click="startJob('backup')">打包备份</n-button>
        </div>
        <div class="hdr-sub">
          <span class="sub-title">{{ title[1] }}</span>
          <span v-for="m in meta" :key="m.k" class="path" :title="m.v">
            <span class="dim">{{ m.k }}</span>{{ m.v }}
          </span>
        </div>
      </header>

      <div v-if="job" class="jobbar">
        <b>{{ JOB_TITLES[job.kind] || job.kind }}</b>
        <n-progress type="line" :percentage="job.pct" :show-indicator="false" :height="8"
                    style="flex: 1; min-width: 120px" />
        <span class="jobtext">
          {{ job.total ? `${job.done}/${job.total} · ` : '' }}{{ job.text }}
          <span class="dim">· 已用 {{ job.elapsed }}s</span>
        </span>
        <n-button size="tiny" type="error" quaternary :disabled="job.state !== 'running'"
                  @click="api.cancelJob().then(() => msg.info('正在取消…')).catch((e) => msg.error(e.message))">
          取消
        </n-button>
      </div>

      <main class="content">
        <mods-view v-if="view === 'mods'" :mods="mods" @changed="refreshAll" />
        <tools-view v-else-if="view === 'tools'" :mods="mods" @changed="refreshAll" />
        <categories-view v-else-if="view === 'cats'" @changed="refreshAll" />
        <backup-view v-else-if="view === 'backup'" />
        <workbench-view v-else-if="view === 'work'" :mods="mods" @changed="refreshAll" />
        <pending-view v-else-if="view === 'pending'" @changed="refreshAll" />
        <settings-view v-else-if="view === 'settings'" @changed="refreshAll" />
      </main>
    </div>
  </n-layout>

  <n-modal v-model:show="wizard" preset="card" style="width: 620px"
           title="首次使用：先告诉它 Mod 放在哪">
    <n-alert type="info" :show-icon="false" style="margin-bottom: 12px">
      填你放 Mod 的那一层目录（里面是 衣服 / 饰品 / 武器 / 皮肤 这些分类文件夹）。
      浏览器拿不到系统文件夹选择框，所以这里直接粘路径。
    </n-alert>
    <n-form size="small" label-placement="left" label-width="104">
      <n-form-item label="Mod 根目录">
        <n-input v-model:value="wiz.root" placeholder="G:\Games\FFXIV\MOD\202609" />
      </n-form-item>
      <n-form-item label="汇总表 Excel">
        <n-input v-model:value="wiz.excel" placeholder="留空会自动放在 Mod 根目录旁边" />
      </n-form-item>
    </n-form>
    <n-alert type="warning" :show-icon="false">
      保存后会立刻扫描一遍目录，并把索引和 Excel 生成好。
    </n-alert>
    <template #footer>
      <n-space justify="end">
        <n-button size="small" @click="wizard = false">先随便看看</n-button>
        <n-button size="small" type="primary" @click="saveWizard">保存并扫描</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<style scoped>
.sider {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 16px 12px;
}
.brand.mini {
  justify-content: center;
  padding: 16px 0 12px;
}
.logo {
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  border-radius: 9px;
  background: linear-gradient(135deg, #4b8bf5, #2f6feb);
  color: #fff;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
}
.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
}
.brand-text b {
  font-size: 14px;
}
.brand-text span {
  font-size: 11px;
  opacity: 0.5;
}
.nav {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding-top: 2px;
}
.sider-foot {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  padding: 10px 12px 12px;
  border-top: 1px solid rgba(128, 128, 128, 0.16);
}
.foot-top {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.sider-foot.mini {
  align-items: center;
  padding: 10px 6px 12px;
  gap: 10px;
}
.sider-foot.mini .foot-top {
  flex-direction: column;
  gap: 6px;
}
.sider-foot .dim {
  font-size: 12px;
}
.build {
  font-size: 10px;
  opacity: 0.45;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
/* 整行按钮：窄侧栏也不会被挤出去 */
.quitbtn {
  width: 100%;
}
.sider-foot.mini .quitbtn {
  width: auto;
}
.main {
  flex: 1 1 auto;
  min-width: 0;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.hdr {
  flex: 0 0 auto;
  padding: 10px 18px 7px;
  border-bottom: 1px solid rgba(128, 128, 128, 0.16);
}
.hdr-top {
  display: flex;
  align-items: center;
  gap: 10px;
}
.hdr-top h1 {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.2px;
}
.hdr-top .grow {
  flex: 1 1 auto;
}
.hdr-sub {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 3px;
  font-size: 12px;
  opacity: 0.72;
  white-space: nowrap;
  overflow: hidden;
}
.sub-title {
  flex: 0 0 auto;
}
.path {
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 34%;
}
.path .dim {
  margin-right: 4px;
}
.warn {
  font-size: 12px;
  padding: 1px 8px;
  border-radius: 999px;
  background: rgba(208, 48, 80, 0.12);
  color: #d03050;
}
.dim {
  opacity: 0.6;
}
.jobbar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 18px;
  border-bottom: 1px solid rgba(128, 128, 128, 0.16);
}
.jobtext {
  flex: 0 1 auto;
  max-width: 46%;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.content {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}
</style>
