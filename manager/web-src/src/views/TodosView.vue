<script setup>
// 待办聚合页：把散在「待导入 / Mod 列表 / 云存储 / 插件」的待处理事项收在一处，能一键就一键。
// 分组逻辑在 ../todos.js（侧栏角标共用同一份，别在这儿另写一套判据）。
import { ref, computed, h, inject } from 'vue'
import {
  NButton, NCard, NDataTable, NSpace, NAlert, NEmpty, NTag, useMessage, useDialog,
} from 'naive-ui'
import { api, canAutoUpdate } from '../api'
import { buildTodos } from '../todos'

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
    await startJob('update_check', { folders: [] })
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
      ? `这 ${skip.length} 条拿不到下载直链（heliosphere 或没填站点地址）——`
        + '去详情里点「打开页面下载」，下好再「上传新文件替换」'
      : '当前没有可自动更新的：先点「检查更新」', { duration: 12000 })
  }
  dialog.warning({
    title: `更新 ${list.length} 条（从站点下载最新版覆盖）`,
    content: `将更新：\n${updAuto.value.slice(0, 6).map((m) => '・' + m.name).join('\n')}`
      + (updAuto.value.length > 6 ? `\n… 还有 ${updAuto.value.length - 6} 条` : '')
      + (skip.length ? `\n\n会跳过 ${skip.length} 条（拿不到直链）：\n${skip.slice(0, 4).map((m) => '・' + m.name).join('\n')}` : '')
      + '\n\n旧文件进回收站（可还原）；地址.txt、预览图、编号、标签、影响/替换 都保留。',
    positiveText: '开始更新',
    negativeText: '取消',
    onPositiveClick: async () => {
      busy.value = 'update'
      try {
        await startJob('mod_update', { folders: list, mode: 'same_name', export: true })
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
        await startJob('cloud_archive', { folders, delete_local: true })
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
    await startJob('cloud_reconcile', { folders: [], write: false })
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
