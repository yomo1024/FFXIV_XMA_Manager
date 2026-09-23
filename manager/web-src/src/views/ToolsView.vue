<script setup>
import { ref, computed, inject, onMounted } from 'vue'
import {
  NButton, NInput, NSelect, NDataTable, NTag, NCard, NTabs, NTabPane, NSpace, NAlert,
  NInputNumber, NEmpty, NSpin, useMessage, useDialog,
} from 'naive-ui'
import { api } from '../api'

const props = defineProps({ mods: { type: Array, default: () => [] } })
const emit = defineEmits(['changed'])
const { state, startJob, bus } = inject('mm')
const msg = useMessage()
const dialog = useDialog()

const tab = ref('dupes')
const busy = ref(false)
const dupes = ref([])
const install = ref(null)
const report = ref(null)
const installDir = ref('')
const plan = ref([])
const renum = ref({ category: '', subcat: '', start: 1 })

async function loadAll() {
  busy.value = true
  try {
    const [d, i, c] = await Promise.all([api.dupes(), api.install(), api.check()])
    dupes.value = d.groups || []
    install.value = i
    installDir.value = i.dir || ''
    report.value = c
  } catch (e) {
    msg.error(e.message)
  } finally {
    busy.value = false
  }
}
bus.refresh = loadAll
onMounted(loadAll)

const catOptions = computed(() => {
  const s = new Set(props.mods.map((m) => m.category))
  return [...s].map((x) => ({ label: x, value: x }))
})

// ---------------- 查重
async function delDup(rows) {
  if (!rows.length) return
  dialog.warning({
    title: '删除重复的 Mod',
    content: '移入回收站：\n' + rows.map((r) => '· ' + r.rel).join('\n'),
    positiveText: '移入回收站',
    negativeText: '取消',
    onPositiveClick: async () => {
      busy.value = true
      for (const r of rows) {
        try {
          await api.deleteMod({ folder: r.folder })
        } catch (e) {
          msg.error(e.message)
        }
      }
      busy.value = false
      msg.success('处理完了')
      emit('changed')
      await loadAll()
    },
  })
}

const dupColumns = [
  { title: '分类', key: 'category', width: 80 },
  { title: '序号', key: 'seq', width: 60, align: 'center' },
  { title: '名称', key: 'name', ellipsis: { tooltip: true } },
  { title: '作者', key: 'author', width: 110, ellipsis: { tooltip: true } },
  { title: '路径', key: 'rel', ellipsis: { tooltip: true } },
  {
    title: '', key: 'act', width: 90,
    render: (r) => null,
  },
]

// ---------------- 安装检查
async function saveInstallDir() {
  try {
    await api.saveSettings({ install_dir: installDir.value.trim() })
    msg.success('安装目录已保存')
    await loadAll()
    emit('changed')
  } catch (e) {
    msg.error(e.message)
  }
}

// ---------------- 序号重排
async function previewRenum() {
  try {
    const r = await api.renumberPreview({ category: renum.value.category, start: renum.value.start })
    plan.value = r.plan
    if (!r.plan.length) msg.info('这个范围里的序号已经是连续的了，不用改')
  } catch (e) {
    msg.error(e.message)
  }
}
function applyRenum() {
  if (!plan.value.length) return
  dialog.warning({
    title: '确认重排序号',
    content: `会重命名 ${plan.value.length} 个文件夹（把序号改成连续的 1..N）。`,
    positiveText: '开始重排',
    negativeText: '取消',
    onPositiveClick: () => {
      startJob('renumber', { category: renum.value.category, start: renum.value.start })
      plan.value = []
    },
  })
}
const planColumns = [
  { title: '现在', key: 'old', width: 70, align: 'center' },
  { title: '改成', key: 'new', width: 70, align: 'center' },
  { title: '名称', key: 'name', ellipsis: { tooltip: true } },
  { title: '路径', key: 'rel', ellipsis: { tooltip: true } },
]
const rcols = [
  { title: '分类', key: 'category', width: 80 },
  { title: '序号', key: 'seq', width: 60, align: 'center' },
  { title: '名称', key: 'name', ellipsis: { tooltip: true } },
  { title: '问题', key: 'issues', render: (r) => r.issues.join('；') },
]
</script>

<template>
  <div class="pane">
    <n-tabs v-model:value="tab" type="line" animated>
      <!-- 查重 -->
      <n-tab-pane name="dupes" :tab="`查重${dupes.length ? '（' + dupes.length + '）' : ''}`">
        <n-spin :show="busy">
          <n-alert v-if="!dupes.length" type="success" :show-icon="false"
                   style="margin-bottom: 10px">没有发现重复的 Mod。</n-alert>
          <n-card v-for="(g, i) in dupes" :key="i" size="small" style="margin-bottom: 10px"
                  :title="`${g.reason}：${g.detail}`">
            <n-data-table :columns="dupColumns" :data="g.mods" size="small" :bordered="false" />
            <template #footer>
              <n-space justify="end">
                <n-button size="tiny" @click="delDup(g.mods.slice(1))">
                  只留第一个，其余进回收站
                </n-button>
                <n-button size="tiny" @click="delDup([g.mods[0]])">删第一个</n-button>
              </n-space>
            </template>
          </n-card>
        </n-spin>
      </n-tab-pane>

      <!-- 安装检查 -->
      <n-tab-pane name="install" tab="安装检查">
        <n-card size="small" title="Penumbra 的 Mods 目录">
          <n-space vertical>
            <n-space>
              <n-input v-model:value="installDir" placeholder="例如 %APPDATA%\XIVLauncher\pluginConfigs\Penumbra\Mods"
                       style="width: 560px" size="small" />
              <n-button size="small" type="primary" @click="saveInstallDir">保存</n-button>
            </n-space>
            <n-alert v-if="install" :type="install.ok ? 'success' : 'warning'" :show-icon="false">
              <template v-if="install.ok">
                目录里有 {{ install.folders }} 个文件夹 ｜ 已安装 {{ install.installed }} ｜
                未安装 {{ install.missing.length }}（共 {{ install.total }}）
              </template>
              <template v-else>
                还没设置好安装目录（或目录不存在）。设置后，列表里「是否安装」会变绿。
              </template>
            </n-alert>
            <n-data-table v-if="install?.missing?.length" :columns="rcols" size="small"
                          :data="install.missing" :max-height="360" :scroll-x="700" />
          </n-space>
        </n-card>
      </n-tab-pane>

      <!-- 检查报告 -->
      <n-tab-pane name="check" tab="检查报告">
        <n-spin :show="busy">
          <n-alert v-if="report?.clean" type="success" :show-icon="false">
            {{ report.total }} 条全部正常：地址、预览图都在，序号也没重。
          </n-alert>
          <template v-else>
            <n-alert type="warning" :show-icon="false" style="margin-bottom: 10px">
              共 {{ report?.total }} 条，{{ report?.problems.length }} 条要看一下，
              {{ report?.dup_seqs.length }} 组序号重复。
            </n-alert>
            <n-data-table :columns="rcols" size="small" :data="report?.problems || []"
                          :max-height="420" :scroll-x="700" />
          </template>
        </n-spin>
      </n-tab-pane>

      <!-- 自动序号 -->
      <n-tab-pane name="renum" tab="自动分配序号">
        <n-card size="small" title="把某个分类的序号重排成连续的 1..N">
          <n-space vertical>
            <n-space align="center">
              <n-select v-model:value="renum.category" :options="catOptions" size="small"
                        placeholder="选分类（留空=每个分类各自编号）" clearable style="width: 240px" />
              <n-input-number v-model:value="renum.start" :min="1" size="small"
                              style="width: 120px" placeholder="起始序号" />
              <n-button size="small" @click="previewRenum">预览要改哪些</n-button>
              <n-button size="small" type="primary" :disabled="!plan.length" @click="applyRenum">
                执行（{{ plan.length }}）
              </n-button>
            </n-space>
            <n-data-table v-if="plan.length" :columns="planColumns" :data="plan" size="small"
                          :max-height="380" :scroll-x="700" />
            <n-empty v-else description="点「预览要改哪些」看看要不要动" />
          </n-space>
        </n-card>
      </n-tab-pane>
    </n-tabs>
  </div>
</template>

<style scoped>
.pane {
  height: 100%;
  overflow: auto;
  padding: 16px 18px 24px;
}
</style>
