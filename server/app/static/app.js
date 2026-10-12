"use strict";

// ---------- state ----------
const state = {
  categories: [],
  videos: [],
  filter: "all", // "all" | "none" | category id
  uploads: [], // {id, file, title, categoryId, uploaded, status, error, uploadId}
  uploading: false,
};
let pollTimer = null;

// ---------- helpers ----------
const $ = (sel) => document.querySelector(sel);

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k in el && k !== "list") el[k] = v;
    else el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

// replaceChildren() would print null/false/arrays literally.
function setChildren(el, ...children) {
  el.replaceChildren(...children.flat(Infinity).filter((c) => c != null && c !== false));
}

// The site may be served under a path prefix (https://host/<prefix>/), so every
// request is made relative to the page instead of the domain root.
const rel = (path) => path.replace(/^\//, "");

class ApiError extends Error {
  constructor(status, message, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function api(method, path, body, opts = {}) {
  const init = { method, credentials: "same-origin", headers: {} };
  if (body instanceof Blob) {
    init.body = body;
    init.headers["Content-Type"] = "application/octet-stream";
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers["Content-Type"] = "application/json";
  }
  if (opts.signal) init.signal = opts.signal;
  const res = await fetch(rel(path), init);
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    if (res.status === 401 && path !== "/api/login") showLogin();
    const msg = data && typeof data.detail === "string" ? data.detail : `请求失败（${res.status}）`;
    throw new ApiError(res.status, msg, data);
  }
  return data;
}

function toast(msg, ms = 2500) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, ms);
}

function fmtDuration(sec) {
  if (!sec && sec !== 0) return "";
  sec = Math.round(sec);
  const m = Math.floor(sec / 60);
  const s = String(sec % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function fmtSize(bytes) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function categoryName(id) {
  const c = state.categories.find((x) => x.id === id);
  return c ? c.name : "未分类";
}

function categoryOptions(selected) {
  return [
    h("option", { value: "", selected: selected == null }, "未分类"),
    ...state.categories.map((c) => h("option", { value: c.id, selected: c.id === selected }, c.name)),
  ];
}

// ---------- views ----------
function showLogin() {
  $("#main-view").hidden = true;
  $("#login-view").hidden = false;
  closeSheet();
  setTimeout(() => $("#login-password").focus(), 50);
}

async function showMain() {
  $("#login-view").hidden = true;
  $("#main-view").hidden = false;
  await refresh();
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = $("#login-error");
  err.hidden = true;
  try {
    await api("POST", "/api/login", { password: $("#login-password").value });
    $("#login-password").value = "";
    await showMain();
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
  }
});

async function refresh() {
  const [categories, videos] = await Promise.all([api("GET", "/api/categories"), api("GET", "/api/videos")]);
  state.categories = categories;
  state.videos = videos;
  if (typeof state.filter === "number" && !categories.some((c) => c.id === state.filter)) state.filter = "all";
  render();
  schedulePoll();
}

function schedulePoll() {
  clearTimeout(pollTimer);
  // Keep checking while the server is still transcoding something.
  if (state.videos.some((v) => v.status === "processing")) {
    pollTimer = setTimeout(() => refresh().catch(() => schedulePoll()), 4000);
  }
}

function render() {
  renderChips();
  renderGrid();
  renderUploads();
}

function renderChips() {
  const uncategorized = state.videos.filter((v) => v.category_id == null).length;
  const chip = (key, label, count) =>
    h("button", {
      class: "chip" + (state.filter === key ? " active" : ""),
      type: "button",
      onclick: () => { state.filter = key; render(); },
    }, label, count != null ? h("span", { class: "count" }, count) : null);
  setChildren($("#chips"),
    chip("all", "全部", state.videos.length),
    ...state.categories.map((c) => chip(c.id, c.name, c.video_count)),
    uncategorized ? chip("none", "未分类", uncategorized) : null,
  );
}

function filteredVideos() {
  if (state.filter === "all") return state.videos;
  if (state.filter === "none") return state.videos.filter((v) => v.category_id == null);
  return state.videos.filter((v) => v.category_id === state.filter);
}

function renderGrid() {
  const videos = filteredVideos();
  $("#empty").hidden = videos.length > 0;
  $("#video-grid").replaceChildren(...videos.map(videoCard));
}

function videoCard(v) {
  let thumb;
  if (v.status === "ready") {
    thumb = [
      h("img", { src: rel(v.thumb_url), alt: "", loading: "lazy" }),
      h("span", { class: "duration" }, fmtDuration(v.duration)),
    ];
  } else if (v.status === "processing") {
    thumb = h("div", { class: "status" }, h("div", { class: "spinner" }), "处理中…");
  } else {
    thumb = h("div", { class: "status failed" }, "⚠️ 处理失败");
  }
  return h("button", { class: "card", type: "button", onclick: () => openVideo(v) },
    h("div", { class: "thumb" }, thumb),
    h("div", { class: "title" }, v.title),
  );
}

// ---------- sheet ----------
function openSheet(...children) {
  setChildren($("#sheet-body"), ...children);
  $("#sheet").hidden = false;
  $("#sheet-backdrop").hidden = false;
  $("#sheet").scrollTop = 0;
}

function closeSheet() {
  const video = $("#sheet-body video");
  if (video) video.pause();
  $("#sheet").hidden = true;
  $("#sheet-backdrop").hidden = true;
  $("#sheet-body").replaceChildren();
}

$("#sheet-backdrop").addEventListener("click", closeSheet);

function openVideo(v) {
  const title = h("input", { value: v.title, maxLength: 100 });
  const category = h("select", {}, categoryOptions(v.category_id));
  const save = async () => {
    const body = { title: title.value.trim() || v.title };
    if (category.value === "") body.uncategorized = true;
    else body.category_id = Number(category.value);
    try {
      await api("PATCH", `/api/videos/${v.id}`, body);
      closeSheet();
      toast("已保存");
      await refresh();
    } catch (ex) { toast(ex.message); }
  };
  const remove = async () => {
    if (!confirm(`确定删除「${v.title}」吗？删除后电视上也看不到了。`)) return;
    try {
      await api("DELETE", `/api/videos/${v.id}`);
      closeSheet();
      toast("已删除");
      await refresh();
    } catch (ex) { toast(ex.message); }
  };
  const retry = async () => {
    try {
      await api("POST", `/api/videos/${v.id}/retry`);
      closeSheet();
      await refresh();
    } catch (ex) { toast(ex.message); }
  };

  let preview;
  if (v.status === "ready") {
    preview = h("video", { src: rel(v.video_url), controls: true, playsInline: true, preload: "metadata", poster: rel(v.thumb_url) });
  } else if (v.status === "processing") {
    preview = h("p", { class: "muted" }, "视频正在处理（转成电视能播放的格式），稍等一下就好。");
  } else {
    preview = h("div", {},
      h("p", { class: "error" }, "处理失败：" + (v.error || "未知原因")),
      h("button", { class: "btn small", type: "button", onclick: retry }, "重试"),
    );
  }

  openSheet(
    preview,
    h("div", { style: "height:14px" }),
    v.status === "ready"
      ? h("p", { class: "muted", style: "margin:0 0 12px" },
          `${fmtDuration(v.duration)} · ${v.width}×${v.height} · ${fmtSize(v.size || 0)}`)
      : null,
    h("label", { class: "field" }, h("span", {}, "名称"), title),
    h("label", { class: "field" }, h("span", {}, "分类"), category),
    h("div", { class: "buttons" },
      h("button", { class: "btn danger", type: "button", onclick: remove }, "删除"),
      h("button", { class: "btn primary", type: "button", onclick: save }, "保存"),
    ),
  );
}

// ---------- categories ----------
$("#btn-categories").addEventListener("click", openCategories);

function openCategories() {
  const rows = state.categories.map((c, i) => {
    const input = h("input", { value: c.name, maxLength: 40 });
    const rename = async () => {
      const name = input.value.trim();
      if (!name || name === c.name) return;
      try { await api("PATCH", `/api/categories/${c.id}`, { name }); await refresh(); toast("已改名"); }
      catch (ex) { toast(ex.message); }
    };
    input.addEventListener("change", rename);
    const move = async (dir) => {
      const list = [...state.categories];
      const j = i + dir;
      if (j < 0 || j >= list.length) return;
      [list[i], list[j]] = [list[j], list[i]];
      try {
        await Promise.all(list.map((x, k) => api("PATCH", `/api/categories/${x.id}`, { sort_order: k })));
        await refresh();
        openCategories();
      } catch (ex) { toast(ex.message); }
    };
    const remove = async () => {
      if (!confirm(`删除分类「${c.name}」？里面的 ${c.video_count} 个视频会变成「未分类」，不会被删掉。`)) return;
      try { await api("DELETE", `/api/categories/${c.id}`); await refresh(); openCategories(); }
      catch (ex) { toast(ex.message); }
    };
    return h("div", { class: "cat-row" },
      input,
      h("button", { class: "btn small", type: "button", disabled: i === 0, onclick: () => move(-1), "aria-label": "上移" }, "↑"),
      h("button", { class: "btn small", type: "button", disabled: i === state.categories.length - 1, onclick: () => move(1), "aria-label": "下移" }, "↓"),
      h("button", { class: "btn small", type: "button", onclick: remove, "aria-label": "删除" }, "✕"),
    );
  });

  const newName = h("input", { placeholder: "新分类，例如：中国舞、本周作业", maxLength: 40 });
  const add = async () => {
    const name = newName.value.trim();
    if (!name) return newName.focus();
    try { await api("POST", "/api/categories", { name }); await refresh(); openCategories(); }
    catch (ex) { toast(ex.message); }
  };
  newName.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });

  openSheet(
    h("h2", {}, "管理分类"),
    rows.length ? rows : h("p", { class: "muted" }, "还没有分类。可以按舞种或课程来分，电视上会按分类显示。"),
    h("div", { class: "cat-row", style: "margin-top:16px" },
      newName,
      h("button", { class: "btn primary", type: "button", onclick: add }, "添加"),
    ),
    h("p", { class: "muted" }, "改名后点别处即可保存；用 ↑↓ 调整电视上的显示顺序。"),
  );
}

// ---------- TV pairing ----------
$("#btn-pair").addEventListener("click", () => {
  const code = h("input", {
    class: "code-input", inputMode: "numeric", maxLength: 6, placeholder: "······", autocomplete: "one-time-code",
  });
  const submit = async () => {
    const value = code.value.replace(/\D/g, "");
    if (value.length !== 6) return toast("请输入电视上显示的 6 位数字");
    try {
      await api("POST", "/api/pair/confirm", { code: value });
      closeSheet();
      toast("绑定成功，电视马上就能看到视频了 🎉", 3500);
    } catch (ex) { toast(ex.message); }
  };
  code.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
  openSheet(
    h("h2", {}, "绑定电视"),
    h("p", { class: "muted" }, "在电视上打开「舞蹈练习」App，屏幕上会显示 6 位配对码，输入到下面："),
    h("div", { class: "field" }, code),
    h("button", { class: "btn primary block", type: "button", onclick: submit }, "绑定"),
  );
  setTimeout(() => code.focus(), 50);
});

// ---------- upload ----------
$("#file-input").addEventListener("change", (e) => {
  const files = [...e.target.files];
  e.target.value = "";
  if (files.length) openUploadForm(files);
});

function openUploadForm(files) {
  const defaultCat = typeof state.filter === "number" ? state.filter : null;
  const category = h("select", {}, categoryOptions(defaultCat));
  const titles = files.map((f) => h("input", { value: f.name.replace(/\.[^.]+$/, ""), maxLength: 100 }));
  const start = () => {
    const categoryId = category.value === "" ? null : Number(category.value);
    files.forEach((file, i) => {
      state.uploads.push({
        id: Math.random().toString(36).slice(2),
        file,
        title: titles[i].value.trim(),
        categoryId,
        uploaded: 0,
        status: "waiting",
        error: null,
        uploadId: null,
      });
    });
    closeSheet();
    renderUploads();
    runUploads();
  };
  openSheet(
    h("h2", {}, files.length > 1 ? `上传 ${files.length} 个视频` : "上传视频"),
    h("label", { class: "field" }, h("span", {}, "放到哪个分类"), category),
    ...files.map((f, i) => h("label", { class: "file-row" },
      h("span", { class: "muted" }, files.length > 1 ? `第 ${i + 1} 个名称` : "名称"),
      titles[i],
      h("small", {}, `${f.name} · ${fmtSize(f.size)}`),
    )),
    h("button", { class: "btn primary block", type: "button", onclick: start }, "开始上传"),
    h("p", { class: "muted" }, "上传过程中请保持页面打开、手机不要锁屏。网络断了会自动续传。"),
  );
}

function renderUploads() {
  const box = $("#upload-queue");
  const items = state.uploads;
  box.hidden = items.length === 0;
  box.replaceChildren(...items.map((u) => {
    const pct = u.file.size ? Math.floor((u.uploaded / u.file.size) * 100) : 0;
    const label = {
      waiting: "等待中",
      uploading: `${pct}%`,
      finishing: "收尾中…",
      done: "完成 ✓",
      error: "失败",
    }[u.status];
    return h("div", { class: `upload-item ${u.status}` },
      h("div", { class: "row" }, h("span", { class: "name" }, u.title || u.file.name), h("span", { class: "pct" }, label)),
      h("div", { class: "bar" }, h("div", { style: `width:${u.status === "done" ? 100 : pct}%` })),
      u.status === "error" ? h("div", {},
        h("p", { class: "error", style: "margin:4px 0 0" }, u.error),
        h("div", { class: "actions" },
          h("button", { class: "btn small", type: "button", onclick: () => { u.status = "waiting"; u.error = null; renderUploads(); runUploads(); } }, "重试"),
          h("button", { class: "btn small", type: "button", onclick: () => cancelUpload(u) }, "取消"),
        ),
      ) : null,
    );
  }));
}

async function cancelUpload(u) {
  state.uploads = state.uploads.filter((x) => x !== u);
  renderUploads();
  if (u.uploadId) api("DELETE", `/api/uploads/${u.uploadId}`).catch(() => {});
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function uploadOne(u) {
  if (!u.uploadId) {
    const init = await api("POST", "/api/uploads", {
      filename: u.file.name, size: u.file.size, title: u.title, category_id: u.categoryId,
    });
    u.uploadId = init.upload_id;
    u.chunkSize = init.chunk_size;
  } else {
    // Resuming after a failure: ask the server how much it already has.
    const st = await api("GET", `/api/uploads/${u.uploadId}`);
    u.uploaded = st.received;
    u.chunkSize = u.chunkSize || 8 * 1024 * 1024;
  }

  let failures = 0;
  while (u.uploaded < u.file.size) {
    const end = Math.min(u.uploaded + u.chunkSize, u.file.size);
    try {
      const res = await api("PUT", `/api/uploads/${u.uploadId}?offset=${u.uploaded}`, u.file.slice(u.uploaded, end));
      u.uploaded = res.received;
      failures = 0;
    } catch (ex) {
      if (ex.status === 409 && ex.body && typeof ex.body.received === "number") {
        u.uploaded = ex.body.received;
        continue;
      }
      if (ex.status && ex.status !== 0 && ex.status < 500 && ex.status !== 408) throw ex;
      // Network hiccup or server error: back off and resume from what the server has.
      if (++failures > 8) throw new Error("网络不稳定，上传中断了，可以点重试继续");
      renderUploads();
      await sleep(Math.min(30000, 1000 * 2 ** failures));
      try { u.uploaded = (await api("GET", `/api/uploads/${u.uploadId}`)).received; } catch { /* retry loop */ }
    }
    renderUploads();
  }
  u.status = "finishing";
  renderUploads();
  await api("POST", `/api/uploads/${u.uploadId}/complete`);
}

async function runUploads() {
  if (state.uploading) return;
  state.uploading = true;
  let wakeLock = null;
  try { wakeLock = await navigator.wakeLock?.request("screen"); } catch { /* not supported */ }
  try {
    let next;
    while ((next = state.uploads.find((u) => u.status === "waiting"))) {
      next.status = "uploading";
      renderUploads();
      try {
        await uploadOne(next);
        next.status = "done";
        refresh().catch(() => {});
      } catch (ex) {
        next.status = "error";
        next.error = ex.message || "上传失败";
        if (ex.status === 404) { next.uploadId = null; next.uploaded = 0; } // server forgot it; start over
      }
      renderUploads();
    }
  } finally {
    state.uploading = false;
    try { await wakeLock?.release(); } catch { /* ignore */ }
  }
  // Clear finished items after a moment; keep failed ones visible.
  setTimeout(() => {
    state.uploads = state.uploads.filter((u) => u.status !== "done");
    renderUploads();
  }, 3000);
}

window.addEventListener("beforeunload", (e) => {
  if (state.uploads.some((u) => u.status === "uploading" || u.status === "waiting" || u.status === "finishing")) {
    e.preventDefault();
    e.returnValue = "";
  }
});

// Re-acquire fresh data when coming back to the tab.
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && !$("#main-view").hidden) refresh().catch(() => {});
});

// ---------- boot ----------
api("GET", "/api/me").then(showMain).catch(() => showLogin());
