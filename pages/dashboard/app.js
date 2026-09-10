const bridge = window.AstrBotPluginPage;

const state = {
  tab: "overview",
  page: 1,
  pageSize: 12,
  total: 0,
  scope: "active",
  selected: new Set(),
  stats: null,
  itemsById: new Map(),
  canPublish: false,
  config: null,
};

const SETTINGS_FIELDS = [
  ["public_enabled", "启用公共源", "bool"],
  ["public_index_url", "公共菜单 URL", "text"],
  ["library_mode", "抽取模式 (local/public/mixed)", "text"],
  ["public_sync_hours", "同步间隔小时", "number"],
  ["public_auto_import", "公共视频自动导入本地库", "bool"],
  ["public_weight", "mixed 公共权重", "number"],
  ["github_proxy", "GitHub 代理（留空=gh-proxy.com）", "text"],
  ["github_token", "GitHub Token（发布用，不回显）", "password"],
  ["github_repo", "你的仓库 owner/repo", "text"],
  ["github_branch", "分支", "text"],
  ["github_index_path", "菜单路径", "text"],
  ["github_release_tag", "Release 标签", "text"],
  ["max_public_upload_mb", "上传大小上限 MB", "number"],
  ["cooldown_seconds", "抽取冷却秒数", "number"],
  ["max_videos", "本地库上限（0不限）", "number"],
  ["collect_whitelist", "入库白名单（逗号分隔）", "text"],
  ["cmd_collect", "入库指令", "text"],
  ["cmd_show", "随机发送指令", "text"],
  ["cmd_sync", "同步指令", "text"],
  ["cmd_count", "数量指令", "text"],
  ["cmd_delete", "删除指令", "text"],
  ["cmd_detail", "详情指令", "text"],
  ["cmd_help", "帮助指令", "text"],
  ["cmd_clear", "清空指令", "text"],
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
    updateBatchButtons();
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
      ? "已配置 Token 与仓库：勾选本地视频后可发布到你自己的 GitHub 公共库。"
      : "请先在「设置」填写 github_token 与 github_repo（你自己的仓库），才能发布。";
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
  if (state.tab === "overview") await loadStats();
  else if (state.tab === "logs") await loadLogs();
  else if (state.tab === "settings") await loadSettings();
  else await loadLibrary();
  try {
    const stats = await bridge.apiGet("stats");
    const pub = stats.public || {};
    $("#subtitle").textContent =
      `在库 ${stats.active_count} · 回收站 ${stats.trash_count} · 公共 ${pub.public_count || 0} · ${stats.total_size_human}`;
    state.canPublish = !!pub.token_configured && !!(pub.repo || "").trim();
    updateBatchButtons();
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
    form.innerHTML = SETTINGS_FIELDS.map(([key, label, type]) => {
      let value = cfg[key];
      if (key === "collect_whitelist" && Array.isArray(value)) value = value.join(",");
      if (key === "github_token") {
        return `<label>${esc(label)}
          <input name="${esc(key)}" type="password" placeholder="${cfg.github_token_configured ? "已配置（留空不修改）" : "粘贴你的 PAT"}" />
        </label>`;
      }
      if (type === "bool") {
        return `<label class="check"><input name="${esc(key)}" type="checkbox" ${value ? "checked" : ""}/> ${esc(label)}</label>`;
      }
      return `<label>${esc(label)}
        <input name="${esc(key)}" type="${type === "number" ? "number" : "text"}" value="${esc(value ?? "")}" />
      </label>`;
    }).join("");
  } catch (err) {
    form.innerHTML = `<div class="hint">加载失败：${esc(err.message || err)}</div>`;
  }
}

async function saveSettings() {
  const form = $("#settingsForm");
  if (!form) return;
  const payload = {};
  SETTINGS_FIELDS.forEach(([key, , type]) => {
    const el = form.querySelector(`[name="${key}"]`);
    if (!el) return;
    if (type === "bool") payload[key] = !!el.checked;
    else if (key === "github_token") {
      if (el.value) payload[key] = el.value;
    } else if (type === "number") payload[key] = el.value === "" ? 0 : Number(el.value);
    else payload[key] = el.value;
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
