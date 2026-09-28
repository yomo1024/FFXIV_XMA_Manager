// 极简 markdown → VNode：只认 **粗体** / `代码` / 换行，够我们界面用。
//
// 为什么需要：以前界面文案里写了一堆 `**加粗**`、反引号，但 Vue 不解析 markdown →
// 那些字符原样显示出来（主人：'根本没达到效果'）。
// 这里**只用 VNode 拼**，不走 innerHTML/v-html → 不存在注入问题。
import { h } from 'vue'

const RE = /\*\*([^*\n]+)\*\*|`([^`\n]+)`/g
const B_STYLE = 'font-weight: 600'
const C_STYLE = 'padding: 0 4px; border-radius: 4px; background: rgba(128,128,128,.18); font-size: 12px'

/** 把一段文本转成 VNode 数组（**粗体** / `代码` / \n 换行） */
export function mdNodes(text) {
  const s = String(text == null ? '' : text)
  const out = []
  const pushText = (t) => {
    if (!t) return
    const parts = t.split('\n')
    parts.forEach((seg, i) => {
      if (i) out.push(h('br'))
      if (seg) out.push(seg)
    })
  }
  let last = 0
  let m
  RE.lastIndex = 0
  while ((m = RE.exec(s)) !== null) {
    pushText(s.slice(last, m.index))
    if (m[1] !== undefined) out.push(h('b', { style: B_STYLE }, m[1]))
    else out.push(h('code', { style: C_STYLE }, m[2]))
    last = RE.lastIndex
  }
  pushText(s.slice(last))
  return out
}

/** 组件：<MdText :text="s" /> 或 h(MdText, { text: s }) */
export const MdText = {
  name: 'MdText',
  props: { text: { type: [String, Number], default: '' } },
  render() {
    return h('span', { style: 'white-space: pre-wrap' }, mdNodes(this.text))
  },
}

/** dialog.*({ content }) 用：naive-ui 的 content 支持渲染函数 */
export const mdDialog = (text) => () => h('div', { style: 'white-space: pre-wrap' }, mdNodes(text))

/** msg.success/info/warning/error 用：naive-ui 的消息内容支持渲染函数 */
export const mdToast = (text) => () => h(MdText, { text })
