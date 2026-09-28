// 「待办」聚合：把散在各页的待处理事项收成一处。
// 唯一来源 —— 侧栏角标（AppShell）和待办页（TodosView）都调它，别在两处各写一套。
//
// 判据全部来自 /api/mods 的行 + /api/pending 的文件，不需要额外接口。

function rowOf(m) {
  return {
    id: m.folder,
    folder: m.folder,
    title: m.name || m.folder,
    sub: [m.category, m.subcat, m.author, m.nsfw].filter(Boolean).join(' ｜ '),
  }
}

export function buildTodos(mods, pending) {
  const M = mods || []
  const P = pending || []
  // installed === null 表示「压根没配游戏安装目录」→ 整组改成引导，别列一堆假的「没装」
  const hasInstallDir = M.some((m) => m.installed === true || m.installed === false)

  const groups = [
    {
      key: 'import',
      label: '待导入文件',
      hint: '下载目录 / 暂存目录里还没入库的 Mod 文件',
      items: P.map((x) => ({
        id: x.src,
        folder: '',
        title: x.file,
        sub: [x.where, x.size_h, x.author, x.name].filter(Boolean).join(' ｜ '),
      })),
      action: 'pending',
    },
    {
      key: 'update',
      label: '有新版',
      hint: '站点上已有更新的版本（拿不到直链的会在弹窗里单独列出来）',
      items: M.filter((m) => m.update_avail).map(rowOf),
      action: 'update',
    },
    {
      key: 'install',
      label: '没装进游戏',
      hint: hasInstallDir ? '本地库里有、游戏里没有' : '还没设置安装目录 —— 先去设置里填',
      items: hasInstallDir ? M.filter((m) => m.installed === false).map(rowOf) : [],
      action: 'install',
      needInstallDir: !hasInstallDir,
    },
    {
      key: 'archive',
      label: '没归档到云盘',
      hint: '本地还占着载荷（归档=上传+校验通过才删本地）',
      items: M.filter((m) => (m.payload_size || 0) > 0 && m.cloud_state !== 'archived').map(rowOf),
      action: 'archive',
    },
    {
      key: 'missing',
      label: '云端找不到',
      hint: '记着已归档，但网盘上没见到文件 —— 用「与网盘对账」按云端实况重建',
      items: M.filter((m) => m.cloud_state === 'missing').map(rowOf),
      action: 'reconcile',
    },
    {
      key: 'cover',
      label: '没预览图',
      hint: '列表 / 详情里没有图',
      items: M.filter((m) => !m.has_img).map(rowOf),
      action: 'cover',
    },
    {
      key: 'meta',
      label: '资料不全',
      hint: '缺站点地址或标签（会影响「检查更新」和搜索）',
      items: M.filter((m) => !(m.addr || '').trim() || !(m.tags || []).length).map((m) => ({
        ...rowOf(m),
        sub: [!m.addr ? '缺站点地址' : '', !(m.tags || []).length ? '缺标签' : ''].filter(Boolean).join('、'),
      })),
      action: '',
    },
  ]
  const total = groups.reduce((s, g) => s + g.items.length, 0)
  return { groups, total }
}
