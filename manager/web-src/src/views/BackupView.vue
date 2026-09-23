<script setup>
import { ref, computed, inject, onMounted, h } from 'vue'
import {
  NButton, NDataTable, NCard, NSpace, NModal, NRadio, NRadioGroup, NRadioButton,
  NCheckbox, NCheckboxGroup, NAlert, NSpin, NEmpty, NInput, NInputNumber, NTag,
  useMessage, useDialog,
} from 'naive-ui'
import { api } from '../api'

const { startJob, bus } = inject('mm')
const msg = useMessage()
const dialog = useDialog()

const items = ref([])            // 整库备份（zip）
const snaps = ref([])            // 汇总表快照（xlsx）
const stats = ref({})
const dir = ref('')
const busy = ref(false)
const kw = ref('')
const kind = ref('all')
const keep = ref(5)
const checked = ref([])

const showRestore = ref(false)
const pick = ref(null)
const info = ref(null)
const mode = ref('skip')
const include = ref(['mods', 'meta'])

const showDel = ref(false)
const applyCfg = ref(true)          // 恢复时套用包里的配置（迁机用）
const showMigrate = ref(false)      // 「迁机说明」弹窗
const delTargets = ref([])
const delWhy = ref('pick')
const delPerm = ref(false)
const delBusy = ref(false)

async function load() {
  busy.value = true
  try {
    const d = await api.backups()
    items.value = d.items || []
    snaps.value = d.snaps || []
    stats.value = d.stats || {}
    dir.value = d.dir
    const alive = items.value.concat(snaps.value).map((r) => r.name)
    checked.value = checked.value.filter((n) => alive.includes(n))
  } catch (e) {
    msg.error(e.message)
  } finally {
    busy.value = false
  }
}
bus.refresh = load
onMounted(load)

const rows = computed(() => {
  const all = items.value.map((r) => ({ ...r, kind: 'zip' }))
    .concat(snaps.value.map((r) => ({ ...r, kind: 'snap' })))
  const k = kw.value.trim().toLowerCase()
  return all
    .filter((r) => (kind.value === 'all' || r.kind === kind.value)
      && (!k || r.name.toLowerCase().includes(k)))
    .sort((a, b) => b.mtime - a.mtime)
})
const selRows = computed(() => rows.value.filter((r) => checked.value.includes(r.name)))
const selSize = computed(() => fmt(bytesOf(selRows.value)))
const pruneList = computed(() => {
  const z = items.value.slice().sort((a, b) => b.mtime - a.mtime)
  const n = Math.floor(Number(keep.value) || 0)
  return n > 0 ? z.slice(n) : []
})

function bytesOf(list) { return list.reduce((s, r) => s + (r.size || 0), 0) }
function fmt(n) {
  if (n === null || n === undefined) return '—'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = Number(n) || 0
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i += 1 }
  return (i === 0 ? String(v) : v.toFixed(v >= 100 ? 0 : 1)) + ' ' + u[i]
}

function makeBackup() {
  dialog.warning({
    title: '打包备份',
    content: '把整个 Mod 库（Mod 文件夹 + 索引库 + 汇总表）打成一个 zip。'
      + '已归档到云端的载荷不在包里，所以包不大。开始后能看到进度、也能取消。',
    positiveText: '开始',
    negativeText: '取消',
    onPositiveClick: () => startJob('backup', {}),
  })
}

function reveal(r) {
  api.reveal(r.path).then(() => msg.success('已经在文件夹里选中它了')).catch((e) => msg.error(e.message))
}

function askDelete(list, why) {
  if (!list || !list.length) return
  delTargets.value = list
  delWhy.value = why || 'pick'
  delPerm.value = false
  showDel.value = true
}
function askPrune() {
  askDelete(pruneList.value, 'prune')
}
async function doDelete() {
  delBusy.value = true
  try {
    const r = await api.backupDelete(delTargets.value.map((x) => x.name), delPerm.value)
    showDel.value = false
    checked.value = []
    if (r.failed && r.failed.length) {
      msg.warning(r.message + '：' + r.failed.map((f) => f.name + '（' + f.error + '）').join('；'))
    } else {
      msg.success(r.message)
    }
    load()
  } catch (e) {
    msg.error(e.message)
  } finally {
    delBusy.value = false
  }
}

async function openRestore(row) {
  pick.value = row
  showRestore.value = true
  info.value = null
  try {
    info.value = await api.inspect(row.path)
    applyCfg.value = !!info.value?.has_config
    // 包里带索引库就默认勾上 —— 云端状态/标签/影响替换都在索引库里，不勾重扫就重建不出来
    include.value = info.value?.has_index ? ['mods', 'meta'] : ['mods']
  } catch (e) {
    msg.error(e.message)
  }
}
function doRestore() {
  if (!pick.value) return
  const inc_mods = include.value.includes('mods')
  const inc_meta = include.value.includes('meta')
  if (!inc_mods && !inc_meta) return msg.warning('至少要勾一样')
  const apply_config = !!applyCfg.value && !!info.value?.has_config
  if (inc_mods && mode.value === 'overwrite') {
    dialog.error({
      title: '确认覆盖？',
      content: '同名 Mod 会先移入回收站，再写入备份里的版本。这个操作改的是真文件。',
      positiveText: '我确定，覆盖',
      negativeText: '再想想',
      onPositiveClick: () => {
        showRestore.value = false
        startJob('restore', { file: pick.value.path, mode: mode.value, mods: inc_mods,
                              meta: inc_meta, apply_config })
      },
    })
    return
  }
  showRestore.value = false
  startJob('restore', { file: pick.value.path, mode: mode.value, mods: inc_mods,
                        meta: inc_meta, apply_config })
}

function contentCell(r) {
  if (r.kind !== 'zip') return '汇总表（Excel）的历史版本'
  if (r.mods === null || r.mods === undefined) return '读不出内容（可能不是本工具的备份包）'
  const tag = (txt) => h(NTag, { size: 'tiny', bordered: false }, { default: () => txt })
  return h('div', { class: 'cwrap' }, [
    h('span', {}, r.mods + ' Mod ｜ ' + (r.files || 0) + ' 文件'),
    r.has_index ? tag('+索引库') : null,
    r.has_excel ? tag('+汇总表') : null,
    r.has_config ? tag('+配置') : null,
  ].filter(Boolean))
}

const columns = [
  { type: 'selection' },
  {
    title: '备份文件', key: 'name', minWidth: 240, ellipsis: { tooltip: true },
    render: (r) => h('div', { class: 'nmwrap', title: r.name }, [
      h(NTag, { size: 'tiny', bordered: false, type: r.kind === 'zip' ? 'info' : 'default' },
        { default: () => (r.kind === 'zip' ? '整库' : '快照') }),
      h('span', { class: 'nmtext' }, r.name),
    ]),
  },
  {
    title: '大小', key: 'size', width: 96, align: 'right',
    sorter: (a, b) => a.size - b.size, render: (r) => r.human,
  },
  { title: '内容', key: 'content', width: 272, render: contentCell },
  {
    title: '备份时间', key: 'mtime', width: 164,
    sorter: (a, b) => a.mtime - b.mtime, render: (r) => r.created || '—',
  },
  {
    title: '操作', key: 'act', width: 148,
    render: (r) => h(NSpace, { size: 4, wrap: false }, {
      default: () => [
        r.kind === 'zip'
          ? h(NButton, { size: 'tiny', text: true, type: 'primary', onClick: () => openRestore(r) },
            { default: () => '恢复' })
          : null,
        h(NButton, { size: 'tiny', text: true, onClick: () => reveal(r) }, { default: () => '定位' }),
        h(NButton, { size: 'tiny', text: true, type: 'error', onClick: () => askDelete([r]) },
          { default: () => '删除' }),
      ].filter(Boolean),
    }),
  },
]
</script>

<template>
  <div class="pane">
    <n-card size="small" title="备份 / 恢复">
      <template #header-extra>
        <n-space>
          <n-button size="small" @click="showMigrate = true">迁机说明</n-button>
          <n-button size="small" @click="api.open('backup')">打开备份目录</n-button>
          <n-button size="small" @click="load">刷新</n-button>
          <n-button size="small" type="primary" @click="makeBackup">打包备份…</n-button>
        </n-space>
      </template>

      <div class="stat">
        <div class="cell">
          <div class="k">整库备份</div>
          <div class="v">{{ stats.count || 0 }} <span class="u">份</span></div>
          <div class="s">{{ stats.human || '0 B' }}</div>
        </div>
        <div class="cell">
          <div class="k">汇总表快照</div>
          <div class="v">{{ stats.snap_count || 0 }} <span class="u">份</span></div>
          <div class="s">{{ stats.snap_human || '0 B' }}（程序自动留最近 5 份）</div>
        </div>
        <div class="cell grow">
          <div class="k">最近一次备份</div>
          <div class="v">{{ stats.latest || '还没有备份' }}</div>
          <div class="s ell" :title="stats.latest_name">{{ stats.latest_name || '—' }}</div>
        </div>
        <div class="cell grow">
          <div class="k">备份目录</div>
          <div class="v ell" :title="dir">{{ dir || '未设置' }}</div>
          <div class="s">删除默认进回收站，能还原</div>
        </div>
      </div>

      <div class="bar">
        <n-radio-group v-model:value="kind" size="small">
          <n-radio-button value="all">全部 {{ rows.length }}</n-radio-button>
          <n-radio-button value="zip">整库备份 {{ items.length }}</n-radio-button>
          <n-radio-button value="snap">汇总表快照 {{ snaps.length }}</n-radio-button>
        </n-radio-group>
        <n-input v-model:value="kw" size="small" clearable placeholder="按文件名筛选" class="kw" />
        <div class="fill"></div>
        <span class="tip">整库备份只保留最近</span>
        <n-input-number v-model:value="keep" size="small" :min="1" :max="99" class="num" />
        <span class="tip">份</span>
        <n-button size="small" :disabled="!pruneList.length" @click="askPrune">
          清理旧备份<span v-if="pruneList.length">（{{ pruneList.length }}）</span>
        </n-button>
      </div>

      <div v-if="checked.length" class="selbar">
        <span>已选 {{ checked.length }} 项 ｜ 合计 {{ selSize }}</span>
        <n-button size="tiny" type="error" ghost @click="askDelete(selRows)">删除选中</n-button>
        <n-button size="tiny" quaternary @click="checked = []">取消选择</n-button>
      </div>

      <n-spin :show="busy">
        <n-empty v-if="!rows.length"
          :description="(kw || kind !== 'all') ? '没有符合条件的备份' : '还没有备份，点右上角「打包备份」'" />
        <n-data-table v-else :columns="columns" :data="rows" :row-key="(r) => r.name"
          :checked-row-keys="checked" size="small" :scroll-x="980"
          @update:checked-row-keys="(k) => (checked = k)" />
      </n-spin>
    </n-card>

    <!-- 恢复 -->
    <n-modal v-model:show="showRestore" preset="card" style="width: 580px" title="导入备份">
      <n-spin :show="!info">
        <n-alert v-if="info && !info.ok" type="error" :show-icon="false">
          {{ info.error || '这个包读不出来' }}
        </n-alert>
        <template v-else-if="info">
          <div class="rline">
            备份时间 {{ info.created || '未知' }} ｜ {{ info.mods }} 个 Mod ｜ {{ info.files }} 个文件
          </div>
          <div class="rline">
            压缩包 {{ info.zip }}，解开约 {{ info.raw }} ｜ 含
            {{ [info.has_index ? '索引库' : '', info.has_excel ? '汇总表' : ''].filter(Boolean).join(' + ') || '—' }}
          </div>
          <div class="rline dim">
            已归档到云端的 Mod：载荷不在包里，恢复后需要时点「从云盘取回」。
          </div>
          <n-alert v-if="info && (info.archived || info.has_index) && !include.includes('meta')"
                   type="error" :show-icon="false">
            包里含索引库{{ info.archived ? '，其中 ' + info.archived + ' 条 Mod 的载荷已归档到云端' : '' }} ——
            <b>不勾「索引库 + 汇总表」会把云端状态 / 标签 / 影响替换 / 站点版本全丢掉</b>
            （重扫只能重建文件夹层面的信息）。建议勾上。
          </n-alert>
          <div>
            <div class="label">恢复什么</div>
            <n-checkbox-group v-model:value="include">
              <n-space vertical>
                <n-checkbox value="mods">Mod 文件夹</n-checkbox>
                <n-checkbox value="meta">索引库 + 汇总表（<b>迁机 / 想保住云状态·标签就勾上</b>；恢复完会自动重扫重建缺的部分）</n-checkbox>
              </n-space>
            </n-checkbox-group>
          </div>
          <div v-if="info?.has_config" class="cfgbox">
            <n-checkbox v-model:checked="applyCfg">套用备份里的配置（迁机就用这个）</n-checkbox>
            <div class="dim">
              包里带了配置 <b>{{ info.config_keys }}</b> 项（云盘 Cookie、分类顺序、界面偏好…）；
              恢复前会先把你当前配置备份一份，再套用包里的。
              <b>路径类</b>（Mod 根目录 / 汇总表 / 下载 / 暂存 / Penumbra / 备份目录）如果这台电脑上没有，
              会保留当前设置 —— 差异在下面列出来。
            </div>
            <n-alert v-if="info.config_keep && info.config_keep.length" type="warning" :show-icon="false">
              <div>这 {{ info.config_keep.length }} 个路径本机没有，会保留本机的：</div>
              <div v-for="k in info.config_keep" :key="k.key" class="keep">
                · <b>{{ k.key }}</b>：包里 <span class="mono">{{ k.from_pack }}</span>
                → 保留 <span class="mono">{{ k.current || '（空）' }}</span>
              </div>
            </n-alert>
          </div>
          <n-alert v-else-if="info" type="info" :show-icon="false">
            这个包里没有配置（可能是旧版本打的包）—— 恢复完到「设置」里手动填一遍即可。
          </n-alert>

          <div>
            <div class="label">已经存在同名的 Mod 时</div>
            <n-radio-group v-model:value="mode">
              <n-space vertical>
                <n-radio-button value="skip">跳过（最保险，只补齐缺的）</n-radio-button>
                <n-radio-button value="overwrite">覆盖（旧的先进回收站）</n-radio-button>
                <n-radio-button value="rename">另存一份（名字后加「(备份恢复)」）</n-radio-button>
              </n-space>
            </n-radio-group>
          </div>
        </template>
      </n-spin>
      <template #footer>
        <n-space justify="end">
          <n-button size="small" @click="showRestore = false">取消</n-button>
          <n-button size="small" type="primary" :disabled="!info?.ok" @click="doRestore">开始恢复</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 迁机说明 -->
    <n-modal v-model:show="showMigrate" preset="card" style="width: 620px" title="搬到新电脑（迁机）">
      <n-alert type="info" :show-icon="false" style="margin-bottom:10px">
        备份包里已经带了：<b>Mod 文件夹</b>（元数据+图+地址.txt）、<b>索引库</b>、<b>汇总表</b>、
        <b>配置</b>（含云盘 Cookie、分类顺序、界面偏好）。已归档的载荷在网盘里，不用下载。
      </n-alert>
      <ol class="steps">
        <li>新电脑上先装程序：解压部署包（<span class="mono">XMA-Manager-v*.zip</span>）→ 双击
          <span class="mono">ModManagerWeb.exe</span></li>
        <li>「备份 / 恢复」→ 恢复这个备份 zip：勾 <b>Mod 文件夹</b> + <b>索引库 + 汇总表</b>，
          再勾 <b>套用备份里的配置</b>，冲突方式选「跳过已存在」</li>
        <li>路径类设置（Mod 根目录 / 汇总表 / 下载 / 暂存 / Penumbra / 备份目录）：
          新电脑上不一样的会自动<b>保留新电脑当前的</b>，恢复完在「设置」里指到对应目录</li>
        <li>云盘：夸克 Cookie 也带过来了 → 「设置 → 云存储 → 测试连接」确认一下；
          已归档的载荷不用下载，装进游戏时会自动从云端取回</li>
        <li>游戏插件：Dalamud 里装好插件后，管理器「设置 → 游戏插件」点一次
          <b>测试连接 / 自动配对</b>（插件在新电脑上会生成新 Token）</li>
        <li>浏览器拓展（可选）：按说明加载一次，端口填 8765</li>
      </ol>
      <div class="dim">包内也带了一份同样的说明：<span class="mono">迁移到新电脑.txt</span></div>
    </n-modal>

    <!-- 删除 -->
    <n-modal v-model:show="showDel" preset="card" style="width: 540px" title="删除备份">
      <n-space vertical :size="12">
        <n-alert type="warning" :show-icon="false">
          <div v-if="delWhy === 'prune'">
            按「只保留最近 {{ keep }} 份」算下来，下面这些是要清掉的：
          </div>
          <div v-else>要删除的文件：</div>
          <div class="dlist">
            <div v-for="r in delTargets.slice(0, 8)" :key="r.name">
              · {{ r.name }}（{{ r.human }}）
            </div>
            <div v-if="delTargets.length > 8">… 等共 {{ delTargets.length }} 个</div>
          </div>
          <div class="dsum">合计 {{ fmt(bytesOf(delTargets)) }}</div>
        </n-alert>
        <div>
          <div class="label">怎么删</div>
          <n-radio-group v-model:value="delPerm">
            <n-space vertical>
              <n-radio :value="false">移入回收站（推荐，删错了还能在回收站还原）</n-radio>
              <n-radio :value="true">永久删除（不进回收站，不可恢复）</n-radio>
            </n-space>
          </n-radio-group>
        </div>
        <div class="dim" style="font-size: 12px">
          只删备份目录里的 .zip / .xlsx；正在用的汇总表不在删除范围里。
        </div>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button size="small" @click="showDel = false">取消</n-button>
          <n-button size="small" type="error" :loading="delBusy" @click="doDelete">
            删除 {{ delTargets.length }} 个
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.pane {
  height: 100%;
  overflow: auto;
  padding: 16px 18px 24px;
}
.label {
  font-size: 12px;
  opacity: 0.6;
  margin: 8px 0 6px;
}
.dim {
  opacity: 0.65;
}
/* ---- 概览 ---- */
.stat {
  display: grid;
  grid-template-columns: repeat(2, minmax(120px, 0.7fr)) repeat(2, minmax(180px, 1.3fr));
  gap: 1px;
  background: rgba(128, 128, 128, 0.18);
  border: 1px solid rgba(128, 128, 128, 0.18);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 10px;
}
.stat .cell {
  background: var(--n-color, #fff);
  padding: 8px 12px;
  min-width: 0;
}
.stat .k {
  font-size: 12px;
  opacity: 0.6;
}
.stat .v {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.5;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.stat .v .u {
  font-size: 12px;
  font-weight: 400;
  opacity: 0.6;
}
.stat .s {
  font-size: 12px;
  opacity: 0.55;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* ---- 工具条 ---- */
.bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.bar .kw {
  width: 200px;
}
.bar .num {
  width: 76px;
}
.bar .fill {
  flex: 1 1 auto;
}
.tip {
  font-size: 12px;
  opacity: 0.6;
}
.selbar {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 5px 10px;
  margin-bottom: 8px;
  border-radius: 4px;
  background: rgba(32, 128, 240, 0.09);
}
/* ---- 表格里的文件名 ---- */
.nmwrap {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.cwrap {
  display: flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
}
.nmtext {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.dlist {
  margin-top: 4px;
  max-height: 150px;
  overflow: auto;
  line-height: 1.7;
  word-break: break-all;
}
.dsum {
  margin-top: 4px;
  font-weight: 600;
}
.rline {
  font-size: 13px;
  margin-bottom: 4px;
}
.cfgbox {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 6px;
  background: rgba(32, 128, 240, 0.06);
}
.cfgbox .keep {
  font-size: 12px;
  line-height: 1.7;
  word-break: break-all;
}
.mono {
  font-family: Consolas, Menlo, monospace;
  font-size: 12px;
}
.steps {
  margin: 0;
  padding-left: 20px;
  line-height: 1.9;
  font-size: 13px;
}
</style>
