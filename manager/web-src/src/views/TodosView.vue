<script setup>
// 待办聚合页：把散在「待导入 / Mod 列表 / 云存储 / 插件」的待处理事项收在一处，能一键就一键。
// 分组逻辑在 ../todos.js（侧栏角标共用同一份，别在这儿另写一套判据）。
import { ref, computed, h, inject, onMounted } from 'vue'
import {
  NButton, NCard, NDataTable, NSpace, NAlert, NEmpty, NTag, NCheckbox, useMessage, useDialog,
} from 'naive-ui'
import { api, canAutoUpdate, runJob, withDialogProgress } from '../api'
import { buildTodos } from '../todos'
import { mdNodes } from '../md'

const props = defineProps({
  mods: { type: Array, default: () => [] },
  pending: { type: Array, default: () => [] },
})
const emit = defineEmits(['changed', 'go'])
const { startJob } = inject('mm')
const msg = useMessage()
const dialog = useDialog()

const busy = ref('')
const openMap = ref({})
const todo = computed(() => buildTodos(props.mods, props.pending))
const total = computed(() => todo.value.total)
const updAuto = computed(() => (props.mods || []).filter(canAutoUpdate))
const updManual = computed(() => (props.mods || []).filter((m) => m.update_avail && !canAutoUpdate(m)))
const summary = computed(() => todo.value.groups.filter((g) => g.items.length)
  .map((g) => `${g.label} ${g.items.length}`).join(' ｜ '))

// ---- 索引体检（索引 ↔ 磁盘）----
// 单独一块，**不并进 todo.groups**：那些判据必须「只靠 mods/pending 行算得出来」
// （侧栏角标共用同一份 todos.js），这一项要问后端才知道，做成分组会让角标和这里对不上。
const ih = ref(null)
const ihBusy = ref(false)
const ihAlign = ref(true)
const ihBad = computed(() => !!ih.value && ((ih.value.counts || {}).ghost || 0) > 0)
const leafName = (p) => String(p || '').split(/[\\/]/).filter(Boolean).pop() || String(p || '')

async function checkIndex(silent) {
  ihBusy.value = true
  try {
    ih.value = await api.indexHealth()
    if (!silent) {
      const c = ih.value.counts || {}
      msg.info(`索引体检：残留 ${c.ghost || 0} 条（可并入 ${c.merge || 0}、可清理 ${c.orphan || 0}）`
        + `，云端名不一致 ${c.cloud || 0} 条`)
    }
  } catch (e) {
    if (!silent) msg.error('索引体检失败：' + e.message)
  } finally {
    ihBusy.value = false
  }
}

function repairIndex() {
  const v = ih.value || {}
  const merge = v.merge || []
  const orphan = v.orphan || []
  const cloud = v.cloud || []
  const lines = [
    `**要并入现存记录的 ${merge.length} 条**（本地改过名/重排过序号，索引里那条还停在旧路径；`
      + '云端路径、载荷账目、标签都会跟着并过去）',
    ...merge.slice(0, 5).map((x) => `・${leafName(x.folder)} → ${leafName(x.target)}`),
    merge.length > 5 ? `・… 还有 ${merge.length - 5} 条` : '',
    '',
    `**要清掉索引的 ${orphan.length} 条**（本地已经没有这个文件夹，云端也没有它的载荷）`,
    ...orphan.slice(0, 5).map((x) => `・${leafName(x.folder)}`),
    orphan.length > 5 ? `・… 还有 ${orphan.length - 5} 条` : '',
    '',
    `云端还留着载荷的 ${(v.cloud_only || []).length} 条**不动**（归档 / 认领回来的条目）。`,
    '修复**只改索引库，不删任何文件**。',
  ].filter((x) => x !== '' || true).join('\n')
  const content = () => h('div', { style: 'white-space: pre-wrap' }, [
    ...mdNodes(lines),
    cloud.length
      ? h('div', { style: 'margin-top: 12px' }, [
        h(NCheckbox, {
          checked: ihAlign.value,
          'onUpdate:checked': (x) => { ihAlign.value = !!x },
        }, { default: () => `顺带把 ${cloud.length} 个云端目录名改成和本地一致（只改名、不覆盖）` }),
      ])
      : null,
  ])
  dialog.warning({
    title: '修复索引残留',
    content,
    positiveText: '写入修复',
    negativeText: '只看不改',
    onPositiveClick: async () => {
      ihBusy.value = true
      try {
        const r = await withDialogProgress('正在修复索引残留',
          () => api.indexRepair(1, ihAlign.value && cloud.length > 0))
        const cdone = ((r.cloud_align || {}).done || []).length
        msg.success(`索引修复完成：并入 ${(r.merged || []).length} 条、清理 ${(r.dropped || []).length} 条`
          + (cdone ? `、云端目录改名 ${cdone} 个` : '')
          + (((r.failed || []).length) ? `；失败 ${r.failed.length} 条（看日志）` : ''))
        await checkIndex(true)
        emit('changed')
      } catch (e) {
        msg.error('修复失败：' + e.message)
      } finally {
        ihBusy.value = false
      }
    },
  })
}

onMounted(() => checkIndex(true))

function toggle(k) {
  openMap.value = { ...openMap.value, [k]: !openMap.value[k] }
}
function jump(row, g) {
  if (!row || !row.folder) return emit('go', { view: 'pending' })
  emit('go', { view: 'mods', folder: row.folder })
}
// 「操作」列只给能就地做完的两类，其余点行跳过去在 Mod 列表里做
function colsFor(g) {
  const base = [
    { title: '名称', key: 'title', ellipsis: { tooltip: true } },
    { title: '信息', key: 'sub', width: 300, ellipsis: { tooltip: true } },
  ]
  if (g.key === 'install') {
    base.push({
      title: '', key: '_install', width: 108,
      render: (r) => h(NButton, {
        size: 'tiny', type: 'primary', ghost: true,
        onClick: (e) => { e.stopPropagation(); installOne(r) },
      }, { default: () => '装进游戏' }),
    })
  }
  if (g.key === 'cover') {
    base.push({
      title: '', key: '_cover', width: 96,
      render: (r) => h(NButton, {
        size: 'tiny', onClick: (e) => { e.stopPropagation(); fixOne(r) },
      }, { default: () => '补预览图' }),
    })
  }
  return base
}

async function checkUpdates() {
  busy.value = 'check'
  try {
    await withDialogProgress('正在检查更新（逐条读站点）',
      () => runJob('update_check', { folders: [] }))
    msg.info('开始检查更新（只查 XMA / heliosphere）…')
    emit('changed')
  } catch (e) {
    msg.error('启动检查失败：' + e.message)
  } finally {
    setTimeout(() => { busy.value = '' }, 3000)
  }
}

function doUpdate() {
  const list = updAuto.value.map((m) => m.folder)
  const skip = updManual.value
  if (!list.length) {
    return msg.warning(skip.length
      ? `这 ${skip.length} 条没填站点地址，没法自动更新 ——`
        + '去详情里补上站点地址再试，或自己下好再「上传新文件替换」'
      : '当前没有可自动更新的：先点「检查更新」', { duration: 12000 })
  }
  dialog.warning({
    title: `更新 ${list.length} 条（从站点下载最新版覆盖）`,
    content: `将更新：\n${updAuto.value.slice(0, 6).map((m) => '・' + m.name).join('\n')}`
      + (updAuto.value.length > 6 ? `\n… 还有 ${updAuto.value.length - 6} 条` : '')
      + (skip.length ? `\n\n会跳过 ${skip.length} 条（没填站点地址）：\n${skip.slice(0, 4).map((m) => '・' + m.name).join('\n')}` : '')
      + '\n\n旧文件进回收站（可还原）；地址.txt、预览图、编号、标签、影响/替换 都保留。',
    positiveText: '开始更新',
    negativeText: '取消',
    onPositiveClick: async () => {
      busy.value = 'update'
      try {
        await withDialogProgress('正在更新 Mod（下载并替换）',
      () => runJob('mod_update', { folders: list, mode: 'same_name', export: true }))
      } catch (e) {
        msg.error('启动更新失败：' + e.message)
      } finally {
        setTimeout(() => { busy.value = '' }, 4000)
      }
    },
  })
}

function doArchive() {
  const g = todo.value.groups.find((x) => x.key === 'archive')
  const folders = (g ? g.items : []).map((x) => x.folder)
  if (!folders.length) return
  dialog.warning({
    title: `归档 ${folders.length} 条到云盘`,
    content: '上传 + 逐文件校验通过后才会删本地载荷（进回收站，可还原）；'
      + '装进游戏时会自动从云端取回。',
    positiveText: '开始归档',
    negativeText: '取消',
    onPositiveClick: async () => {
      busy.value = 'archive'
      try {
        await withDialogProgress('正在归档到云盘',
        () => runJob('cloud_archive', { folders, delete_local: true }))
      } catch (e) {
        msg.error('启动归档失败：' + e.message)
      } finally {
        setTimeout(() => { busy.value = '' }, 4000)
      }
    },
  })
}

async function doReconcile() {
  busy.value = 'reconcile'
  try {
    await withDialogProgress('正在与网盘对账（只看不改）',
      () => runJob('cloud_reconcile', { folders: [], write: false }))
    msg.info('开始与网盘对账（只看不改，结果在任务条里看）')
  } catch (e) {
    msg.error('启动对账失败：' + e.message)
  } finally {
    setTimeout(() => { busy.value = '' }, 4000)
  }
}

async function installOne(row) {
  busy.value = 'install'
  try {
    const r = await api.bridgePropose(row.folder)
    msg.success(`已送到游戏里：${(r && r.sent && r.sent.name) || row.title}`
      + ' —— 请在游戏内窗口点「确认安装」', { duration: 12000 })
  } catch (e) {
    msg.error('送到游戏失败：' + e.message, { duration: 20000 })
  } finally {
    busy.value = ''
  }
}

async function fixOne(row) {
  busy.value = 'cover'
  try {
    const r = await api.fixCover({ folder: row.folder })
    if (r && r.img) {
      msg.success(`${r.already ? '本来就有预览图' : '已补上预览图'}：${r.name}`)
      emit('changed')
    } else {
      msg.warning('没抓到封面：' + ((r && r.reason) || '未知原因'), { duration: 15000 })
    }
  } catch (e) {
    msg.error('补预览图失败：' + e.message)
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <div class="pane">
    <n-alert type="info" :show-icon="false" style="margin-bottom: 12px">
      待办合计 <b>{{ total }}</b> 项
      <template v-if="total"> —— {{ summary }}</template>
      <template v-else> —— 没什么要做的 👍</template>
    </n-alert>

    <n-card v-if="ih" size="small" class="grp" :class="{ zero: !ihBad }">
      <template #header>
        <span>索引残留（索引 ↔ 磁盘）</span>
        <n-tag size="tiny" :bordered="false" :type="ihBad ? 'warning' : 'success'"
               style="margin-left: 8px">{{ ih.counts.ghost }}</n-tag>
      </template>
      <template #header-extra>
        <n-space :size="6">
          <n-button size="tiny" :loading="ihBusy" @click="checkIndex(false)">重新体检</n-button>
          <n-button size="tiny" type="primary" ghost :disabled="!ihBad"
                    @click="repairIndex">预览并修复</n-button>
        </n-space>
      </template>
      <div class="hintline">
        把索引库和磁盘上的文件夹对一遍：<b>可并入 {{ ih.counts.merge }}</b>
        （本地改过名/重排过序号，索引里那条还停在旧路径）、<b>可清理 {{ ih.counts.orphan }}</b>
        （本地已经没有这个文件夹）、云端目录名不一致 <b>{{ ih.counts.cloud }}</b>、
        云端还留着载荷、不动的 <b>{{ ih.counts.cloud_only }}</b> 条。
      </div>
    </n-card>

    <n-empty v-if="!total" description="全部处理完了，没有待办" style="margin: 48px 0" />

    <n-card v-for="g in todo.groups" v-else :key="g.key" size="small" class="grp"
            :class="{ zero: !g.items.length }">
      <template #header>
        <span>{{ g.label }}</span>
        <n-tag size="tiny" :bordered="false" :type="g.items.length ? 'warning' : 'success'"
               style="margin-left: 8px">{{ g.items.length }}</n-tag>
      </template>
      <template #header-extra>
        <n-space :size="6">
          <n-button v-if="g.key === 'import' && g.items.length" size="tiny"
                    @click="emit('go', { view: 'pending' })">去处理</n-button>
          <n-button v-if="g.key === 'update'" size="tiny" :loading="busy === 'check'"
                    @click="checkUpdates">检查更新</n-button>
          <n-button v-if="g.key === 'update'" size="tiny" type="primary" ghost
                    :disabled="!updAuto.length" @click="doUpdate">全部更新（{{ updAuto.length }}）</n-button>
          <n-button v-if="g.key === 'archive'" size="tiny" type="primary" ghost
                    :disabled="!g.items.length" @click="doArchive">全部归档</n-button>
          <n-button v-if="g.key === 'missing'" size="tiny" :disabled="!g.items.length"
                    @click="doReconcile">与网盘对账（只看不改）</n-button>
          <n-button v-if="g.needInstallDir" size="tiny" type="primary" ghost
                    @click="emit('go', { view: 'settings' })">去设置安装目录</n-button>
          <n-button v-if="g.items.length" size="tiny" quaternary @click="toggle(g.key)">
            {{ openMap[g.key] ? '收起' : '展开' }}
          </n-button>
        </n-space>
      </template>
      <div class="hintline">{{ g.hint }}</div>
      <n-data-table v-if="openMap[g.key] && g.items.length" :columns="colsFor(g)" :data="g.items"
                    size="small" :bordered="false" :max-height="320"
                    :row-props="(r) => ({ style: 'cursor:pointer', onClick: () => jump(r, g) })" />
      <div v-if="openMap[g.key] && g.key === 'install' && g.items.length" class="hintline">
        安装是逐条的（插件一次装一条，避免游戏里排队）；点某一行会跳到 Mod 列表选中它。
      </div>
    </n-card>
  </div>
</template>

<style scoped>
.pane {
  height: 100%;
  overflow: auto;
  padding: 16px 18px 24px;
}
.grp {
  margin-bottom: 10px;
}
.grp.zero {
  opacity: 0.6;
}
.hintline {
  font-size: 12px;
  opacity: 0.68;
  margin: 2px 0 8px;
}
</style>
