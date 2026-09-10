const bridge = window.AstrBotPluginPage;

const state = {
  tab: "overview",
  page: 1,
  pageSize: 12,
  total: 0,
  scope: "active",
  selected: new Set(),
  publicSelected: new Set(),
  publicItemsById: new Map(),
  publicFilter: "",
  stats: null,
  itemsById: new Map(),
  canPublish: false,
  canManagePublic: false,
  config: null,
};

const DEFAULT_PUBLIC_INDEX_URL =
  "https://raw.githubusercontent.com/sxd55/astrbot_plugin_tiancai/main/public/public_index.json";

/** 分组设置：title / desc / fields[{key,label,type,desc,placeholder,options}] */
const SETTINGS_GROUPS = [
  {
    title: "公共源（读取）",
    desc: "控制插件如何同步并抽取公共菜单。留空的菜单 URL 会使用官方默认地址。",
    fields: [
      {
        key: "public_enabled",
        label: "启用公共源",
        type: "bool",
        desc: "开启后会按间隔同步公共菜单，并可在抽取时使用公共视频。关闭则只使用本地库。",
      },
      {
        key: "public_index_url",
        label: "公共菜单 URL",
        type: "text",
        desc: "公共库菜单 JSON 的 HTTPS 地址（通常是 GitHub raw）。留空则使用官方默认菜单。",
        placeholder: DEFAULT_PUBLIC_INDEX_URL,
      },
      {
        key: "library_mode",
        label: "抽取模式",
        type: "select",
        desc: "决定「随机发送」从哪里抽：仅本地 / 仅公共 / 本地与公共混合。",
        options: [
          { value: "local", label: "仅本地库" },
          { value: "public", label: "仅公共源" },
          { value: "mixed", label: "本地 + 公共混合（推荐）" },
        ],
      },
      {
        key: "public_sync_hours",
        label: "同步间隔（小时）",
        type: "number",
        desc: "多久重新拉取一次公共菜单。填 0 表示每次抽取前都尝试同步（更及时，也更费网络）。",
        placeholder: "12",
      },
      {
        key: "public_auto_import",
        label: "公共视频自动导入本地库",
        type: "bool",
        desc: "抽中公共视频并下载后，自动写入本地视频库，之后可预览、编辑、再发布。建议开启。",
      },
      {
        key: "public_weight",
        label: "混合模式下公共权重",
        type: "number",
        desc: "仅 library_mode=mixed 时生效。1=与本地同等；小于 1 更常抽本地；大于 1 更常抽公共。",
        placeholder: "1.0",
      },
      {
        key: "github_proxy",
        label: "GitHub 代理前缀",
        type: "text",
        desc: "拉取 GitHub raw/Release 时加在原 URL 前面。留空默认 https://gh-proxy.com/ 。若直连可用可填直连代理或保持默认。",
        placeholder: "https://gh-proxy.com/",
      },
    ],
  },
  {
    title: "发布到 GitHub（写入你自己的仓库）",
    desc: "只有填写了 Token 和你自己的仓库后，才能在视频库把本地条目发布到公共库。不会默认写进别人的仓库。",
    fields: [
      {
        key: "github_token",
        label: "GitHub Token",
        type: "password",
        desc: "用于创建/更新 Release 与 public_index.json。需要对该仓库有写入权限的 PAT。留空表示不修改已保存的 Token。",
        placeholder: "已配置则留空不改；未配置请粘贴 ghp_... / github_pat_...",
      },
      {
        key: "github_repo",
        label: "你的仓库 owner/repo",
        type: "text",
        desc: "发布目标仓库，格式：用户名/仓库名。必须手填你自己的仓库，例如 yourname/tiancai-public。读取官方菜单不依赖此项。",
        placeholder: "yourname/tiancai-public",
      },
      {
        key: "github_branch",
        label: "菜单所在分支",
        type: "text",
        desc: "更新 public_index.json 时提交到的分支，一般是 main。",
        placeholder: "main",
      },
      {
        key: "github_index_path",
        label: "仓库内菜单路径",
        type: "text",
        desc: "菜单文件在仓库中的路径。默认 public/public_index.json。",
        placeholder: "public/public_index.json",
      },
      {
        key: "github_release_tag",
        label: "视频 Release 标签",
        type: "text",
        desc: "视频作为 GitHub Release 附件上传时使用的标签名。同仓库内建议固定一个标签持续追加。",
        placeholder: "tiancai-videos",
      },
      {
        key: "max_public_upload_mb",
        label: "单条上传大小上限（MB）",
        type: "number",
        desc: "超过此大小的本地视频不允许发布。GitHub 单文件硬顶约 100MB，建议不超过 95。",
        placeholder: "95",
      },
    ],
  },
  {
    title: "本地库与抽取",
    desc: "控制本机收藏容量、冷却和入库权限。",
    fields: [
      {
        key: "cooldown_seconds",
        label: "抽取冷却（秒）",
        type: "number",
        desc: "同一用户两次「随机发送」的最短间隔。管理员不受冷却限制。0 表示不限制。",
        placeholder: "15",
      },
      {
        key: "max_videos",
        label: "本地库上限",
        type: "number",
        desc: "本地在库视频最大数量（不含回收站）。0 表示不限制。",
        placeholder: "0",
      },
      {
        key: "allow_duplicate",
        label: "允许重复入库同一条消息",
        type: "bool",
        desc: "关闭后，同一条原群消息只能入库一次（按消息 ID 去重）。",
      },
      {
        key: "collect_whitelist",
        label: "入库白名单 QQ",
        type: "text",
        desc: "除 AstrBot 管理员外，允许使用入库指令的 QQ 号。多个用逗号分隔。",
        placeholder: "123456,234567",
      },
      {
        key: "recent_penalty_count",
        label: "少重复：近期条数",
        type: "number",
        desc: "最近发出的 N 条会降低再次被抽中的权重，减少连着抽到同一条。",
        placeholder: "8",
      },
      {
        key: "recent_penalty_weight",
        label: "少重复：近期权重",
        type: "number",
        desc: "近期已发视频的权重倍率。普通为 1.0；越小越不容易马上再抽到。",
        placeholder: "0.15",
      },
      {
        key: "pinned_weight",
        label: "置顶权重",
        type: "number",
        desc: "标记为置顶的视频基础权重，越大越容易被抽到。",
        placeholder: "3.0",
      },
      {
        key: "storage_subdir",
        label: "本地存储子目录名",
        type: "text",
        desc: "视频文件保存在 data/plugin_data/astrbot_plugin_tiancai/<该目录>/ 下。一般无需修改。",
        placeholder: "videos",
      },
    ],
  },
  {
    title: "指令别名",
    desc: "可自定义触发词。多个别名用英文/中文逗号分隔。修改后立即按新文案匹配（无需改代码）。",
    fields: [
      {
        key: "cmd_collect",
        label: "入库指令",
        type: "text",
        desc: "回复视频后发送这些词可入库。",
        placeholder: "收进天菜,加入天菜,天菜入库",
      },
      {
        key: "cmd_show",
        label: "随机发送指令",
        type: "text",
        desc: "发送这些词会随机发一条视频。",
        placeholder: "看看天菜,来点天菜,天菜",
      },
      {
        key: "cmd_sync",
        label: "同步公共源指令",
        type: "text",
        desc: "手动拉取公共菜单。",
        placeholder: "同步天菜源,天菜同步,同步公共天菜",
      },
      {
        key: "cmd_count",
        label: "数量查询指令",
        type: "text",
        desc: "查看本地/公共数量。",
        placeholder: "天菜数量,天菜库,天菜列表",
      },
      {
        key: "cmd_delete",
        label: "删除指令",
        type: "text",
        desc: "用法：指令 + 编号，例如：删除天菜 3",
        placeholder: "删除天菜,天菜删除",
      },
      {
        key: "cmd_detail",
        label: "详情指令",
        type: "text",
        desc: "用法：指令 + 编号，例如：天菜详情 3",
        placeholder: "天菜详情,天菜信息",
      },
      {
        key: "cmd_help",
        label: "帮助指令",
        type: "text",
        desc: "查看当前生效的指令说明。",
        placeholder: "天菜帮助,天菜说明,天菜指令",
      },
      {
        key: "cmd_clear",
        label: "清空指令（仅管理员）",
        type: "text",
        desc: "将全部在库视频移入回收站。",
        placeholder: "清空天菜",
      },
    ],
  },
];

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

function toast(msg, ms = 2400) {
  const el = $("#toast");
  el.hidden = false;
  el.textContent = msg;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => {
    el.hidden = true;
  }, ms);
}

function askConfirm(message, title = "确认操作") {
  return new Promise((resolve) => {
    const dialog = $("#confirmDialog");
    const form = $("#confirmForm");
    const titleEl = $("#confirmTitle");
    const msgEl = $("#confirmMessage");
    const cancelBtn = $("#confirmCancel");
    if (!dialog || !form || !titleEl || !msgEl || !cancelBtn) {
      resolve(true);
      return;
    }
    titleEl.textContent = title;
    msgEl.textContent = message;
    const cleanup = () => {
      form.removeEventListener("submit", onSubmit);
      cancelBtn.removeEventListener("click", onCancel);
      dialog.removeEventListener("close", onClose);
    };
    const onSubmit = (ev) => {
      ev.preventDefault();
      cleanup();
      dialog.close();
      resolve(true);
    };
    const onCancel = () => {
      cleanup();
      dialog.close();
      resolve(false);
    };
    const onClose = () => {
      cleanup();
      resolve(false);
    };
    form.addEventListener("submit", onSubmit);
    cancelBtn.addEventListener("click", onCancel);
    dialog.addEventListener("close", onClose, { once: true });
    dialog.showModal();
  });
}

function esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setTab(name) {
  state.tab = name;
  state.selected.clear();
  state.publicSelected.clear();
  $$(".tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === name);
  });
  $$(".panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `panel-${name}`);
  });
  if (name === "library") {
    state.scope = "active";
    state.page = 1;
    loadLibrary();
  } else if (name === "public") {
    loadPublicManaged();
  } else if (name === "trash") {
    state.scope = "trash";
    state.page = 1;
    loadLibrary();
  } else if (name === "logs") {
    loadLogs();
  } else if (name === "settings") {
    loadSettings();
  } else {
    loadStats();
  }
  updateBatchButtons();
  updatePublicButtons();
}

async function loadStats() {
  try {
    const stats = await bridge.apiGet("stats");
    state.stats = stats;
    const pub = stats.public || {};
    $("#subtitle").textContent =
      `在库 ${stats.active_count} · 回收站 ${stats.trash_count} · 公共 ${pub.public_count || 0} · ${stats.total_size_human}`;
    $("#videosDir").textContent = stats.videos_dir || "—";
    const cards = [
      ["在库", stats.active_count],
      ["回收站", stats.trash_count],
      ["公共源", pub.public_count || 0],
      ["占用", stats.total_size_human],
      ["今日入库", stats.collected_today],
      ["今日抽出", stats.played_today],
    ];
    $("#statCards").innerHTML = cards
      .map(
        ([label, value]) => `
      <div class="stat">
        <div class="label">${esc(label)}</div>
        <div class="value">${esc(value)}</div>
      </div>`,
      )
      .join("");
    renderMini("#recentCollected", stats.recent_collected || [], "saved_at_human");
    renderMini("#recentPlayed", stats.recent_played || [], "last_played_at_human");
    const summary = $("#publicSummary");
    if (summary) {
      summary.textContent = pub.enabled
        ? `已启用 · 模式 ${pub.mode || "-"} · ${pub.index_url || ""}\n代理 ${pub.proxy || "-"} · 自动导入 ${pub.auto_import ? "开" : "关"}`
        : "公共源未启用";
    }
    state.canPublish = !!pub.token_configured && !!(pub.repo || "").trim();
    state.canManagePublic = state.canPublish;
    updateBatchButtons();
    updatePublicButtons();
  } catch (err) {
    toast(`加载总览失败：${err.message || err}`);
  }
}

function renderMini(sel, items, timeKey) {
  const box = $(sel);
  if (!items.length) {
    box.classList.add("empty");
    box.textContent = "暂无";
    return;
  }
  box.classList.remove("empty");
  box.innerHTML = items
    .map((item) => {
      const t = item[timeKey] || item.saved_at_human || "—";
      const label = item.seq ? `#${item.seq}` : item.id_short || String(item.id || "").slice(0, 8);
      return `<div class="mini-item">
        <span class="id">${esc(label)}</span>
        <span>${esc(t)}</span>
      </div>`;
    })
    .join("");
}

async function loadLibrary() {
  const listId = state.scope === "trash" ? "#trashList" : "#libraryList";
  const box = $(listId);
  box.innerHTML = `<div class="empty">加载中…</div>`;
  const q = $("#searchQ")?.value?.trim() || "";
  const sort = $("#sortBy")?.value || "seq";
  try {
    const data = await bridge.apiGet("videos", {
      scope: state.scope,
      q,
      sort,
      order: sort === "seq" ? "asc" : "desc",
      page: state.page,
      page_size: state.pageSize,
    });
    state.total = data.total || 0;
    const items = data.items || [];
    state.itemsById = new Map(items.map((it) => [it.id, it]));
    if (!items.length) {
      box.classList.add("empty");
      box.textContent =
        state.scope === "trash" ? "回收站为空" : "视频库为空，可上传或抽取公共视频自动导入";
      updatePager();
      updateBatchButtons();
      return;
    }
    box.classList.remove("empty");
    box.innerHTML = items.map(renderCard).join("");
    bindCardEvents(box);
    updatePager();
    updateBatchButtons();
  } catch (err) {
    box.textContent = `加载失败：${err.message || err}`;
    toast(`加载列表失败：${err.message || err}`);
  }
}

function renderCard(item) {
  const checked = state.selected.has(item.id) ? "checked" : "";
  const tags = (item.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("");
  const pin = item.pinned ? `<span class="pin">置顶</span>` : "";
  const missing = item.file_exists ? "" : "missing";
  const note = item.note || "无备注";
  const num = item.seq ? `#${item.seq}` : item.id_short || String(item.id).slice(0, 8);
  const actions =
    state.scope === "trash"
      ? `
        <button type="button" data-act="restore" data-id="${esc(item.id)}">恢复</button>
        <button type="button" class="danger" data-act="purge" data-id="${esc(item.id)}">永久删除</button>
        <button type="button" data-act="download" data-id="${esc(item.id)}" data-name="${esc(item.filename || "video.mp4")}">下载</button>
      `
      : `
        <button type="button" data-act="edit" data-id="${esc(item.id)}">编辑</button>
        <button type="button" data-act="download" data-id="${esc(item.id)}" data-name="${esc(item.filename || "video.mp4")}">下载</button>
        <button type="button" class="danger" data-act="delete" data-id="${esc(item.id)}">回收站</button>
      `;
  const previewDisabled = item.file_exists ? "" : "disabled";
  return `<article class="v-card ${missing}" data-id="${esc(item.id)}">
    <div class="v-body">
      <div class="v-main">
        <div class="v-head">
          <input type="checkbox" data-select="${esc(item.id)}" ${checked} />
          <div>
            <div class="v-title">${esc(num)} ${pin}</div>
            <div class="v-meta">
              ${esc(item.size_human)} · 抽中 ${esc(item.play_count)} 次<br/>
              入库 ${esc(item.saved_at_human || "—")}<br/>
              ${item.collector_name ? `收藏人 ${esc(item.collector_name)}` : "未知来源"}
              ${item.file_exists ? "" : " · 文件缺失"}
            </div>
          </div>
        </div>
        <div class="v-meta">${esc(note)}</div>
        <div class="tags">${tags || `<span class="tag">天菜</span>`}</div>
        <div class="v-actions">${actions}</div>
      </div>
      <button type="button" class="preview-box" data-act="preview" data-id="${esc(item.id)}" ${previewDisabled} title="点击播放预览">
        <span class="preview-placeholder">
          <span class="play-icon">▶</span>
          <span>预览</span>
        </span>
      </button>
    </div>
  </article>`;
}

function bindCardEvents(box) {
  box.querySelectorAll("[data-select]").forEach((input) => {
    input.addEventListener("change", () => {
      const id = input.getAttribute("data-select");
      if (input.checked) state.selected.add(id);
      else state.selected.delete(id);
      updateBatchButtons();
    });
  });
  box.querySelectorAll("[data-act]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const act = btn.getAttribute("data-act");
      const id = btn.getAttribute("data-id");
      try {
        if (act === "delete") {
          await bridge.apiPost("videos/delete", { ids: [id] });
          toast("已移入回收站");
          await refreshCurrent();
        } else if (act === "restore") {
          await bridge.apiPost("videos/restore", { ids: [id] });
          toast("已恢复");
          await refreshCurrent();
        } else if (act === "purge") {
          const ok = await askConfirm("确定永久删除这条视频？\n此操作不可恢复。", "永久删除");
          if (!ok) return;
          await bridge.apiPost("videos/purge", { ids: [id] });
          toast("已永久删除");
          await refreshCurrent();
        } else if (act === "download") {
          const name = btn.getAttribute("data-name") || `tiancai_${id.slice(0, 8)}.mp4`;
          await bridge.download("videos/download", { id }, name);
          toast("开始下载");
        } else if (act === "edit") {
          openEdit(id);
        } else if (act === "preview") {
          await openPreview(id, btn);
        }
      } catch (err) {
        toast(`操作失败：${err.message || err}`);
      }
    });
  });
}

async function openPreview(id, btn) {
  const item = state.itemsById.get(id);
  if (!item?.file_exists) {
    toast("文件不存在，无法预览");
    return;
  }
  if (btn.dataset.loaded === "1") {
    const video = btn.querySelector("video");
    if (video) {
      if (video.paused) video.play().catch(() => {});
      else video.pause();
    }
    return;
  }
  btn.classList.add("loading");
  const ph = btn.querySelector(".preview-placeholder");
  if (ph) ph.innerHTML = `<span>加载中…</span>`;
  try {
    const media = await bridge.apiGet("videos/media", { id });
    if (!media?.data_url) throw new Error("无预览数据");
    btn.innerHTML = "";
    const video = document.createElement("video");
    video.controls = true;
    video.playsInline = true;
    video.preload = "metadata";
    video.src = media.data_url;
    video.addEventListener("click", (e) => e.stopPropagation(), true);
    btn.appendChild(video);
    btn.dataset.loaded = "1";
    btn.classList.add("has-video");
    video.play().catch(() => {});
  } catch (err) {
    const msg = String(err.message || err);
    toast(msg.includes("too large") || msg.includes("413") ? "文件较大，请用下载" : `预览失败：${msg}`);
    if (ph) ph.innerHTML = `<span class="play-icon">▶</span><span>预览</span>`;
  } finally {
    btn.classList.remove("loading");
  }
}

function updateBatchButtons() {
  const n = state.selected.size;
  const del = $("#btnBatchDelete");
  const restore = $("#btnBatchRestore");
  const purge = $("#btnBatchPurge");
  const publish = $("#btnPublishGithub");
  if (del) del.disabled = n === 0 || state.scope !== "active";
  if (restore) restore.disabled = n === 0 || state.scope !== "trash";
  if (purge) purge.disabled = n === 0 || state.scope !== "trash";
  if (publish) publish.disabled = !state.canPublish || n === 0 || state.scope !== "active";
  const hint = $("#publishHint");
  if (hint) {
    hint.textContent = state.canPublish
      ? "已配置 Token 与你的仓库：勾选本地视频后可发布到该仓库。"
      : "发布前请在「设置」填写 github_token，并手填你自己的 github_repo（owner/repo）。公共菜单可留空使用官方默认。";
  }
}

function updatePublicButtons() {
  const n = state.publicSelected.size;
  const del = $("#btnPublicDelete");
  const imp = $("#btnPublicImport");
  const refresh = $("#btnPublicRefresh");
  if (del) del.disabled = !state.canManagePublic || n === 0;
  if (imp) imp.disabled = !state.canManagePublic || n === 0;
  if (refresh) refresh.disabled = !state.canManagePublic;
  const hint = $("#publicManageHint");
  if (hint) {
    hint.textContent = state.canManagePublic
      ? "已配置 Token 与仓库：可刷新、编辑、删除公共库条目，或下载到本地。"
      : "此栏管理设置里 github_repo 指向的仓库。请先在「设置」填写 github_token 与 github_repo。";
  }
}

async function loadPublicManaged() {
  const box = $("#publicList");
  if (!box) return;
  box.innerHTML = `<div class="empty">加载中…</div>`;
  updatePublicButtons();
  if (!state.canManagePublic) {
    // 尝试再读一次 stats/config
    try {
      const stats = await bridge.apiGet("stats");
      const pub = stats.public || {};
      state.canManagePublic = !!pub.token_configured && !!(pub.repo || "").trim();
      state.canPublish = state.canManagePublic;
      updatePublicButtons();
    } catch {
      /* ignore */
    }
  }
  if (!state.canManagePublic) {
    box.classList.add("empty");
    box.textContent = "未配置 github_token / github_repo，无法管理公共库。";
    return;
  }
  try {
    const data = await bridge.apiGet("public/managed/list");
    let items = data.items || [];
    const q = (state.publicFilter || $("#publicSearchQ")?.value || "").trim().toLowerCase();
    if (q) {
      items = items.filter((it) => {
        const blob = [
          it.id,
          it.seq,
          it.title,
          ...(it.tags || []),
        ]
          .join(" ")
          .toLowerCase();
        return blob.includes(q);
      });
    }
    state.publicItemsById = new Map(items.map((it) => [it.id, it]));
    if (!items.length) {
      box.classList.add("empty");
      box.textContent = q ? "没有匹配的公共条目" : "公共库还是空的，可先从「视频库」发布";
      return;
    }
    box.classList.remove("empty");
    box.innerHTML = items.map(renderPublicCard).join("");
    bindPublicCardEvents(box);
    const hint = $("#publicManageHint");
    if (hint) {
      hint.textContent = `仓库 ${data.repo || "-"} · 共 ${data.total || items.length} 条 · 更新 ${data.updated_at_human || "-"}`;
    }
  } catch (err) {
    box.classList.add("empty");
    box.textContent = `加载失败：${err.message || err}`;
    toast(`加载公共库失败：${err.message || err}`);
  }
}

function renderPublicCard(item) {
  const checked = state.publicSelected.has(item.id) ? "checked" : "";
  const tags = (item.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("");
  const num = item.seq ? `#${item.seq}` : String(item.id || "").slice(0, 10);
  return `<article class="v-card" data-id="${esc(item.id)}">
    <div class="v-main">
      <div class="v-head">
        <input type="checkbox" data-public-select="${esc(item.id)}" ${checked} />
        <div>
          <div class="v-title">${esc(num)}</div>
          <div class="v-meta">
            ${esc(item.size_human || "-")} · ${esc(item.created_at_human || "")}<br/>
            ID：${esc(item.id)}
          </div>
        </div>
      </div>
      <div class="v-meta">${esc(item.title || "无标题")}</div>
      <div class="tags">${tags || `<span class="tag">天菜</span>`}</div>
      <div class="v-actions">
        <button type="button" data-public-act="edit" data-id="${esc(item.id)}">编辑</button>
        <button type="button" data-public-act="import" data-id="${esc(item.id)}">下载到本地</button>
        <button type="button" class="danger" data-public-act="delete" data-id="${esc(item.id)}">删除</button>
      </div>
    </div>
  </article>`;
}

function bindPublicCardEvents(box) {
  box.querySelectorAll("[data-public-select]").forEach((input) => {
    input.addEventListener("change", () => {
      const id = input.getAttribute("data-public-select");
      if (input.checked) state.publicSelected.add(id);
      else state.publicSelected.delete(id);
      updatePublicButtons();
    });
  });
  box.querySelectorAll("[data-public-act]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const act = btn.getAttribute("data-public-act");
      const id = btn.getAttribute("data-id");
      try {
        if (act === "edit") {
          openPublicEdit(id);
        } else if (act === "import") {
          toast("正在下载到本地…");
          const result = await bridge.apiPost("public/managed/import", { ids: [id] });
          toast(
            `导入完成：成功 ${result.imported || 0}，跳过 ${result.skipped || 0}，失败 ${result.failed || 0}`,
          );
        } else if (act === "delete") {
          const ok = await askConfirm(
            "确定从公共库删除该条目？\n会更新菜单，并尽量删除对应 Release 附件。",
            "删除公共条目",
          );
          if (!ok) return;
          const result = await bridge.apiPost("public/managed/delete", { ids: [id] });
          toast(`已删除 ${result.deleted || 0} 条`);
          state.publicSelected.delete(id);
          await loadPublicManaged();
        }
      } catch (err) {
        toast(`操作失败：${err.message || err}`);
      }
    });
  });
}

function openPublicEdit(id) {
  const item = state.publicItemsById.get(id);
  if (!item) {
    toast("未找到该公共条目");
    return;
  }
  $("#publicEditId").value = item.id;
  $("#publicEditTitle").value = item.title || "";
  $("#publicEditTags").value = (item.tags || []).join(", ");
  $("#publicEditDialog").showModal();
}

async function savePublicEdit(ev) {
  ev.preventDefault();
  const id = $("#publicEditId").value;
  const title = $("#publicEditTitle").value;
  const tags = $("#publicEditTags").value;
  try {
    await bridge.apiPost("public/managed/update", { id, title, tags });
    $("#publicEditDialog").close();
    toast("公共库条目已保存");
    await loadPublicManaged();
  } catch (err) {
    toast(`保存失败：${err.message || err}`);
  }
}

function updatePager() {
  const pages = Math.max(Math.ceil(state.total / state.pageSize), 1);
  $("#pageInfo").textContent = `第 ${state.page} / ${pages} 页 · 共 ${state.total} 条`;
  $("#btnPrev").disabled = state.page <= 1;
  $("#btnNext").disabled = state.page >= pages;
}

async function refreshCurrent() {
  state.selected.clear();
  state.publicSelected.clear();
  if (state.tab === "overview") await loadStats();
  else if (state.tab === "logs") await loadLogs();
  else if (state.tab === "settings") await loadSettings();
  else if (state.tab === "public") await loadPublicManaged();
  else await loadLibrary();
  try {
    const stats = await bridge.apiGet("stats");
    const pub = stats.public || {};
    $("#subtitle").textContent =
      `在库 ${stats.active_count} · 回收站 ${stats.trash_count} · 公共 ${pub.public_count || 0} · ${stats.total_size_human}`;
    state.canPublish = !!pub.token_configured && !!(pub.repo || "").trim();
    state.canManagePublic = state.canPublish;
    updateBatchButtons();
    updatePublicButtons();
  } catch {
    /* ignore */
  }
}

async function loadLogs() {
  const box = $("#logList");
  try {
    const data = await bridge.apiGet("logs", { limit: 80 });
    const items = data.items || [];
    if (!items.length) {
      box.classList.add("empty");
      box.textContent = "暂无日志";
      return;
    }
    box.classList.remove("empty");
    box.innerHTML = items
      .map((row) => {
        const ts = row.ts ? formatTs(row.ts) : "—";
        return `<div class="log-row">
          <span>${esc(ts)}</span>
          <span>${esc(row.action || "")}</span>
          <span>${esc([row.user, row.video, row.detail].filter(Boolean).join(" · "))}</span>
        </div>`;
      })
      .join("");
  } catch (err) {
    box.textContent = `加载日志失败：${err.message || err}`;
  }
}

function formatTs(raw) {
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return String(raw || "");
  const d = new Date(n * 1000);
  const p = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

async function openEdit(id) {
  try {
    let target = state.itemsById.get(id);
    if (!target) {
      const data = await bridge.apiGet("videos", { scope: "all", q: id, page: 1, page_size: 20 });
      target = (data.items || []).find((x) => x.id === id);
    }
    if (!target) {
      toast("未找到该条目");
      return;
    }
    $("#editId").value = target.id;
    $("#editNote").value = target.note || "";
    $("#editTags").value = (target.tags || []).join(", ");
    $("#editPinned").checked = !!target.pinned;
    $("#editDialog").showModal();
  } catch (err) {
    toast(`打开编辑失败：${err.message || err}`);
  }
}

async function saveEdit(ev) {
  ev.preventDefault();
  try {
    await bridge.apiPost("videos/update", {
      id: $("#editId").value,
      note: $("#editNote").value,
      tags: $("#editTags").value,
      pinned: $("#editPinned").checked,
    });
    $("#editDialog").close();
    toast("已保存");
    await refreshCurrent();
  } catch (err) {
    toast(`保存失败：${err.message || err}`);
  }
}

async function onUpload(file) {
  if (!file) return;
  toast(`上传中：${file.name}`);
  try {
    const result = await bridge.upload("videos/upload", file);
    toast(result?.item?.seq ? `上传成功 #${result.item.seq}` : "上传成功");
    await refreshCurrent();
    if (state.tab !== "library") setTab("library");
  } catch (err) {
    toast(`上传失败：${err.message || err}`);
  }
}

async function loadSettings() {
  const form = $("#settingsForm");
  if (!form) return;
  form.innerHTML = `<div class="hint">加载中…</div>`;
  try {
    const data = await bridge.apiGet("config/get");
    state.config = data.config || {};
    const cfg = state.config;
    form.innerHTML = SETTINGS_GROUPS.map((group) => {
      const fieldsHtml = group.fields
        .map((field) => {
          let value = cfg[field.key];
          if (field.key === "collect_whitelist" && Array.isArray(value)) {
            value = value.join(",");
          }
          if (field.key === "public_index_url" && !value) {
            value = "";
          }
          if (field.key === "github_token") {
            return `<div class="setting-item">
              <div class="setting-label">${esc(field.label)}</div>
              <div class="setting-desc">${esc(field.desc)}</div>
              <input name="${esc(field.key)}" type="password" placeholder="${esc(
                cfg.github_token_configured
                  ? "已配置（留空不修改）"
                  : field.placeholder || "粘贴你的 PAT",
              )}" />
            </div>`;
          }
          if (field.type === "bool") {
            return `<div class="setting-item">
              <label class="check">
                <input name="${esc(field.key)}" type="checkbox" ${value ? "checked" : ""}/>
                <span>${esc(field.label)}</span>
              </label>
              <div class="setting-desc">${esc(field.desc)}</div>
            </div>`;
          }
          if (field.type === "select") {
            const opts = (field.options || [])
              .map((opt) => {
                const selected = String(value || "mixed") === opt.value ? "selected" : "";
                return `<option value="${esc(opt.value)}" ${selected}>${esc(opt.label)}</option>`;
              })
              .join("");
            return `<div class="setting-item">
              <div class="setting-label">${esc(field.label)}</div>
              <div class="setting-desc">${esc(field.desc)}</div>
              <select name="${esc(field.key)}">${opts}</select>
            </div>`;
          }
          const shown =
            value === undefined || value === null || value === ""
              ? ""
              : String(value);
          return `<div class="setting-item">
            <div class="setting-label">${esc(field.label)}</div>
            <div class="setting-desc">${esc(field.desc)}</div>
            <input name="${esc(field.key)}" type="${
              field.type === "number" ? "number" : "text"
            }" value="${esc(shown)}" placeholder="${esc(field.placeholder || "")}" />
          </div>`;
        })
        .join("");
      return `<section class="settings-group">
        <h3>${esc(group.title)}</h3>
        <p class="hint">${esc(group.desc)}</p>
        ${fieldsHtml}
      </section>`;
    }).join("");
  } catch (err) {
    form.innerHTML = `<div class="hint">加载失败：${esc(err.message || err)}</div>`;
  }
}

async function saveSettings() {
  const form = $("#settingsForm");
  if (!form) return;
  const payload = {};
  SETTINGS_GROUPS.forEach((group) => {
    group.fields.forEach((field) => {
      const el = form.querySelector(`[name="${field.key}"]`);
      if (!el) return;
      if (field.type === "bool") payload[field.key] = !!el.checked;
      else if (field.key === "github_token") {
        if (el.value) payload[field.key] = el.value;
      } else if (field.type === "number") {
        payload[field.key] = el.value === "" ? 0 : Number(el.value);
      } else {
        payload[field.key] = el.value;
      }
    });
  });
  try {
    const result = await bridge.apiPost("config/save", payload);
    toast(`已保存 ${result.changed?.length || 0} 项配置`);
    await loadSettings();
    await loadStats();
  } catch (err) {
    toast(`保存失败：${err.message || err}`);
  }
}

function wire() {
  $$(".tab").forEach((btn) => btn.addEventListener("click", () => setTab(btn.dataset.tab)));
  $("#btnRefresh")?.addEventListener("click", () => refreshCurrent());
  $("#btnSearch")?.addEventListener("click", () => {
    state.page = 1;
    loadLibrary();
  });
  $("#searchQ")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      state.page = 1;
      loadLibrary();
    }
  });
  $("#sortBy")?.addEventListener("change", () => {
    state.page = 1;
    loadLibrary();
  });
  $("#btnPrev")?.addEventListener("click", () => {
    if (state.page > 1) {
      state.page -= 1;
      loadLibrary();
    }
  });
  $("#btnNext")?.addEventListener("click", () => {
    const pages = Math.max(Math.ceil(state.total / state.pageSize), 1);
    if (state.page < pages) {
      state.page += 1;
      loadLibrary();
    }
  });

  $("#btnBatchDelete")?.addEventListener("click", async () => {
    const ids = [...state.selected];
    if (!ids.length) return;
    try {
      await bridge.apiPost("videos/delete", { ids });
      toast(`已移入回收站 ${ids.length} 条`);
      await refreshCurrent();
    } catch (err) {
      toast(`批量删除失败：${err.message || err}`);
    }
  });

  $("#btnPublishGithub")?.addEventListener("click", async () => {
    const ids = [...state.selected];
    if (!ids.length) {
      toast("请先勾选要发布的视频");
      return;
    }
    if (!state.canPublish) {
      toast("请先在设置页填写 github_token 与 github_repo");
      return;
    }
    const ok = await askConfirm(
      `将选中的 ${ids.length} 条发布到你自己的 GitHub 公共库？\n视频上传到 Release，并更新 public_index.json。`,
      "发布到公共库",
    );
    if (!ok) {
      toast("已取消发布");
      return;
    }
    const btn = $("#btnPublishGithub");
    if (btn) btn.disabled = true;
    toast("正在发布到公共库，请稍候…", 8000);
    try {
      const result = await bridge.apiPost("public/publish", { ids });
      toast(
        `发布完成：成功 ${result.published || 0}，跳过 ${result.skipped || 0}，失败 ${result.failed || 0}`,
        5000,
      );
      if (result.errors?.length) console.warn("publish errors", result.errors);
      state.selected.clear();
      await refreshCurrent();
    } catch (err) {
      toast(`发布失败：${err.message || err}`, 5000);
      console.error(err);
    } finally {
      updateBatchButtons();
    }
  });

  $("#btnBatchRestore")?.addEventListener("click", async () => {
    const ids = [...state.selected];
    if (!ids.length) return;
    try {
      await bridge.apiPost("videos/restore", { ids });
      toast(`已恢复 ${ids.length} 条`);
      await refreshCurrent();
    } catch (err) {
      toast(`批量恢复失败：${err.message || err}`);
    }
  });

  $("#btnBatchPurge")?.addEventListener("click", async () => {
    const ids = [...state.selected];
    if (!ids.length) return;
    const ok = await askConfirm(`确定永久删除 ${ids.length} 条？\n此操作不可恢复。`, "永久删除");
    if (!ok) return;
    try {
      await bridge.apiPost("videos/purge", { ids });
      toast(`已永久删除 ${ids.length} 条`);
      state.selected.clear();
      await refreshCurrent();
    } catch (err) {
      toast(`永久删除失败：${err.message || err}`);
    }
  });

  $("#btnPublicRefresh")?.addEventListener("click", async () => {
    if (!state.canManagePublic) {
      toast("请先在设置页填写 github_token 与 github_repo");
      return;
    }
    toast("正在刷新公共库…");
    // 先同步公开菜单缓存，再拉可管理列表
    try {
      await bridge.apiPost("public/sync", {});
    } catch {
      /* 同步失败也继续拉 managed list */
    }
    await loadPublicManaged();
    toast("公共库已刷新");
  });

  $("#btnPublicSearch")?.addEventListener("click", () => {
    state.publicFilter = $("#publicSearchQ")?.value || "";
    loadPublicManaged();
  });
  $("#publicSearchQ")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      state.publicFilter = $("#publicSearchQ")?.value || "";
      loadPublicManaged();
    }
  });

  $("#btnPublicImport")?.addEventListener("click", async () => {
    const ids = [...state.publicSelected];
    if (!ids.length) {
      toast("请先勾选公共库视频");
      return;
    }
    toast(`正在下载 ${ids.length} 条到本地…`, 6000);
    try {
      const result = await bridge.apiPost("public/managed/import", { ids });
      toast(
        `导入完成：成功 ${result.imported || 0}，跳过 ${result.skipped || 0}，失败 ${result.failed || 0}`,
        5000,
      );
      if (result.errors?.length) console.warn(result.errors);
    } catch (err) {
      toast(`导入失败：${err.message || err}`);
    }
  });

  $("#btnPublicDelete")?.addEventListener("click", async () => {
    const ids = [...state.publicSelected];
    if (!ids.length) {
      toast("请先勾选要删除的公共条目");
      return;
    }
    const ok = await askConfirm(
      `确定从公共库删除 ${ids.length} 条？\n会更新菜单，并尽量删除对应 Release 附件。`,
      "删除公共条目",
    );
    if (!ok) return;
    try {
      const result = await bridge.apiPost("public/managed/delete", { ids });
      toast(`已删除 ${result.deleted || 0} 条`);
      state.publicSelected.clear();
      await loadPublicManaged();
    } catch (err) {
      toast(`删除失败：${err.message || err}`);
    }
  });

  $("#publicEditForm")?.addEventListener("submit", savePublicEdit);
  $("#publicEditCancel")?.addEventListener("click", () => $("#publicEditDialog").close());

  $("#fileInput")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    await onUpload(file);
  });
  $("#editForm")?.addEventListener("submit", saveEdit);
  $("#editCancel")?.addEventListener("click", () => $("#editDialog").close());
  $("#btnSaveSettings")?.addEventListener("click", saveSettings);
  $("#btnReloadSettings")?.addEventListener("click", loadSettings);
}

async function boot() {
  wire();
  try {
    const ctx = await bridge.ready();
    document.title = bridge.t("pages.dashboard.title", "天菜管理台");
    if (ctx?.isDark) document.documentElement.dataset.theme = "dark";
    bridge.onContext((c) => {
      document.documentElement.dataset.theme = c?.isDark ? "dark" : "light";
      document.title = bridge.t("pages.dashboard.title", "天菜管理台");
    });
  } catch (err) {
    console.warn("bridge ready failed", err);
  }
  await loadStats();
}

boot();
