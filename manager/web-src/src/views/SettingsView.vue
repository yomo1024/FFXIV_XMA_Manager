<script setup>
import { ref, inject, onMounted } from 'vue'
import {
  NButton, NCard, NSpace, NForm, NFormItem, NInput, NInputNumber, NSwitch, NAlert,
  NDivider, useMessage,
} from 'naive-ui'
import { api } from '../api'

const emit = defineEmits(['changed'])
const { bus } = inject('mm')
const msg = useMessage()

const s = ref({})
const resolved = ref({})
const busy = ref(false)
const testing = ref(false)
const bridgeMsg = ref(null)
const syncMsg = ref(null)
const verInfo = ref(null)
const syncInfo = ref(null)
const syncing = ref(false)

async function autoPair() {
  testing.value = true
  bridgeMsg.value = null
  try {
    const r = await api.bridgeAutopair()
    if (!r.paired) {
      bridgeMsg.value = { ok: false, text: r.error || '自动配对失败' }
      return
    }
    await load()
    const pb = r.penumbra || {}
    bridgeMsg.value = {
      ok: !!r.live,
      text: r.live
        ? `配对成功（读了 ${r.configPath}，token 尾号 ${r.tokenTail}）：插件 v${r.plugin_version}，` +
          `Penumbra ${pb.available ? `已就绪（API ${pb.apiMajor}.${pb.apiMinor}，${pb.modCount} 个 mod）` : '未就绪'}`
        : `token 已写入（尾号 ${r.tokenTail}），但现在连不上插件：${r.warning || ''}`,
    }
  } catch (e) {
    bridgeMsg.value = { ok: false, text: e.message }
  } finally {
    testing.value = false
  }
}

async function loadVersions() {
  try {
    verInfo.value = await api.bridgeStatus()
  } catch (e) {
    verInfo.value = null
  }
}

async function testBridge() {
  testing.value = true
  bridgeMsg.value = null
  try {
    // 先存再测，免得测的是旧值
    await api.saveSettings({ bridge_url: s.value.bridge_url, bridge_token: s.value.bridge_token })
    const r = await api.bridgeStatus()
    verInfo.value = r
    if (r.ok) {
      const p = r.ping || {}
      const pb = p.penumbra || {}
      bridgeMsg.value = {
        ok: true,
        text: `已连上插件 v${p.version || '?'}；Penumbra ` +
          (pb.available ? `已就绪（API ${pb.apiMajor}.${pb.apiMinor}，${pb.modCount} 个 mod）` : '未就绪') +
          '。可以在 Mod 列表里点「安装到游戏」。',
      }
    } else {
      bridgeMsg.value = { ok: false, text: (r.error || '连不上插件') }
    }
  } catch (e) {
    bridgeMsg.value = { ok: false, text: e.message }
  } finally {
    testing.value = false
  }
}

async function syncCoversPreview() {
  syncing.value = true
  syncMsg.value = null
  syncInfo.value = null
  try {
    const r = await api.bridgeSyncCovers(true)
    syncInfo.value = r
    syncMsg.value = {
      ok: true,
      text: `游戏里已装 ${r.installed} 个 mod：能补封面 ${r.willFix} 个，管理器里没封面图 ${r.noCover} 个，` +
        `对不上号 ${r.unmatched} 个。确认无误就点「开始同步」。`,
    }
  } catch (e) {
    syncMsg.value = { ok: false, text: e.message }
  } finally {
    syncing.value = false
  }
}

async function syncCoversRun() {
  syncing.value = true
  syncMsg.value = null
  try {
    const r = await api.bridgeSyncCovers(false)
    syncMsg.value = {
      ok: r.failed === 0,
      text: `同步完成：写入 ${r.written} 个，本来就有封面跳过 ${r.skipped} 个，失败 ${r.failed} 个。` +
        `去游戏里看 Penumbra 的「模组描述」页（没变就重启一次游戏）。`,
    }
  } catch (e) {
    syncMsg.value = { ok: false, text: e.message }
  } finally {
    syncing.value = false
  }
}

async function load() {
  try {
    const d = await api.settings()
    // 版本监控要用的字段在 /api/state 里，设置接口没带过来，这里补上
    try {
      const st = await api.state()
      d.manager_version = st.manager_version || ''
      d.manager_build = st.manager_build || ''
      d.min_plugin_version = st.min_plugin_version || ''
    } catch (e2) { /* 忽略 */ }
    resolved.value = d
    s.value = { ...d }
  } catch (e) {
    msg.error(e.message)
  }
}
bus.refresh = load
onMounted(() => { load(); loadVersions() })

async function save() {
  busy.value = true
  try {
    const body = {
      root: s.value.root, excel: s.value.excel,
      download_dir: s.value.download_dir, inbox_dir: s.value.inbox_dir,
      install_dir: s.value.install_dir, backup_dir: s.value.backup_dir,
      browser_path: s.value.browser_path,
      auto_open_browser: !!s.value.auto_open_browser,
      bridge_url: s.value.bridge_url, bridge_token: s.value.bridge_token,
      thumb_width: s.value.thumb_width,
      embed_images: s.value.embed_images, autofilter: s.value.autofilter,
    }
    const r = await api.saveSettings(body)
    msg.success('已保存：' + (r.changed || []).join('、'))
    await load()
    emit('changed')
  } catch (e) {
    msg.error(e.message)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="pane">
    <n-card size="small" title="设置" style="max-width: 900px">
      <n-alert v-if="resolved.temp_root" type="warning" :show-icon="false" style="margin-bottom: 10px">
        当前是临时根目录模式（命令行 --root），Mod 根目录不可改。
      </n-alert>
      <n-alert type="info" :show-icon="false" style="margin-bottom: 10px">
        路径直接粘绝对路径（浏览器拿不到本机文件夹选择框）。留空表示用默认值。
      </n-alert>
      <n-form label-placement="left" label-width="120" size="small">
        <n-form-item label="游戏内插件">
          <div class="dim" style="width: 100%; margin-bottom: 4px">
            同一台电脑上，游戏里启用过 Mod Bridge 之后点「自动配对」即可（会读插件配置文件里的端口与 token）；
            也可以手动填。
          </div>
          <n-space align="center" style="flex-wrap: wrap">
            <n-input v-model:value="s.bridge_url" placeholder="http://127.0.0.1:42100"
                     style="width: 300px" />
            <n-input v-model:value="s.bridge_token" placeholder="token（游戏里 /modbridge 复制）"
                     style="width: 300px" />
            <n-button size="small" :loading="testing" @click="autoPair">自动配对（推荐）</n-button>
            <n-button size="small" :loading="testing" @click="testBridge">测试连接</n-button>
            <n-button size="small" :loading="testing" @click="loadVersions">刷新版本</n-button>
          </n-space>
        </n-form-item>
        <n-form-item label="版本">
          <div style="width: 100%">
            <div class="dim">
              管理器 <b>v{{ resolved.manager_version || '?' }}</b>
              <span v-if="resolved.manager_build">（构建 {{ resolved.manager_build }}）</span>
              <span v-if="resolved.min_plugin_version">
                ・要求插件 ≥ v{{ resolved.min_plugin_version }}
              </span>
            </div>
            <div class="dim" style="margin-top: 4px">
              <template v-if="verInfo && verInfo.plugin_version">
                游戏内插件 <b>v{{ verInfo.plugin_version }}</b>
                <span v-if="verInfo.plugin_ok" style="color:#18a058">✓ 版本达标</span>
                <span v-else style="color:#d03050">✗ 版本过旧，请更新插件并重启游戏</span>
              </template>
              <template v-else-if="verInfo">游戏内插件：没连上（点「测试连接」或「自动配对」）</template>
              <template v-else>游戏内插件：点「刷新版本」查看</template>
            </div>
            <n-alert v-if="verInfo && verInfo.plugin_version && !verInfo.plugin_ok" type="warning"
                     :show-icon="false" style="max-width: 820px; margin-top: 6px">
              {{ verInfo.version_message }}
            </n-alert>
          </div>
        </n-form-item>
        <n-form-item v-if="bridgeMsg" label=" ">
          <n-alert :type="bridgeMsg.ok ? 'success' : 'warning'" :show-icon="false"
                   style="max-width: 800px">{{ bridgeMsg.text }}</n-alert>
        </n-form-item>
        <n-form-item label="封面同步到游戏">
          <div style="width: 100%">
            <div class="dim" style="margin-bottom: 4px">
              Penumbra 认的是 mod 文件夹里的 <code>cover.webp</code>（Heliosphere 的包就是这个文件名）；新装的 mod 会自动带上。
              已经装好的那些可以用这里一次补上（按 mod 名对号入座，只写封面，不动 mod 内容）。
            </div>
            <n-space align="center">
              <n-button size="small" :loading="syncing" @click="syncCoversPreview">预览能同步哪些</n-button>
              <n-button size="small" type="primary" :loading="syncing"
                        :disabled="!syncInfo || !syncInfo.willFix" @click="syncCoversRun">开始同步</n-button>
            </n-space>
            <n-alert v-if="syncMsg" :type="syncMsg.ok ? 'success' : 'warning'" :show-icon="false"
                     style="max-width: 800px; margin-top: 6px">{{ syncMsg.text }}</n-alert>
            <div v-if="syncInfo && syncInfo.noCoverList && syncInfo.noCoverList.length" class="dim"
                 style="margin-top: 4px">
              管理器里还没封面图的（先去 Mod 列表点「补预览图」）：{{ syncInfo.noCoverList.map((x) => x.mod).slice(0, 8).join('、') }}
              <span v-if="syncInfo.noCoverList.length > 8">…</span>
            </div>
            <div v-if="syncInfo && syncInfo.unmatchedList && syncInfo.unmatchedList.length" class="dim"
                 style="margin-top: 4px">
              对不上号的（游戏里装了、管理器里没有）：{{ syncInfo.unmatchedList.map((x) => x.dir).slice(0, 6).join('、') }}
              <span v-if="syncInfo.unmatchedList.length > 6">…</span>
            </div>
          </div>
        </n-form-item>
        <n-form-item label="Mod 根目录">
          <n-space style="width: 100%">
            <n-input v-model:value="s.root" placeholder="G:\Games\FFXIV\MOD\202609" style="width: 560px" />
            <n-button size="small" @click="api.open('root')">打开</n-button>
          </n-space>
        </n-form-item>
        <n-form-item label="汇总表 Excel">
          <n-space style="width: 100%">
            <n-input v-model:value="s.excel" placeholder="留空=放在 Mod 根目录旁边" style="width: 560px" />
            <n-button size="small" @click="api.open('excel')">打开</n-button>
          </n-space>
        </n-form-item>
        <n-divider style="margin: 8px 0" />
        <n-form-item label="下载目录">
          <n-space style="width: 100%">
            <n-input v-model:value="s.download_dir" :placeholder="resolved.download_resolved" style="width: 560px" />
            <n-button size="small" @click="api.open('downloads')">打开</n-button>
          </n-space>
        </n-form-item>
        <n-form-item label="暂存目录">
          <n-space style="width: 100%">
            <n-input v-model:value="s.inbox_dir" :placeholder="resolved.inbox_resolved" style="width: 560px" />
            <n-button size="small" @click="api.open('inbox')">打开</n-button>
          </n-space>
        </n-form-item>
        <n-form-item label="Penumbra 目录">
          <n-space style="width: 100%">
            <n-input v-model:value="s.install_dir" placeholder="留空=自动探测；填了列表里就会显示已安装/未安装" style="width: 560px" />
            <n-button size="small" :disabled="!resolved.install_resolved" @click="api.open('install')">打开</n-button>
          </n-space>
        </n-form-item>
        <n-form-item label="备份目录">
          <n-space style="width: 100%">
            <n-input v-model:value="s.backup_dir" :placeholder="resolved.backup_resolved" style="width: 560px" />
            <n-button size="small" @click="api.open('backup')">打开</n-button>
          </n-space>
        </n-form-item>
        <n-divider style="margin: 8px 0" />
        <n-form-item label="内置浏览器">
          <n-input v-model:value="s.browser_path" placeholder="留空=自动探测（优先 CentBrowser / Chrome / Edge）" style="width: 560px" />
        </n-form-item>

        <n-form-item label="自动开内置浏览器">
            <div style="width: 100%">
              <n-switch v-model:value="s.auto_open_browser" />
              <span class="dim" style="margin-left: 10px">只在需要时才自动打开（默认关闭）</span>
              <div class="dim" style="margin-top: 4px">
                默认<b>关闭</b>：用书签小工具在你自己浏览器里把页面推过来就够了 ——
                「解析链接」和「抓封面」都不会再自作主张去开内置浏览器。
                只有必须让工具自己去过 Cloudflare、或要现抓整页画廊时，才勾上它。
              </div>
            </div>
        </n-form-item>
        <n-form-item label="Excel 缩略图宽">
          <n-input-number v-model:value="s.thumb_width" :min="120" :max="2400" :step="100" style="width: 160px" />
          <span style="margin-left: 10px; font-size: 12px; opacity: 0.6">像素，越大越清晰也越大</span>
        </n-form-item>
        <n-form-item label="内嵌预览图">
          <n-switch v-model:value="s.embed_images" />
          <span style="margin-left: 10px; font-size: 12px; opacity: 0.6">关掉的话 Excel 只有文字</span>
        </n-form-item>
        <n-form-item label="表头筛选">
          <n-switch v-model:value="s.autofilter" />
          <span style="margin-left: 10px; font-size: 12px; opacity: 0.6">给 Excel 表头加筛选按钮</span>
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="space-between" align="center">
          <span style="font-size: 12px; opacity: 0.55">
            索引库：{{ resolved.db }} ｜ 日志：{{ resolved.logging }}
          </span>
          <n-space>
            <n-button size="small" @click="api.open('log')">打开日志</n-button>
            <n-button size="small" @click="load">重新读取</n-button>
            <n-button size="small" type="primary" :loading="busy" @click="save">保存</n-button>
          </n-space>
        </n-space>
      </template>
    </n-card>
  </div>
</template>

<style scoped>
.pane {
  height: 100%;
  overflow: auto;
  padding: 16px 18px 24px;
}
</style>