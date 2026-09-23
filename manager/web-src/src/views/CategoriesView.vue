<script setup>
import { ref, computed, inject, onMounted, h } from 'vue'
import {
  NButton, NInput, NSelect, NDataTable, NTag, NCard, NSpace, NModal, NForm, NFormItem,
  NAlert, NEmpty, NSpin, NCheckbox, useMessage,
} from 'naive-ui'
import { api } from '../api'

const emit = defineEmits(['changed'])
const { bus } = inject('mm')
const msg = useMessage()

const cats = ref([])
const stats = ref({})
const busy = ref(false)
const kw = ref('')
const expanded = ref([])

const showNew = ref(false)
const newName = ref('')

const showSub = ref(false)
const subForm = ref({ category: '', zone: 'SFW', name: '' })

const showRename = ref(false)
const renForm = ref({ kind: 'cat', category: '', path: '', old: '', title: '', name: '' })
const renBusy = ref(false)

const showDel = ref(false)
const delTarget = ref(null)
const delAck = ref(false)
const delBusy = ref(false)

async function load() {
  busy.value = true
  try {
    const d = await api.categories()
    cats.value = d.cats || []
    stats.value = d.stats || {}
    if (!expanded.value.length) expanded.value = (d.cats || []).map((c) => 'c:' + c.name)
  } catch (e) {
    msg.error(e.message)
  } finally {
    busy.value = false
  }
}
bus.refresh = load
onMounted(load)

const catOptions = computed(() => cats.value.map((c) => ({ label: c.name, value: c.name })))
const allKeys = computed(() => rows.value.map((r) => r.key))

const rows = computed(() => {
  const k = kw.value.trim().toLowerCase()
  const out = []
  for (const c of cats.value) {
    const subsAll = c.subcats || []
    const catHit = !k || c.name.toLowerCase().includes(k)
    const subs = catHit ? subsAll : subsAll.filter((s) => s.name.toLowerCase().includes(k))
    if (k && !catHit && !subs.length) continue
    out.push({
      key: 'c:' + c.name,
      isSub: false,
      cat: c.name,
      name: c.name,
      count: c.count,
      files: c.files || 0,
      loose: c.loose || 0,
      abs: c.abs,
      zones: c.zones || [],
      on_disk: c.on_disk,
      subCount: subsAll.length,
      children: subs.map((s) => ({
        key: 's:' + c.name + '/' + (s.path || s.name),
        isSub: true,
        cat: c.name,
        name: s.name,
        path: s.path,
        zone: s.zone,
        count: s.count,
        files: s.files || 0,
        abs: s.abs,
        on_disk: s.on_disk,
      })),
    })
  }
  return out
})

async function op(body, okText) {
  try {
    const r = await api.category(body)
    if (okText) msg.success(okText)
    await load()
    emit('changed')
    return r
  } catch (e) {
    msg.error(e.message)
    throw e
  }
}

function createCat() {
  const name = newName.value.trim()
  if (!name) return msg.warning('填个名字')
  op({ action: 'create', name }, `已新建分类「${name}」`).then(() => {
    showNew.value = false
    newName.value = ''
  }).catch(() => {})
}
function openSub(cat) {
  subForm.value = { category: cat || '', zone: 'SFW', name: '' }
  showSub.value = true
}
function addSub() {
  const f = subForm.value
  if (!f.category || !f.name.trim()) return msg.warning('分类和名字都要填')
  op({ action: 'subdir', category: f.category, zone: f.zone, name: f.name.trim() },
    '已新建子分类目录').then(() => {
    showSub.value = false
  }).catch(() => {})
}
function move(i, d) {
  const names = cats.value.map((c) => c.name)
  const j = i + d
  if (j < 0 || j >= names.length) return
  ;[names[i], names[j]] = [names[j], names[i]]
  op({ action: 'order', order: names }).catch(() => {})
}

/* ---- 改名 ---- */
function askRename(r) {
  renForm.value = r.isSub
    ? { kind: 'sub', category: r.cat, path: r.path, old: r.name, title: '子分类改名', name: r.name }
    : { kind: 'cat', category: r.name, path: '', old: r.name, title: '分类改名', name: r.name }
  showRename.value = true
}
async function doRename() {
  const f = renForm.value
  const nn = (f.name || '').trim()
  if (!nn || nn === f.old) return msg.warning('名字没变')
  renBusy.value = true
  try {
    if (f.kind === 'cat') {
      await op({ action: 'rename', name: f.old, new_name: nn }, `已改名：${f.old} → ${nn}`)
    } else {
      await op({ action: 'subdir-rename', category: f.category, path: f.path, new_name: nn },
        `已改名：${f.old} → ${nn}`)
    }
    showRename.value = false
  } catch (e) { /* 已经弹过错误了 */ } finally {
    renBusy.value = false
  }
}

/* ---- 删除 ---- */
function askDelete(r) {
  delTarget.value = r
  delAck.value = false
  showDel.value = true
}
async function doDelete() {
  const r = delTarget.value
  if (!r) return
  delBusy.value = true
  try {
    if (r.isSub) {
      await op({ action: 'subdir-delete', category: r.cat, path: r.path, force: true },
        `子分类「${r.name}」已移入回收站`)
    } else {
      await op({ action: 'delete', name: r.name, force: true },
        `分类「${r.name}」已移入回收站`)
    }
    showDel.value = false
  } catch (e) { /* 已提示 */ } finally {
    delBusy.value = false
  }
}

const columns = [
  {
    title: '名称', key: 'name', minWidth: 240, ellipsis: { tooltip: true },
    render: (r) => h('div', { class: 'nmwrap', title: r.isSub ? (r.path || r.name) : r.name }, [
      h('span', { class: 'nmtext' }, r.name),
      r.isSub && r.zone ? h(NTag, { size: 'tiny', bordered: false, type: 'info' },
        { default: () => r.zone }) : null,
      r.isSub && !r.zone && r.path ? h(NTag, { size: 'tiny', bordered: false },
        { default: () => '分类根下' }) : null,
      !r.on_disk ? h(NTag, { size: 'tiny', bordered: false, type: 'warning' },
        { default: () => '磁盘上没目录' }) : null,
    ].filter(Boolean)),
  },
  {
    title: 'Mod 数', key: 'count', width: 86, align: 'right',
    sorter: (a, b) => (a.count || 0) - (b.count || 0),
    render: (r) => (r.count ? String(r.count) : '—'),
  },
  {
    title: '磁盘文件', key: 'files', width: 96, align: 'right',
    sorter: (a, b) => (a.files || 0) - (b.files || 0),
    render: (r) => (r.files ? String(r.files) : '—'),
  },
  {
    title: '子分类', key: 'subCount', width: 86, align: 'center',
    render: (r) => (r.isSub ? '—' : (r.subCount ? r.subCount + ' 个' : '—')),
  },
  {
    title: 'SFW / NSFW', key: 'zones', width: 110,
    render: (r) => (r.isSub ? '—' : (r.zones.length ? r.zones.join(' + ') : '无（旧布局）')),
  },
  {
    title: '操作', key: 'act', width: 246,
    render: (r) => h(NSpace, { size: 3, wrap: false }, {
      default: (r.isSub
        ? [
          h(NButton, { size: 'tiny', text: true, onClick: () => reveal(r) }, { default: () => '定位' }),
          h(NButton, { size: 'tiny', text: true, onClick: () => askRename(r) }, { default: () => '改名' }),
          h(NButton, { size: 'tiny', text: true, type: 'error', onClick: () => askDelete(r) },
            { default: () => '删除' }),
        ]
        : [
          h(NButton, {
            size: 'tiny', text: true, disabled: indexOfCat(r.cat) === 0,
            onClick: () => move(indexOfCat(r.cat), -1),
          }, { default: () => '↑' }),
          h(NButton, {
            size: 'tiny', text: true, disabled: indexOfCat(r.cat) === cats.value.length - 1,
            onClick: () => move(indexOfCat(r.cat), 1),
          }, { default: () => '↓' }),
          h(NButton, { size: 'tiny', text: true, onClick: () => askRename(r) }, { default: () => '改名' }),
          h(NButton, { size: 'tiny', text: true, type: 'primary', onClick: () => openSub(r.cat) },
            { default: () => '子分类' }),
          h(NButton, { size: 'tiny', text: true, type: 'error', onClick: () => askDelete(r) },
            { default: () => '删除' }),
        ]),
    }),
  },
]

function indexOfCat(name) { return cats.value.findIndex((c) => c.name === name) }
function reveal(r) {
  if (!r.abs) return msg.warning('这个子分类磁盘上没有目录')
  api.open('reveal', r.abs)
    .then(() => msg.success('已经在文件夹里选中它了'))
    .catch((e) => msg.error(e.message))
}
</script>

<template>
  <div class="pane">
    <n-card size="small" title="分类管理">
      <template #header-extra>
        <n-space>
          <n-button size="small" @click="load">刷新</n-button>
          <n-button size="small" @click="openSub('')">新建子分类目录</n-button>
          <n-button size="small" type="primary" @click="showNew = true">新建分类</n-button>
        </n-space>
      </template>

      <div class="stat">
        <div class="cell">
          <div class="k">分类</div>
          <div class="v">{{ stats.cats || 0 }} <span class="u">个</span></div>
          <div class="s">磁盘上 {{ stats.on_disk || 0 }} 个</div>
        </div>
        <div class="cell">
          <div class="k">Mod 合计</div>
          <div class="v">{{ stats.mods || 0 }} <span class="u">条</span></div>
          <div class="s">磁盘文件 {{ stats.files || 0 }} 个</div>
        </div>
        <div class="cell">
          <div class="k">子分类</div>
          <div class="v">{{ stats.subcats || 0 }} <span class="u">个</span></div>
          <div class="s">可按分类、类型管理</div>
        </div>
        <div class="cell">
          <div class="k">空分类</div>
          <div class="v">{{ stats.empty || 0 }} <span class="u">个</span></div>
          <div class="s">没有 Mod 也没有文件</div>
        </div>
      </div>

      <div class="bar">
        <n-input v-model:value="kw" size="small" clearable placeholder="按分类 / 子分类名字筛选" class="kw" />
        <n-button size="small" @click="expanded = allKeys">展开全部</n-button>
        <n-button size="small" @click="expanded = []">收起全部</n-button>
        <div class="fill"></div>
        <span class="tip">↑ ↓ 只改显示顺序（写进配置）</span>
      </div>

      <n-spin :show="busy">
        <n-empty v-if="!rows.length"
          :description="kw ? '没有符合条件的分类' : '一个分类都没有？先看看设置里的 Mod 目录对不对'" />
        <n-data-table v-else :columns="columns" :data="rows" :row-key="(r) => r.key"
          :expanded-row-keys="expanded" size="small" :scroll-x="880"
          @update:expanded-row-keys="(ks) => (expanded = ks)" />
      </n-spin>
      <div class="hint">
        分类 = Mod 根目录下的一级文件夹，下面可以再有 SFW / NSFW 与子分类。
        删除会把整个文件夹（含里面的 Mod）移入回收站，删错了能在回收站还原。
      </div>
    </n-card>

    <!-- 新建分类 -->
    <n-modal v-model:show="showNew" preset="card" style="width: 440px" title="新建分类">
      <n-form size="small" label-placement="left" label-width="70">
        <n-form-item label="分类名">
          <n-input v-model:value="newName" placeholder="例如：挂件" @keyup.enter="createCat" />
        </n-form-item>
      </n-form>
      <n-alert type="info" :show-icon="false">
        会在 Mod 根目录下建「分类名\SFW」和「分类名\NSFW」两个文件夹。
      </n-alert>
      <template #footer>
        <n-space justify="end">
          <n-button size="small" @click="showNew = false">取消</n-button>
          <n-button size="small" type="primary" @click="createCat">创建</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 新建子分类 -->
    <n-modal v-model:show="showSub" preset="card" style="width: 460px" title="新建子分类目录">
      <n-form size="small" label-placement="left" label-width="70">
        <n-form-item label="分类">
          <n-select v-model:value="subForm.category" :options="catOptions" filterable placeholder="选一个分类" />
        </n-form-item>
        <n-form-item label="类型">
          <n-select v-model:value="subForm.zone"
            :options="[{ label: 'SFW', value: 'SFW' }, { label: 'NSFW', value: 'NSFW' }]" />
        </n-form-item>
        <n-form-item label="子分类名">
          <n-input v-model:value="subForm.name" placeholder="例如：纹身" @keyup.enter="addSub" />
        </n-form-item>
      </n-form>
      <n-alert type="info" :show-icon="false">
        建在「分类\类型\子分类名」，Mod 放进去后列表里会显示子分类。
      </n-alert>
      <template #footer>
        <n-space justify="end">
          <n-button size="small" @click="showSub = false">取消</n-button>
          <n-button size="small" type="primary" @click="addSub">创建</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 改名 -->
    <n-modal v-model:show="showRename" preset="card" style="width: 460px" :title="renForm.title">
      <n-form size="small" label-placement="left" label-width="80">
        <n-form-item :label="renForm.kind === 'cat' ? '分类名' : '子分类名'">
          <n-input v-model:value="renForm.name" @keyup.enter="doRename" />
        </n-form-item>
      </n-form>
      <n-alert type="warning" :show-icon="false">
        会真的重命名磁盘上的文件夹（{{ renForm.kind === 'cat' ? renForm.old : renForm.category + ' / ' + renForm.path }}）。
        <template v-if="renForm.kind === 'cat'">里面的 Mod 标签会一起跟着走，改完自动重扫。</template>
        <template v-else>改完自动重扫，里面的 Mod 会按新路径重新归类。</template>
      </n-alert>
      <template #footer>
        <n-space justify="end">
          <n-button size="small" @click="showRename = false">取消</n-button>
          <n-button size="small" type="primary" :loading="renBusy" @click="doRename">改名</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 删除 -->
    <n-modal v-model:show="showDel" preset="card" style="width: 540px"
      :title="delTarget?.isSub ? '删除子分类' : '删除分类'">
      <n-space vertical :size="12">
        <n-alert :type="(delTarget && (delTarget.count || delTarget.files)) ? 'error' : 'warning'" :show-icon="false">
          <div>把「{{ delTarget?.isSub ? delTarget?.cat + ' / ' + delTarget?.path : delTarget?.name }}」整个移入回收站：</div>
          <div class="dsum">
            {{ delTarget?.count || 0 }} 条 Mod ｜ {{ delTarget?.files || 0 }} 个文件
          </div>
          <div v-if="delTarget?.count" class="dwarn">
            ⚠ 里面有 {{ delTarget.count }} 条 Mod，会一起从库里去掉了（回收站还能还原）。
          </div>
        </n-alert>
        <n-checkbox v-if="delTarget && (delTarget.count || delTarget.files)"
          v-model:checked="delAck">
          我知道这些会一起移入回收站
        </n-checkbox>
        <div class="dim" style="font-size: 12px">
          只是移入回收站，没有真删；要恢复就去回收站还原。空目录可以放心删。
        </div>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button size="small" @click="showDel = false">取消</n-button>
          <n-button size="small" type="error" :loading="delBusy"
            :disabled="!!(delTarget && (delTarget.count || delTarget.files) && !delAck)"
            @click="doDelete">
            移入回收站
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
/* ---- 概览 ---- */
.stat {
  display: grid;
  grid-template-columns: repeat(4, minmax(150px, 1fr));
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
  width: 280px;
}
.bar .fill {
  flex: 1 1 auto;
}
.tip {
  font-size: 12px;
  opacity: 0.6;
}
.hint {
  margin-top: 10px;
  font-size: 12px;
  opacity: 0.6;
  line-height: 1.7;
}
.nmwrap {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.nmtext {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.dsum {
  font-weight: 600;
  margin-top: 2px;
}
.dwarn {
  margin-top: 4px;
}
.dim {
  opacity: 0.65;
}
</style>
