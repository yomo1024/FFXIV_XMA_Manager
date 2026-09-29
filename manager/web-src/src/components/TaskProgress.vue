<script setup>
// 弹窗内的进度条（浮层卡片，自己 Teleport 到 body 最顶层）。
//
// 为什么需要它：顶部那条「全局加载条」适合"顺手点一下"，但**弹窗里的按钮**点了之后，
// 视线正停在弹窗上，光看顶上一条细线不够 —— 主人 2026-09：
// 「全局进度条很好，但是对于一些弹窗类的按钮，还是要那种弹窗类的进度条」。
//
// 用法：弹窗的动作用 api.js 的 withDialogProgress('正在 XX', () => 动作()) 包一层即可。
//   · 动作是**任务**（runJob）→ 显示真实百分比 + 文字 + 可取消；
//   · 动作是**同步接口** → 显示来回跑的动画条 + 中文动作名 + 已用秒数。
//
// ⚠ z-index 必须比 naive-ui 的弹窗还高：曾用 n-modal 实现，被弹窗遮罩压住 → 卡片发灰、
//    还叠在弹窗文字上（截图里一眼就看出来）。自己 Teleport + 定死 z-index 最稳。
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { NProgress, NButton, NSpin, useMessage } from 'naive-ui'
import { api, busy } from '../api'

const msg = useMessage()
const job = ref(null)
const now = ref(Date.now())
const cancelling = ref(false)
let tick = null

const show = computed(() => !!busy.dialog)
const run = computed(() => (job.value && job.value.state === 'running') ? job.value : null)
const secs = computed(() => (busy.dlgT0 ? Math.max(0, Math.round((now.value - busy.dlgT0) / 1000)) : 0))
const jobPct = computed(() => (run.value ? run.value.pct : 0))
const jobText = computed(() => (run.value ? run.value.text : ''))
// 任务有没有可报的百分比（total>0）——没有就用动画条，别摆一根不动的 0%
const hasPct = computed(() => !!(run.value && Number(run.value.total) > 0))

// 只建一次、永不销毁（曾在别处用 watch 动态建/清 interval，会半途停跳 → 看着像卡死）
onMounted(() => {
  tick = setInterval(async () => {
    now.value = Date.now()
    if (!busy.dialog) return
    try {
      const s = await api.job()
      job.value = (s && s.state && s.state !== 'idle') ? s : null
    } catch (e) { /* 轮询失败就下次再来，不打扰 */ }
  }, 500)
})
onUnmounted(() => { if (tick) clearInterval(tick) })

async function cancel() {
  cancelling.value = true
  try {
    await api.cancelJob()
    msg.info('正在取消…')
  } catch (e) {
    msg.error(e.message)
  } finally {
    setTimeout(() => { cancelling.value = false }, 1500)
  }
}
</script>

<template>
  <teleport to="body">
    <div v-if="show" class="ovl">
      <div class="mask"></div>
      <div class="dlgprog">
        <div class="hd">
          <n-spin :size="16" />
          <b>{{ busy.dialog }}</b>
          <span class="num dim">已用 {{ secs }}s</span>
        </div>

        <!-- 有任务在跑且有可报的百分比：真实进度 -->
        <template v-if="run && hasPct">
          <n-progress type="line" :percentage="jobPct" :height="10" :border-radius="4" />
          <div class="sub">
            <span class="num">{{ jobPct }}%</span>
            <span class="what" :title="jobText">{{ jobText || '处理中…' }}</span>
          </div>
          <div class="ft">
            <n-button size="tiny" type="error" quaternary :disabled="cancelling" @click="cancel">
              取消这个任务
            </n-button>
          </div>
        </template>

        <!-- 同步接口，或这个任务没报百分比：动画条（不假装知道百分比） -->
        <template v-else>
          <div class="loadbar"><i></i></div>
          <div class="sub">
            <span class="num" v-if="run">{{ run.pct }}%</span>
            <span class="what" :title="run ? run.text : (busy.dlgLabel || busy.label)">
              {{ (run ? (run.text || run.title) : (busy.dlgLabel || busy.label)) || '正在处理' }}…
            </span>
          </div>
          <div class="ft">
            <n-button v-if="run" size="tiny" type="error" quaternary :disabled="cancelling" @click="cancel">
              取消这个任务
            </n-button>
            <span v-else class="dim">这一步没有可报的百分比，但条在动、秒数在走 —— 说明没卡死</span>
          </div>
        </template>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
/* 自己铺满全屏 + 压过所有弹窗（naive-ui 弹窗的 z-index 是动态分配的，这里直接顶到最高档） */
.ovl {
  position: fixed;
  inset: 0;
  z-index: 250000;
  display: flex;
  align-items: center;
  justify-content: center;
}
.mask {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.32);
}
.dlgprog {
  position: relative;
  min-width: 440px;
  max-width: 560px;
  padding: 18px 20px 14px;
  border-radius: 8px;
  background: var(--n-color, #fff);
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.32);
}
.hd {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  font-size: 15px;
}
.hd b { flex: 1 1 auto; min-width: 0; }
.hd .num { flex: 0 0 auto; font-size: 12px; }
.num { font-variant-numeric: tabular-nums; }
.dim { opacity: 0.6; }
.sub {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-top: 8px;
  font-size: 12px;
  min-height: 18px;
}
.sub .what {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  opacity: 0.85;
}
.ft {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  font-size: 12px;
}
.loadbar {
  height: 10px;
  border-radius: 4px;
  background: rgba(128, 128, 128, 0.22);
  overflow: hidden;
  position: relative;
}
.loadbar > i {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 38%;
  border-radius: 4px;
  background: #2080f0;
  animation: loadslide 1.1s ease-in-out infinite;
}
@keyframes loadslide {
  0% { left: -38%; }
  100% { left: 100%; }
}
</style>
