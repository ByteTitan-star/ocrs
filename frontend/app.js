/* OCR 对比台前端逻辑：上传 → 轮询 → 双栏对比 / Diff */
"use strict";

const $ = (sel) => document.querySelector(sel);
const state = {
  engines: [],          // [{name,label,available,detail,mock}]
  task: null,           // 最近一次任务状态
  markdowns: {},        // engine -> 原始 markdown 文本
  fetched: {},          // engine -> bool
  view: "preview",      // preview | source | diff
  pollTimer: null,
  file: null,
};

/* ---------- 初始化 ---------- */
async function init() {
  try {
    const res = await fetch("/api/engines");
    const data = await res.json();
    state.engines = data.engines || [];
    renderBadges(data);
  } catch {
    renderBadges(null);
  }
  bindUpload();
  bindToolbar();
}

function renderBadges(info) {
  const wrap = $("#engineBadges");
  wrap.innerHTML = "";
  if (!info) {
    wrap.innerHTML = '<span class="badge bad"><span class="dot"></span>后端未连接</span>';
    return;
  }
  for (const e of info.engines) {
    const b = document.createElement("span");
    b.className = "badge " + (e.available ? "ok" : "bad");
    b.title = e.available ? e.detail : `${e.detail}（${e.setup_hint || ""}）`;
    b.innerHTML = `<span class="dot"></span>${e.label}${e.available ? "" : " · 不可用"}`;
    wrap.appendChild(b);
  }
}

/* ---------- 上传 ---------- */
function bindUpload() {
  const dz = $("#dropzone"), input = $("#fileInput");
  dz.addEventListener("click", () => input.click());
  dz.addEventListener("dragover", (ev) => { ev.preventDefault(); dz.classList.add("dragover"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("dragover"));
  dz.addEventListener("drop", (ev) => {
    ev.preventDefault();
    dz.classList.remove("dragover");
    pickFile(ev.dataTransfer.files[0]);
  });
  input.addEventListener("change", () => pickFile(input.files[0]));
  $("#startBtn").addEventListener("click", startTask);
  $("#resetBtn").addEventListener("click", resetAll);
}

function pickFile(file) {
  const hint = $("#dzHint");
  hint.classList.remove("dz-error");
  if (!file) return;
  if (!/\.pdf$/i.test(file.name)) {
    hint.textContent = "只支持 PDF 文件";
    hint.classList.add("dz-error");
    return;
  }
  state.file = file;
  $("#fileName").textContent = `${file.name}（${(file.size / 1024 / 1024).toFixed(2)} MB）`;
  $("#fileRow").classList.remove("hidden");
  hint.textContent = "两个引擎将并行识别，完成后并排展示 Markdown";
}

async function startTask() {
  if (!state.file) return;
  const btn = $("#startBtn");
  btn.disabled = true;
  btn.textContent = "上传中…";
  try {
    const form = new FormData();
    form.append("file", state.file);
    const res = await fetch("/api/tasks", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `上传失败（${res.status}）`);
    showProgress(data);
    pollTask(data.task_id);
  } catch (err) {
    const hint = $("#dzHint");
    hint.textContent = err.message;
    hint.classList.add("dz-error");
  } finally {
    btn.disabled = false;
    btn.textContent = "开始对比";
  }
}

function resetAll() {
  if (state.pollTimer) clearTimeout(state.pollTimer);
  state.task = null;
  state.markdowns = {};
  state.fetched = {};
  state.file = null;
  $("#fileInput").value = "";
  $("#fileRow").classList.add("hidden");
  $("#progressCard").classList.add("hidden");
  $("#resultsCard").classList.add("hidden");
  $("#uploadCard").classList.remove("hidden");
}

/* ---------- 轮询与进度 ---------- */
function showProgress(created) {
  $("#uploadCard").classList.add("hidden");
  $("#progressCard").classList.remove("hidden");
  $("#taskTitle").textContent = created.filename || "";
  $("#taskSub").textContent = `共 ${created.pages} 页 · 引擎：${created.engines.join(" / ")}`;
  const grid = $("#progressGrid");
  grid.innerHTML = "";
  for (const name of created.engines) {
    const label = (state.engines.find((e) => e.name === name) || {}).label || name;
    grid.insertAdjacentHTML("beforeend", `
      <div class="engine-progress" id="ep-${name}">
        <div class="ep-head">
          <span class="ep-name">${label}</span>
          <span class="ep-state pending" id="ep-state-${name}">排队中</span>
        </div>
        <div class="bar"><i id="ep-bar-${name}"></i></div>
        <div class="ep-note" id="ep-note-${name}"></div>
        <div class="ep-error hidden" id="ep-err-${name}"></div>
      </div>`);
  }
}

const STATE_TEXT = { pending: "排队中", loading: "加载模型中", running: "识别中", done: "完成", error: "失败" };

function pollTask(taskId) {
  state.pollTimer = setTimeout(async () => {
    try {
      const res = await fetch(`/api/tasks/${taskId}`);
      if (res.ok) {
        const task = await res.json();
        state.task = task;
        let allDone = true;
        for (const [name, st] of Object.entries(task.engines)) {
          updateEngineProgress(name, st);
          if (st.status === "done" && !state.fetched[name]) await fetchMarkdown(taskId, name);
          if (!["done", "error"].includes(st.status)) allDone = false;
        }
        if (allDone) { renderResults(); return; }
      }
    } catch { /* 网络抖动时继续轮询 */ }
    pollTask(taskId);
  }, 1200);
}

function updateEngineProgress(name, st) {
  const stateEl = $(`#ep-state-${name}`), bar = $(`#ep-bar-${name}`),
        note = $(`#ep-note-${name}`), errEl = $(`#ep-err-${name}`);
  if (!stateEl) return;
  stateEl.textContent = STATE_TEXT[st.status] || st.status;
  stateEl.className = `ep-state ${st.status}`;
  const pct = st.total ? Math.round((st.done / st.total) * 100) : (st.status === "done" ? 100 : 6);
  bar.style.width = `${pct}%`;
  note.textContent = st.note || "";
  if (st.status === "loading") bar.style.width = "8%";
  if (st.error) {
    errEl.textContent = st.error;
    errEl.classList.remove("hidden");
  }
}

async function fetchMarkdown(taskId, engine) {
  state.fetched[engine] = true;
  try {
    const res = await fetch(`/api/tasks/${taskId}/markdown/${engine}`);
    if (res.ok) state.markdowns[engine] = await res.text();
  } catch { /* 下次渲染时按缺失处理 */ }
}

/* ---------- 结果渲染 ---------- */
function renderResults() {
  $("#progressCard").classList.add("hidden");
  $("#resultsCard").classList.remove("hidden");
  renderColumns();
  renderDownloadButtons();
  applyView();
}

function engineLabel(name) {
  const e = state.engines.find((x) => x.name === name);
  return (e && e.label) || name;
}

function renderColumns() {
  const wrap = $("#resultColumns");
  wrap.innerHTML = "";
  const engines = state.task ? Object.keys(state.task.engines) : Object.keys(state.markdowns);
  for (const name of engines) {
    const st = (state.task && state.task.engines[name]) || {};
    const md = state.markdowns[name] || "";
    const meta = [
      st.elapsed_ms ? `耗时 ${(st.elapsed_ms / 1000).toFixed(1)}s` : "",
      md ? `${md.length} 字符` : "",
    ].filter(Boolean).join(" · ");
    const bodyHtml = st.status === "error"
      ? `<div class="empty-hint">该引擎识别失败：<br><span style="color:var(--red)">${escapeHtml(st.error || "")}</span></div>`
      : md
        ? `<div class="pane pane-preview"><div class="md-body">${renderMarkdown(md)}</div></div>
           <pre class="pane pane-source">${escapeHtml(md)}</pre>`
        : `<div class="empty-hint">暂无结果</div>`;
    wrap.insertAdjacentHTML("beforeend", `
      <div class="column">
        <div class="col-head">
          <span class="col-name">${engineLabel(name)}</span>
          <span class="col-meta"><span>${meta}</span>
            <button class="btn small" data-copy="${name}">复制源码</button></span>
        </div>
        <div class="col-body" data-engine="${name}">${bodyHtml}</div>
      </div>`);
  }
  wrap.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await navigator.clipboard.writeText(state.markdowns[btn.dataset.copy] || "");
      btn.textContent = "已复制";
      setTimeout(() => (btn.textContent = "复制源码"), 1200);
    });
  });
  bindSyncScroll();
}

function renderDownloadButtons() {
  const wrap = $("#downloadButtons");
  wrap.innerHTML = "";
  if (!state.task) return;
  for (const name of Object.keys(state.markdowns)) {
    const btn = document.createElement("a");
    btn.className = "btn small";
    btn.href = `/api/tasks/${state.task.id}/download/${name}`;
    btn.textContent = `下载 ${name}.md`;
    wrap.appendChild(btn);
  }
}

function renderMarkdown(md) {
  const html = marked.parse(md, { gfm: true, breaks: false });
  return DOMPurify.sanitize(html, { ADD_TAGS: ["svg"], ADD_ATTR: ["target"] });
}

/* ---------- 视图切换 ---------- */
function bindToolbar() {
  $("#viewTabs").addEventListener("click", (ev) => {
    const tab = ev.target.closest(".tab");
    if (!tab) return;
    state.view = tab.dataset.view;
    document.querySelectorAll("#viewTabs .tab").forEach((t) => t.classList.toggle("active", t === tab));
    applyView();
  });
}

function applyView() {
  const twoCols = state.view === "preview" || state.view === "source";
  $("#resultColumns").classList.toggle("hidden", !twoCols);
  $("#diffWrap").classList.toggle("hidden", state.view !== "diff");
  document.querySelectorAll(".pane-preview").forEach((el) => {
    el.classList.toggle("hidden", state.view !== "preview");
  });
  document.querySelectorAll(".pane-source").forEach((el) => {
    el.classList.toggle("hidden", state.view !== "source");
  });
  if (state.view === "diff") renderDiff();
}

/* ---------- 同步滚动 ---------- */
function bindSyncScroll() {
  const bodies = document.querySelectorAll(".col-body");
  bodies.forEach((el) => {
    el.onscroll = () => {
      if (!$("#syncScroll").checked || el.dataset.syncing) return;
      const ratio = el.scrollTop / Math.max(1, el.scrollHeight - el.clientHeight);
      bodies.forEach((other) => {
        if (other === el) return;
        other.dataset.syncing = "1";
        other.scrollTop = ratio * (other.scrollHeight - other.clientHeight);
        delete other.dataset.syncing;
      });
    };
  });
}

/* ---------- Diff ---------- */
function buildDiffRows(left, right) {
  const changes = window.Diff.diffLines(left, right);
  const rows = [];
  let pendingL = [], pendingR = [];
  const flush = () => {
    const n = Math.max(pendingL.length, pendingR.length);
    for (let i = 0; i < n; i++) {
      const l = pendingL[i], r = pendingR[i];
      if (l !== undefined && r !== undefined) rows.push({ type: "diff", l, r });
      else if (l !== undefined) rows.push({ type: "diff", l, r: "" });
      else rows.push({ type: "diff", l: "", r });
    }
    pendingL = []; pendingR = [];
  };
  for (const c of changes) {
    const lines = c.value.replace(/\n$/, "").split("\n");
    if (c.added) pendingR.push(...lines);
    else if (c.removed) pendingL.push(...lines);
    else { flush(); for (const line of lines) rows.push({ type: "same", l: line, r: line }); }
  }
  flush();
  return rows;
}

function diffEngineOrder() {
  // 按任务里的引擎顺序固定左右栏（dots 在左、paddle 在右），与双栏视图一致
  const order = state.task ? Object.keys(state.task.engines) : [];
  return order.length >= 2 ? order : Object.keys(state.markdowns);
}

function renderDiff() {
  const names = diffEngineOrder().filter((n) => n in state.markdowns);
  if (names.length < 2) {
    $("#diffScroll").innerHTML = '<div class="empty-hint">需要两个引擎都完成才能对比差异</div>';
    $("#diffStat").textContent = "";
    return;
  }
  const [leftName, rightName] = names;
  $("#diffLegend").innerHTML =
    `差异说明：<span class="chip chip-del">红色 = ${engineLabel(leftName)} 独有</span> ` +
    `<span class="chip chip-add">绿色 = ${engineLabel(rightName)} 独有</span>`;
  const rows = buildDiffRows(state.markdowns[leftName] || "", state.markdowns[rightName] || "");
  const diffCount = rows.filter((r) => r.type === "diff").length;
  $("#diffStat").textContent = `共 ${rows.length} 行，其中 ${diffCount} 行存在差异`;
  const head = `
    <table class="diff"><tbody>
      <tr class="d-diff" style="position:sticky;top:0">
        <td class="l" style="background:#f3f5f8;font-weight:700">${engineLabel(leftName)}</td>
        <td class="r" style="background:#f3f5f8;font-weight:700">${engineLabel(rightName)}</td>
      </tr>`;
  const body = rows.map((r) =>
    r.type === "same"
      ? `<tr><td class="l">${escapeHtml(r.l)}</td><td class="r">${escapeHtml(r.r)}</td></tr>`
      : `<tr class="d-diff"><td class="l">${escapeHtml(r.l)}</td><td class="r">${escapeHtml(r.r)}</td></tr>`
  ).join("");
  $("#diffScroll").innerHTML = head + body + "</tbody></table>";
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

init();
