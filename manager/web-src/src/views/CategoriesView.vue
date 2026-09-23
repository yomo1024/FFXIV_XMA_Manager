<script setup>
import { ref, computed, inject, onMounted } from 'vue'
import {
  NButton, NInput, NSelect, NDataTable, NTag, NCard, NSpace, NModal, NForm, NFormItem,
  NAlert, NEmpty, NSpin, useMessage, useDialog,
} from 'naive-ui'
import { api } from '../api'

const emit = defineEmits(['changed'])
const { bus } = inject('mm')
const msg = useMessage()
const dialog = useDialog()

const cats = ref([])
const busy = ref(false)
const showNew = ref(false)
const showSub = ref(false)
const newName = ref('')
const subForm = ref({ category: '', zone: 'SFW', name: '' })

async function load() {
  busy.value = true
  try {
    cats.value = (await api.categories()).cats
  } catch (e) {
    msg.error(e.message)
  } finally {
    busy.value = false
  }
}
bus.refresh = load
onMounted(load)

const catOptions = computed(() => cats.value.map((c) => ({ label: c.name, value: c.name })))

async function op(body, okText) {
  try {
    await api.category(body)
    if (okText) msg.success(okText)
    await load()
    emit('changed')
  } catch (e) {
    msg.error(e.message)
  }
}

function createCat() {
  const name = newName.value.trim()
  if (!name) return msg.warning('填个名字')
  op({ action: 'create', name }, `已新建分类「${name}」`).then(() => {
    showNew.value = false
    newName.value = ''
  })
}
function renameCatPrompt(c) {
  const nv = window.prompt('新的分类名（会真的重命名文件夹）', c.name)
  if (!nv || nv.trim() === c.name) return
  op({ action: 'rename', name: c.name, new_name: nv.trim() }, '已改名：' + nv.trim())
}
function delCat(c) {
  dialog.warning({
    title: '删除分类',
    content: `分类「${c.name}」当前有 ${c.count} 条 Mod。` +
      (c.count ? '\n里面还有文件，会整个移入回收站，确定吗？' : '\n这个分类是空的，直接删掉。'),
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: () => op({ action: 'delete', name: c.name, force: true },
                              `已删除「${c.name}」`),
  })
}
function move(i, d) {
  const names = cats.value.map((c) => c.name)
  const j = i + d
  if (j < 0 || j >= names.length) return
  ;[names[i], names[j]] = [names[j], names[i]]
  op({ action: 'order', order: names })
}
function addSub() {
  const f = subForm.value
  if (!f.category || !f.name.trim()) return msg.warning('分类和名字都要填')
  op({ action: 'subdir', category: f.category, zone: f.zone, name: f.name.trim() },
     '已新建子分类目录').then(() => {
    showSub.value = false
    subForm.value = { category: '', zone: 'SFW', name: '' }
  })
}
</script>

<template>
  <div class="pane">
    <n-card size="small" title="分类管理">
      <template #header-extra>
        <n-space>
          <n-button size="small" @click="showSub = true">新建子分类目录</n-button>
          <n-button size="small" type="primary" @click="showNew = true">新建分类</n-button>
        </n-space>
      </template>
      <n-alert type="info" :show-icon="false" style="margin-bottom: 10px">
        分类就是 Mod 根目录下的一级文件夹；上下箭头只改显示顺序（写进配置）。
        删分类会把整个文件夹移入回收站。
      </n-alert>
      <n-spin :show="busy">
        <n-empty v-if="!cats.length" description="一个分类都没有？先看看设置里的 Mod 目录对不对" />
        <div v-for="(c, i) in cats" :key="c.name" class="row">
          <b class="name">{{ c.name }}</b>
          <n-tag size="small" :bordered="false">{{ c.count }} 条</n-tag>
          <n-tag v-if="!c.on_disk" size="small" type="warning" :bordered="false">磁盘上没有</n-tag>
          <n-tag v-for="s in c.subcats" :key="s.name" size="small" type="info" :bordered="false">
            {{ s.name }} {{ s.count }}
          </n-tag>
          <div class="grow"></div>
          <n-button size="tiny" quaternary :disabled="i === 0" @click="move(i, -1)">↑</n-button>
          <n-button size="tiny" quaternary :disabled="i === cats.length - 1" @click="move(i, 1)">↓</n-button>
          <n-button size="tiny" @click="renameCatPrompt(c)">改名</n-button>
          <n-button size="tiny" type="error" quaternary @click="delCat(c)">删除</n-button>
        </div>
      </n-spin>
    </n-card>

    <n-modal v-model:show="showNew" preset="card" style="width: 420px" title="新建分类">
      <n-form size="small" label-placement="left" label-width="70">
        <n-form-item label="分类名">
          <n-input v-model:value="newName" placeholder="例如：挂件" />
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

    <n-modal v-model:show="showSub" preset="card" style="width: 460px" title="新建子分类目录">
      <n-form size="small" label-placement="left" label-width="70">
        <n-form-item label="分类">
          <n-select v-model:value="subForm.category" :options="catOptions" filterable />
        </n-form-item>
        <n-form-item label="类型">
          <n-select v-model:value="subForm.zone" :options="[{ label: 'SFW', value: 'SFW' }, { label: 'NSFW', value: 'NSFW' }]" />
        </n-form-item>
        <n-form-item label="子分类名">
          <n-input v-model:value="subForm.name" placeholder="例如：纹身" />
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
  </div>
</template>

<style scoped>
.pane {
  height: 100%;
  overflow: auto;
  padding: 16px 18px 24px;
}
.row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 4px;
  border-bottom: 1px solid rgba(128, 128, 128, 0.12);
}
.name {
  min-width: 120px;
}
.grow {
  flex: 1 1 auto;
}
</style>
