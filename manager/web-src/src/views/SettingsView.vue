<script setup>
import { ref, computed, inject, onMounted } from 'vue'
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

// ---------------- 云存储（夸克归档）----------------
const cloudBusy = ref(false)
const cloudRes = ref(null)
const cloudOn = computed({
  get: () => String(s.value.cloud_backend || '') === 'quark',
  set: (v) => { s.value.cloud_backend = v ? 'quark' : '' },
})
const cloudText = computed(() => {
  const r = cloudRes.value
  if (!r) return ''
  const ck = r.cookie || {}
  const lines = []
  if (!r.ok) lines.push('✗ ' + (r.error || '自检没通过'))
  if (ck.length) {
    lines.push('Cookie 体检：' + ck.length + ' 字符 / ' + (ck.total_keys || 0) + ' 个字段'
      + (ck.had_prefix ? '（带了 "Cookie:" 前缀，已自动去掉）' : ''))
    lines.push('关键字段：' + ((ck.present || []).join('、') || '一个都没有')
      + (((ck.missing || []).length) ? '　缺：' + ck.missing.join('、') : '　齐全 ✓'))
  } else if (!r.ok) {
    lines.push('Cookie 体检：没读到任何内容（输入框是空的？）')
  }
  if (!r.ok) return lines.join('\n')
  lines.push('✓ 连通：' + (r.user || '(未返回昵称)') + (r.member ? '（' + r.member + '）' : ''))
  lines.push('云端根目录：' + r.root + (r.root_fid ? '（fid ' + r.root_fid.slice(0, 10) + '…）' : ''))
  lines.push('根下：' + (r.root_dirs || 0) + ' 个目录 /' + (r.root_children || 0) + ' 个条目')
  if ((r.sample || []).length) {
    lines.push('样例：' + r.sample.map((x) => x.name + (x.dir ? '/' : '')).join('、'))
  }
  if (r.download_test) lines.push('取直链测试：' + r.download_test)
  return lines.join('\n')
})


async function testCloud() {
  cloudBusy.value = true
  cloudRes.value = null
  try {
    // 先把输入框里的这三个字段存下来再自检 —— 否则读的还是上一次保存的值，
    // 主人「填了就点测试」会得到「还没填 Cookie」这种莫名其妙的提示（踩过）。
    const root = String(s.value.cloud_root || '/MOD').trim() || '/MOD'
    await api.saveSettings({
      cloud_backend: s.value.cloud_backend || '',
      cloud_cookie: s.value.cloud_cookie || '',
      cloud_root: root,
    })
    cloudRes.value = await api.cloudCheck()
  } catch (e) {
    cloudRes.value = { ok: false, error: e.message }
  } finally {
    cloudBusy.value = false
  }
}

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
      cloud_backend: s.value.cloud_backend || '', cloud_cookie: s.value.cloud_cookie || '',
      cloud_root: s.value.cloud_root || '/MOD',
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
    <div class="inside">
      <n-alert v-if="resolved.temp_root" type="warning" :show-icon="false" style="margin-bottom: 12px">
        当前是临时根目录模式（命令行 --root），Mod 根目录不可改。
      </n-alert>

      <!-- ① 游戏内插件 -->
      <n-card size="small" class="sec" title="游戏内插件（Mod Bridge）">
        <template #header-extra>
          <n-space size="small">
            <n-button size="tiny" type="primary" ghost :loading="testing" @click="autoPair">
              自动配对（推荐）
            </n-button>
            <n-button size="tiny" :loading="testing" @click="testBridge">测试连接</n-button>
            <n-button size="tiny" :loading="testing" @click="loadVersions">刷新版本</n-button>
          </n-space>
        </template>
        <n-form label-placement="left" label-width="96" size="small">
          <n-form-item label="地址 / token">
            <n-space align="center" style="flex: 1 1 auto; flex-wrap: nowrap">
              <n-input v-model:value="s.bridge_url" placeholder="http://127.0.0.1:42100"
                       style="flex: 1 1 auto; min-width: 170px" />
              <n-input v-model:value="s.bridge_token" placeholder="token（游戏里 /modbridge 复制）"
                       style="flex: 1 1 auto; min-width: 170px" />
            </n-space>
          </n-form-item>
          <n-form-item label="版本">
            <div class="verbox">
              <div>
                <span class="chip">管理器 v{{ resolved.manager_version || '?' }}</span>
                <span v-if="resolved.manager_build" class="dim">构建 {{ resolved.manager_build }}</span>
                <span v-if="resolved.min_plugin_version" class="dim">・要求插件 ≥ v{{ resolved.min_plugin_version }}</span>
              </div>
              <div style="margin-top: 4px">
                <template v-if="verInfo && verInfo.plugin_version">
                  <span class="chip ok">插件 v{{ verInfo.plugin_version }}</span>
                  <span v-if="verInfo.plugin_ok" style="color:#18a058">✓ 版本达标</span>
                  <span v-else style="color:#d03050">✗ 版本过旧，请更新插件并重启游戏</span>
                </template>
                <template v-else-if="verInfo"><span class="dim">没连上（点「测试连接」或「自动配对」）</span></template>
                <template v-else><span class="dim">点「刷新版本」查看</span></template>
              </div>
            </div>
          </n-form-item>
          <n-form-item v-if="verInfo && verInfo.plugin_version && !verInfo.plugin_ok" label=" ">
            <n-alert type="warning" :show-icon="false">{{ verInfo.version_message }}</n-alert>
          </n-form-item>
          <n-form-item v-if="bridgeMsg" label=" ">
            <n-alert :type="bridgeMsg.ok ? 'success' : 'warning'" :show-icon="false">{{ bridgeMsg.text }}</n-alert>
          </n-form-item>
        </n-form>
      </n-card>

      <!-- ② 封面同步 -->
      <n-card size="small" class="sec" title="封面同步到游戏">
        <div class="hint">
          Penumbra 认的是 mod 文件夹里的 <code>cover.webp</code>（Heliosphere 的包就是这个文件名）；新装的 mod 会自动带上。
          已经装好的那些可以用这里一次补上（按 mod 名对号入座，只写封面，不动 mod 内容）。
        </div>
        <n-space align="center" style="margin-top: 8px">
          <n-button size="small" :loading="syncing" @click="syncCoversPreview">预览能同步哪些</n-button>
          <n-button size="small" type="primary" :loading="syncing"
                    :disabled="!syncInfo || !syncInfo.willFix" @click="syncCoversRun">开始同步</n-button>
        </n-space>
        <n-alert v-if="syncMsg" :type="syncMsg.ok ? 'success' : 'warning'" :show-icon="false"
                 style="margin-top: 8px">{{ syncMsg.text }}</n-alert>
        <div v-if="syncInfo && syncInfo.noCoverList && syncInfo.noCoverList.length" class="hint" style="margin-top: 6px">
          还没封面图的（先去 Mod 列表点「补预览图」）：
          {{ syncInfo.noCoverList.map((x) => x.mod).slice(0, 8).join('、') }}
          <span v-if="syncInfo.noCoverList.length > 8">…</span>
        </div>
        <div v-if="syncInfo && syncInfo.unmatchedList && syncInfo.unmatchedList.length" class="hint" style="margin-top: 4px">
          对不上号的（游戏里装了、管理器里没有）：
          {{ syncInfo.unmatchedList.map((x) => x.dir).slice(0, 6).join('、') }}
          <span v-if="syncInfo.unmatchedList.length > 6">…</span>
        </div>
      </n-card>

      <!-- ③ 目录 -->
      <n-card size="small" class="sec" title="目录">
        <div class="hint">路径直接粘绝对路径（浏览器拿不到本机文件夹选择框）；留空表示用默认值（灰色字是实际生效的值）。</div>
        <n-form label-placement="left" label-width="108" size="small" style="margin-top: 8px">
          <n-form-item label="Mod 根目录">
            <n-space align="center" class="pathrow">
              <n-input v-model:value="s.root" placeholder="G:\Games\FFXIV\MOD\202609" class="pathinput" />
              <n-button size="small" @click="api.open('root')">打开</n-button>
            </n-space>
          </n-form-item>
          <n-form-item label="汇总表 Excel">
            <n-space align="center" class="pathrow">
              <n-input v-model:value="s.excel" placeholder="留空 = 放在 Mod 根目录旁边" class="pathinput" />
              <n-button size="small" @click="api.open('excel')">打开</n-button>
            </n-space>
          </n-form-item>
          <n-form-item label="下载目录">
            <n-space align="center" class="pathrow">
              <n-input v-model:value="s.download_dir" :placeholder="resolved.download_resolved" class="pathinput" />
              <n-button size="small" @click="api.open('downloads')">打开</n-button>
            </n-space>
          </n-form-item>
          <n-form-item label="暂存目录">
            <n-space align="center" class="pathrow">
              <n-input v-model:value="s.inbox_dir" :placeholder="resolved.inbox_resolved" class="pathinput" />
              <n-button size="small" @click="api.open('inbox')">打开</n-button>
            </n-space>
          </n-form-item>
          <n-form-item label="Penumbra 目录">
            <n-space align="center" class="pathrow">
              <n-input v-model:value="s.install_dir"
                       placeholder="留空 = 自动探测；填了列表里就会显示已安装/未安装" class="pathinput" />
              <n-button size="small" :disabled="!resolved.install_resolved" @click="api.open('install')">打开</n-button>
            </n-space>
          </n-form-item>
          <n-form-item label="备份目录">
            <n-space align="center" class="pathrow">
              <n-input v-model:value="s.backup_dir" :placeholder="resolved.backup_resolved" class="pathinput" />
              <n-button size="small" @click="api.open('backup')">打开</n-button>
            </n-space>
          </n-form-item>
        </n-form>
      </n-card>

      <!-- ④ 云存储（夸克网盘）：载荷归档，本地只留元数据 + 图 -->
      <n-card size="small" class="sec" title="云存储（夸克网盘）">
        <template #header-extra>
          <n-button size="tiny" :loading="cloudBusy" @click="testCloud">测试连接</n-button>
        </template>
        <div class="opts">
          <div class="opt">
            <span class="opt-lbl">启用归档</span>
            <n-switch v-model:value="cloudOn" size="small" />
            <span class="hint">
              开启后 Mod 载荷（.pmp / .zip 等）归档到夸克，本地只留元数据 + 预览图
            </span>
          </div>
          <div class="opt">
            <span class="opt-lbl">云端根目录</span>
            <n-input v-model:value="s.cloud_root" size="small" style="width: 200px"
                     placeholder="/MOD" />
            <span class="hint">夸克里的目录路径（你之前那批就传在 /MOD）</span>
          </div>
        </div>
        <div class="opt" style="align-items: flex-start; margin-top: 8px">
          <span class="opt-lbl" style="padding-top: 4px">Cookie</span>
          <n-input v-model:value="s.cloud_cookie" type="textarea" :rows="3" size="small"
                   style="max-width: 660px"
                   placeholder="浏览器登录 pan.quark.cn 后，把整条 Cookie 粘进来（含 __kps / __uid / __pus / sign 等字段）" />
        </div>
        <div class="hint" style="margin-top: 6px">
          夸克没有公开的官方接口，这里走的是它 PC 端接口（<b>非官方，夸克改版可能失效</b>）。
          Cookie 只写在本机 <code>mod_manager.json</code>，不会外发；失效时点「测试连接」会提示重新粘贴。
        </div>
        <n-alert v-if="cloudRes" :type="cloudRes.ok ? 'success' : 'error'" :show-icon="false"
                 style="margin-top: 8px; white-space: pre-wrap; font-size: 12px">
          {{ cloudText }}
        </n-alert>
      </n-card>

      <!-- ⑤ 内置浏览器 -->
      <n-card size="small" class="sec" title="内置浏览器">
        <n-form label-placement="left" label-width="108" size="small">
          <n-form-item label="浏览器程序">
            <n-input v-model:value="s.browser_path"
                     placeholder="留空 = 自动探测（优先 CentBrowser / Chrome / Edge）"
                     style="flex: 1 1 auto" />
          </n-form-item>
          <n-form-item label="自动开浏览器">
            <div style="flex: 1 1 auto">
              <n-switch v-model:value="s.auto_open_browser" />
              <span class="dim" style="margin-left: 10px">只在需要时才自动打开（默认关闭）</span>
              <div class="hint" style="margin-top: 4px">
                默认<b>关闭</b>：用书签小工具在你自己浏览器里把页面推过来就够了 ——「解析链接」和「抓封面」都不会再自作主张去开内置浏览器。
                只有必须让工具自己去过 Cloudflare、或要现抓整页画廊时，才勾上它。
                <br />顺手一提：NSFW 的 Mod 想自动检查更新／下载，需要在<b>内置浏览器里登录一次</b> XIVModArchive。
              </div>
            </div>
          </n-form-item>
        </n-form>
      </n-card>

      <!-- ⑥ Excel 导出 -->
      <n-card size="small" class="sec" title="Excel 导出">
        <div class="opts">
          <div class="opt">
            <span class="opt-lbl">缩略图宽</span>
            <n-input-number v-model:value="s.thumb_width" :min="120" :max="2400" :step="100"
                            size="small" style="width: 130px" />
            <span class="hint">像素，越大越清晰也越大</span>
          </div>
          <div class="opt">
            <span class="opt-lbl">内嵌预览图</span>
            <n-switch v-model:value="s.embed_images" size="small" />
            <span class="hint">关掉的话 Excel 只有文字</span>
          </div>
          <div class="opt">
            <span class="opt-lbl">表头筛选</span>
            <n-switch v-model:value="s.autofilter" size="small" />
            <span class="hint">给 Excel 表头加筛选按钮</span>
          </div>
        </div>
      </n-card>
    </div>

    <!-- 底部操作条：滚多远都能点到保存 -->
    <div class="footbar">
      <span class="dim">索引库：{{ resolved.db }} ｜ 日志：{{ resolved.logging }}</span>
      <div class="grow"></div>
      <n-button size="small" @click="api.open('log')">打开日志</n-button>
      <n-button size="small" @click="load">重新读取</n-button>
      <n-button size="small" type="primary" :loading="busy" @click="save">保存</n-button>
    </div>
  </div>
</template>

<style scoped>
.pane {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.inside {
  flex: 1 1 auto;
  overflow: auto;
  padding: 16px 18px 8px;
  max-width: 1120px;
}
.sec {
  margin-bottom: 12px;
}
.sec :deep(.n-card__content) {
  padding: 12px 14px;
}
.hint {
  font-size: 12px;
  opacity: 0.65;
  line-height: 1.6;
}
.dim {
  font-size: 12px;
  opacity: 0.65;
}
.verbox {
  flex: 1 1 auto;
  line-height: 1.8;
}
.chip {
  display: inline-block;
  padding: 0 6px;
  margin-right: 6px;
  border: 1px solid rgba(128, 128, 128, 0.3);
  border-radius: 4px;
  font-size: 12px;
}
.chip.ok {
  border-color: rgba(24, 160, 88, 0.5);
  color: #18a058;
}
.pathrow {
  flex: 1 1 auto;
  flex-wrap: nowrap;
  width: 100%;
}
.pathinput {
  flex: 1 1 auto;
  min-width: 220px;
}
.opts {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 28px;
}
.opt {
  display: flex;
  align-items: center;
  gap: 8px;
}
.opt-lbl {
  font-size: 13px;
  opacity: 0.8;
  min-width: 76px;
  text-align: right;
}
.footbar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 18px;
  border-top: 1px solid rgba(128, 128, 128, 0.18);
}
.grow {
  flex: 1 1 auto;
}
</style>