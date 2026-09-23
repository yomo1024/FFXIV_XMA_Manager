<script setup>
import { ref, inject, onMounted } from 'vue'
import {
  NButton, NDataTable, NCard, NSpace, NModal, NRadioGroup, NRadioButton, NCheckbox,
  NCheckboxGroup, NAlert, NSpin, NEmpty, useMessage, useDialog,
} from 'naive-ui'
import { api } from '../api'

const { startJob, bus } = inject('mm')
const msg = useMessage()
const dialog = useDialog()

const items = ref([])
const dir = ref('')
const busy = ref(false)
const showRestore = ref(false)
const pick = ref(null)
const info = ref(null)
const mode = ref('skip')
const include = ref(['mods'])

async function load() {
  busy.value = true
  try {
    const d = await api.backups()
    items.value = d.items || []
    dir.value = d.dir
  } catch (e) {
    msg.error(e.message)
  } finally {
    busy.value = false
  }
}
bus.refresh = load
onMounted(load)

function makeBackup() {
  dialog.warning({
    title: '打包备份',
    content: '把整个 Mod 库（Mod 文件夹 + 索引库 + 汇总表）打成一个 zip。\n2.4 GB 的库大概要一两分钟，开始后可以看到进度、也能取消。',
    positiveText: '开始',
    negativeText: '取消',
    onPositiveClick: () => startJob('backup', {}),
  })
}

async function openRestore(row) {
  pick.value = row
  showRestore.value = true
  info.value = null
  try {
    info.value = await api.inspect(row.path)
  } catch (e) {
    msg.error(e.message)
  }
}
function doRestore() {
  if (!pick.value) return
  const inc_mods = include.value.includes('mods')
  const inc_meta = include.value.includes('meta')
  if (!inc_mods && !inc_meta) return msg.warning('至少要勾一样')
  if (inc_mods && mode.value === 'overwrite') {
    dialog.error({
      title: '确认覆盖？',
      content: '同名 Mod 会先移入回收站，再写入备份里的版本。这个操作改的是真文件。',
      positiveText: '我确定，覆盖',
      negativeText: '再想想',
      onPositiveClick: () => {
        showRestore.value = false
        startJob('restore', { file: pick.value.path, mode: mode.value, mods: inc_mods, meta: inc_meta })
      },
    })
    return
  }
  showRestore.value = false
  startJob('restore', { file: pick.value.path, mode: mode.value, mods: inc_mods, meta: inc_meta })
}

const columns = [
  { title: '备份文件', key: 'name', ellipsis: { tooltip: true } },
  { title: '备份时间', key: 'created', width: 160 },
  { title: '大小', key: 'human', width: 90 },
  { title: 'Mod', key: 'mods', width: 60, align: 'center' },
  { title: '文件', key: 'files', width: 60, align: 'center' },
  {
    title: '含', key: 'has', width: 120,
    render: (r) => [r.has_index ? '索引库' : '', r.has_excel ? '汇总表' : '']
      .filter(Boolean).join(' + ') || '—',
  },
  {
    title: '', key: 'act', width: 150,
    render: (r) => null,
  },
]
</script>

<template>
  <div class="pane">
    <n-card size="small" title="备份 / 恢复">
      <template #header-extra>
        <n-space>
          <n-button size="small" @click="api.open('backup')">打开备份目录</n-button>
          <n-button size="small" @click="load">刷新</n-button>
          <n-button size="small" type="primary" @click="makeBackup">打包备份…</n-button>
        </n-space>
      </template>
      <n-alert type="info" :show-icon="false" style="margin-bottom: 10px">
        备份目录：{{ dir }} ｜ 恢复时「跳过已存在」最保险；覆盖会把旧文件夹移入回收站。
      </n-alert>
      <n-spin :show="busy">
        <n-empty v-if="!items.length" description="还没有备份，点右上角「打包备份」" />
        <template v-else>
          <n-data-table :columns="columns" :data="items" size="small" :scroll-x="900" />
          <div style="margin-top: 10px">
            <n-space v-for="r in items" :key="r.path" align="center" style="margin-bottom: 6px">
              <n-button size="tiny" type="primary" @click="openRestore(r)">恢复这个备份</n-button>
              <span style="font-size: 12px; opacity: 0.6">{{ r.name }}</span>
            </n-space>
          </div>
        </template>
      </n-spin>
    </n-card>

    <n-modal v-model:show="showRestore" preset="card" style="width: 560px" title="导入备份">
      <n-spin :show="!info">
        <n-space vertical>
          <n-alert type="info" :show-icon="false">
            {{ pick?.name }}<br />
            备份时间 {{ info?.created || '未知' }} ｜ {{ info?.mods }} 个 Mod ｜
            {{ info?.files }} 个文件 ｜ 解压后 {{ info?.raw }} ｜ zip {{ info?.zip }}<br />
            包含：{{ info?.has_index ? '索引库 ' : '' }}{{ info?.has_excel ? '汇总表 ' : '' }}
            ｜ 分类：{{ (info?.cats || []).join('、') || '—' }}
          </n-alert>

          <div>
            <div class="label">恢复内容</div>
            <n-checkbox-group v-model:value="include">
              <n-space vertical>
                <n-checkbox value="mods">Mod 文件夹（解压回 Mod 根目录）</n-checkbox>
                <n-checkbox value="meta">索引库 + 汇总表（一般不用勾，恢复完会自动重扫重建）</n-checkbox>
              </n-space>
            </n-checkbox-group>
          </div>

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
        </n-space>
      </n-spin>
      <template #footer>
        <n-space justify="end">
          <n-button size="small" @click="showRestore = false">取消</n-button>
          <n-button size="small" type="primary" :disabled="!info?.ok" @click="doRestore">
            开始恢复
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
</style>
