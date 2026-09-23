<script setup>
import { ref, computed, inject, onMounted } from 'vue'
import {
  NButton, NDataTable, NCard, NSpace, NAlert, NSpin, NEmpty, NSelect, NSwitch,
  NInput, useMessage,
} from 'naive-ui'
import { api } from '../api'

const emit = defineEmits(['changed'])
const { startJob, bus } = inject('mm')
const msg = useMessage()

const items = ref([])
const dl = ref('')
const ib = ref('')
const busy = ref(false)
const checked = ref([])
const target = ref({ category: '', zone: 'SFW', subcat: '', move: true })
const cats = ref([])

async function load() {
  busy.value = true
  try {
    const d = await api.pending()
    items.value = d.items || []
    dl.value = d.download_dir
    ib.value = d.inbox_dir
    cats.value = (await api.categories()).cats
  } catch (e) {
    msg.error(e.message)
  } finally {
    busy.value = false
  }
}
bus.refresh = load
onMounted(load)

const catOptions = computed(() => cats.value.map((c) => ({ label: `${c.name}（${c.count}）`, value: c.name })))
const allFiles = computed(() => items.value.map((i) => i.src))

function doImport() {
  const files = checked.value.length ? checked.value : []
  if (!files.length) return msg.warning('先勾要导入的文件')
  if (!target.value.category) return msg.warning('先选个分类')
  startJob('import', { files, category: target.value.category, zone: target.value.zone,
                       subdir: target.value.subcat || '', move: target.value.move })
  checked.value = []
}

const columns = [
  { type: 'selection' },
  { title: '文件', key: 'file', ellipsis: { tooltip: true } },
  { title: '来源', key: 'where', width: 70 },
  { title: '大小', key: 'size_h', width: 90 },
  { title: '下载时间', key: 'mtime_h', width: 110 },
  { title: '推测作者', key: 'author', width: 120, ellipsis: { tooltip: true } },
  { title: '推测名称', key: 'name', ellipsis: { tooltip: true } },
  { title: '路径', key: 'src', ellipsis: { tooltip: true } },
]
</script>

<template>
  <div class="pane">
    <n-card size="small" title="待导入（下载目录 + 暂存目录）">
      <template #header-extra>
        <n-space>
          <n-button size="small" @click="api.open('downloads')">打开下载目录</n-button>
          <n-button size="small" @click="api.open('inbox')">打开暂存目录</n-button>
          <n-button size="small" @click="load">刷新</n-button>
        </n-space>
      </template>
      <n-alert type="info" :show-icon="false" style="margin-bottom: 10px">
        下载目录：{{ dl || '—' }}<br />暂存目录：{{ ib || '—' }}
      </n-alert>

      <n-spin :show="busy">
        <n-empty v-if="!items.length"
                 description="这里空着：下载目录/暂存目录里没有 .zip/.7z/.rar/.ttmp2 之类的 Mod 文件" />
        <template v-else>
          <n-space align="center" style="margin-bottom: 10px" :wrap="true">
            <n-select v-model:value="target.category" :options="catOptions" size="small"
                      placeholder="导入到哪个分类" style="width: 200px" />
            <n-select v-model:value="target.zone" size="small" style="width: 110px"
                      :options="[{ label: 'SFW', value: 'SFW' }, { label: 'NSFW', value: 'NSFW' }]" />
            <n-input v-model:value="target.subcat" size="small" placeholder="子分类（可空）"
                     style="width: 150px" />
            <n-switch v-model:value="target.move" size="small" />
            <span style="font-size: 12px; opacity: 0.65">
              {{ target.move ? '移动（删掉原文件）' : '复制（保留原文件）' }}
            </span>
            <n-button size="small" @click="checked = allFiles">全选</n-button>
            <n-button size="small" type="primary" @click="doImport">
              导入选中（{{ checked.length }}）
            </n-button>
          </n-space>
          <n-data-table :columns="columns" :data="items" size="small" :scroll-x="1000"
                        :row-key="(r) => r.src" :checked-row-keys="checked"
                        @update:checked-row-keys="(k) => (checked = k)" :max-height="420" />
        </template>
      </n-spin>
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
