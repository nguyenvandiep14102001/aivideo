(() => {
  const projectId = window.AIVIDEO_PROJECT_ID;
  let status = window.AIVIDEO_STATUS;
  if (!projectId) return;

  const statusText = document.getElementById("status-text");
  const renderBtn = document.getElementById("render-btn");
  const pauseBtn = document.getElementById("pause-btn");
  const cancelBtn = document.getElementById("cancel-btn");
  const videoBox = document.getElementById("video-box");
  const progressWrap = document.getElementById("render-progress");
  const progressBar = document.getElementById("render-progress-bar");
  const progressPct = document.getElementById("render-progress-pct");
  const progressMsg = document.getElementById("render-progress-msg");
  const charInput = document.getElementById("character_id");
  const track = document.getElementById("timeline-track");
  const timeline = document.getElementById("sfx-timeline");
  const ruler = document.getElementById("timeline-ruler");
  const playhead = document.getElementById("timeline-playhead");
  const saveStatus = document.getElementById("sfx-save-status");
  const exportBtn = document.getElementById("sfx-export");
  const timelineVideo = document.getElementById("timeline-video");
  const previewVideo = document.getElementById("preview-video");
  const sfxPanel = document.getElementById("sfx-panel");
  const renderForm = document.getElementById("render-form");

  let duration = Math.max(4, Number(window.AIVIDEO_DURATION) || 12);
  let clips = Array.isArray(window.AIVIDEO_SFX_CLIPS)
    ? window.AIVIDEO_SFX_CLIPS.map((c) => ({ ...c }))
    : [];
  let polling = false;

  function uid() {
    return Math.random().toString(16).slice(2, 10);
  }

  function videoReady() {
    return !!(timelineVideo && timelineVideo.getAttribute("src")) ||
      (sfxPanel && sfxPanel.dataset.ready === "1");
  }

  function updateRenderControls() {
    const running = ["queued", "rendering"].includes(status);
    const paused = status === "paused";
    if (renderBtn) {
      const busy = running || paused;
      renderBtn.disabled = busy;
      renderBtn.textContent = busy ? "Đang render…" : "1) Render video 9:16";
    }
    if (pauseBtn) {
      const canPause = running || paused;
      pauseBtn.disabled = !canPause;
      pauseBtn.textContent = paused ? "Tiếp tục render" : "Tạm dừng render";
    }
    if (cancelBtn) {
      cancelBtn.disabled = !(running || paused);
    }
    if (progressWrap) {
      const show = running || paused;
      progressWrap.classList.toggle("hidden", !show);
      if (show) progressWrap.removeAttribute("hidden");
      else progressWrap.setAttribute("hidden", "");
    }
  }

  function updateProgress(percent, message) {
    const pct = Math.max(0, Math.min(100, Number(percent) || 0));
    if (progressBar) progressBar.style.width = `${pct}%`;
    if (progressPct) progressPct.textContent = `${Math.round(pct)}%`;
    if (progressMsg) {
      progressMsg.textContent = message || (pct > 0 ? "Đang render…" : "Đang chờ…");
    }
  }

  function loadVideoIntoTimeline(url) {
    if (!timelineVideo) return;
    timelineVideo.src = url;
    timelineVideo.load();
    if (previewVideo) {
      previewVideo.src = url;
      previewVideo.load();
    }
    if (sfxPanel) sfxPanel.dataset.ready = "1";
    if (exportBtn) exportBtn.disabled = false;
    const hint = document.getElementById("sfx-locked-hint");
    if (hint) hint.remove();
    timelineVideo.onloadedmetadata = () => {
      if (timelineVideo.duration && isFinite(timelineVideo.duration)) {
        duration = timelineVideo.duration;
        if (timeline) timeline.dataset.duration = String(duration);
        buildRuler();
        renderClips();
      }
    };
  }

  function buildRuler() {
    if (!ruler) return;
    ruler.innerHTML = "";
    const step = duration <= 20 ? 2 : duration <= 60 ? 5 : 10;
    for (let t = 0; t <= duration + 0.01; t += step) {
      const mark = document.createElement("span");
      mark.style.left = `${(t / duration) * 100}%`;
      mark.textContent = `${t.toFixed(0)}s`;
      ruler.appendChild(mark);
    }
  }

  function renderClips() {
    if (!track) return;
    track.innerHTML = "";
    const meta = {};
    document.querySelectorAll(".sfx-chip").forEach((chip) => {
      meta[chip.dataset.sfxId] = {
        label: chip.dataset.label,
        color: chip.dataset.color,
        dur: Number(chip.dataset.dur) || 0.3,
      };
    });
    clips.forEach((clip) => {
      const info = meta[clip.sfx_id] || { label: clip.sfx_id, color: "#e8a35a", dur: 0.4 };
      const el = document.createElement("div");
      el.className = "sfx-block";
      el.style.setProperty("--chip", info.color);
      el.style.left = `${(clip.start / duration) * 100}%`;
      el.style.width = `${Math.max(2.5, (info.dur / duration) * 100)}%`;
      el.innerHTML = `<span>${info.label}</span><button type="button" title="Xóa">×</button>`;
      el.querySelector("button").addEventListener("click", (e) => {
        e.stopPropagation();
        clips = clips.filter((c) => c.id !== clip.id);
        renderClips();
      });

      let dragging = false;
      let startX = 0;
      let originStart = 0;
      el.addEventListener("pointerdown", (e) => {
        if (e.target.tagName === "BUTTON") return;
        dragging = true;
        startX = e.clientX;
        originStart = clip.start;
        el.setPointerCapture(e.pointerId);
      });
      el.addEventListener("pointermove", (e) => {
        if (!dragging) return;
        const rect = track.getBoundingClientRect();
        const dx = e.clientX - startX;
        const dt = (dx / rect.width) * duration;
        clip.start = Math.max(0, Math.min(duration - 0.05, originStart + dt));
        el.style.left = `${(clip.start / duration) * 100}%`;
      });
      el.addEventListener("pointerup", () => {
        dragging = false;
      });
      track.appendChild(el);
    });
  }

  function addClipAt(sfxId, clientX) {
    if (!videoReady()) {
      if (saveStatus) saveStatus.textContent = "Hãy Render video trước";
      return;
    }
    const rect = track.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    clips.push({ id: uid(), sfx_id: sfxId, start: ratio * duration, volume: 0.85 });
    try {
      const audio = new Audio(`/sfx/${sfxId}`);
      audio.volume = 0.5;
      audio.play().catch(() => {});
    } catch (_) {}
    renderClips();
  }

  async function poll() {
    if (polling) return;
    if (!["queued", "rendering", "paused"].includes(status)) return;
    polling = true;
    try {
      const res = await fetch(`/api/projects/${projectId}/status`);
      const data = await res.json();
      status = data.status;
      if (statusText) statusText.textContent = status;
      updateProgress(data.progress, data.progress_message || "");
      updateRenderControls();
      if (status === "ready") {
        updateProgress(100, "Hoàn tất");
        const url = `/projects/${projectId}/video?t=${Date.now()}`;
        if (data.duration_sec) duration = Number(data.duration_sec) || duration;
        loadVideoIntoTimeline(url);
        if (videoBox) {
          videoBox.classList.remove("hidden");
          const v = videoBox.querySelector("video");
          if (v) v.src = url;
        }
        if (saveStatus) {
          saveStatus.textContent = "Video đã vào timeline — kéo SFX rồi bấm Xuất video + SFX";
        }
        if (sfxPanel) sfxPanel.scrollIntoView({ behavior: "smooth", block: "start" });
        setTimeout(() => updateRenderControls(), 2000);
        polling = false;
        return;
      }
      if (status === "error") {
        location.reload();
        return;
      }
    } catch (_) {}
    polling = false;
    setTimeout(poll, 500);
  }

  document.querySelectorAll(".char-card").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".char-card").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".char-card-wrap").forEach((w) => w.classList.remove("active"));
      btn.classList.add("active");
      const wrap = btn.closest(".char-card-wrap");
      if (wrap) wrap.classList.add("active");
      if (charInput) charInput.value = btn.dataset.id;
      if (typeof scheduleAutosave === "function") scheduleAutosave();
    });
  });

  document.querySelectorAll(".sfx-chip").forEach((chip) => {
    chip.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/sfx-id", chip.dataset.sfxId);
      e.dataTransfer.effectAllowed = "copy";
    });
    chip.addEventListener("click", () => {
      if (!videoReady()) {
        if (saveStatus) saveStatus.textContent = "Hãy Render video trước";
        return;
      }
      let start = 0;
      if (timelineVideo && timelineVideo.currentTime) start = timelineVideo.currentTime;
      else if (playhead) start = (parseFloat(playhead.style.left || "0") / 100) * duration;
      clips.push({ id: uid(), sfx_id: chip.dataset.sfxId, start, volume: 0.85 });
      try {
        const audio = new Audio(`/sfx/${chip.dataset.sfxId}`);
        audio.volume = 0.5;
        audio.play().catch(() => {});
      } catch (_) {}
      renderClips();
    });
  });

  if (timeline && track) {
    track.addEventListener("dragover", (e) => {
      e.preventDefault();
      timeline.classList.add("drop-target");
    });
    track.addEventListener("dragleave", () => timeline.classList.remove("drop-target"));
    track.addEventListener("drop", (e) => {
      e.preventDefault();
      timeline.classList.remove("drop-target");
      const sfxId = e.dataTransfer.getData("text/sfx-id");
      if (sfxId) addClipAt(sfxId, e.clientX);
    });
    track.addEventListener("click", (e) => {
      if (e.target !== track) return;
      const rect = track.getBoundingClientRect();
      const ratio = (e.clientX - rect.left) / rect.width;
      if (playhead) playhead.style.left = `${ratio * 100}%`;
      if (timelineVideo && timelineVideo.duration) {
        timelineVideo.currentTime = ratio * timelineVideo.duration;
      }
    });
  }

  if (timelineVideo && playhead) {
    timelineVideo.addEventListener("timeupdate", () => {
      const d = timelineVideo.duration || duration;
      playhead.style.left = `${(timelineVideo.currentTime / d) * 100}%`;
    });
  }

  const saveBtn = document.getElementById("sfx-save");
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      if (saveStatus) saveStatus.textContent = "Đang lưu…";
      try {
        const res = await fetch(`/api/projects/${projectId}/sfx`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ clips }),
        });
        if (!res.ok) throw new Error("save failed");
        if (saveStatus) saveStatus.textContent = `Đã lưu ${clips.length} SFX`;
      } catch (_) {
        if (saveStatus) saveStatus.textContent = "Lỗi lưu SFX";
      }
    });
  }

  const clearBtn = document.getElementById("sfx-clear");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      clips = [];
      renderClips();
      if (saveStatus) saveStatus.textContent = "Đã xóa SFX";
    });
  }

  if (exportBtn) {
    exportBtn.addEventListener("click", async () => {
      if (!videoReady()) {
        if (saveStatus) saveStatus.textContent = "Hãy Render trước";
        return;
      }
      exportBtn.disabled = true;
      if (saveStatus) saveStatus.textContent = "Đang xuất video + SFX…";
      try {
        const res = await fetch(`/api/projects/${projectId}/export-sfx`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ clips }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "export failed");
        const url = data.url || `/projects/${projectId}/video?t=${Date.now()}`;
        loadVideoIntoTimeline(url);
        if (videoBox) {
          videoBox.classList.remove("hidden");
          const v = videoBox.querySelector("video");
          if (v) v.src = url;
        }
        if (saveStatus) saveStatus.textContent = `Đã xuất ${clips.length} SFX vào video`;
      } catch (err) {
        if (saveStatus) saveStatus.textContent = `Lỗi xuất: ${err.message || err}`;
      } finally {
        exportBtn.disabled = false;
      }
    });
  }

  if (pauseBtn) {
    pauseBtn.addEventListener("click", async () => {
      try {
        const action = status === "paused" ? "resume" : "pause";
        pauseBtn.disabled = true;
        const res = await fetch(`/api/projects/${projectId}/${action}`, { method: "POST" });
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.detail || "action failed");
        status = data.status || status;
        if (statusText) statusText.textContent = status;
        updateRenderControls();
        poll();
      } catch (err) {
        if (saveStatus) {
          saveStatus.textContent = `Lỗi ${status === "paused" ? "tiếp tục" : "tạm dừng"}: ${err.message || err}`;
        }
        updateRenderControls();
      }
    });
  }

  if (cancelBtn) {
    cancelBtn.addEventListener("click", async () => {
      if (!confirm("Dừng hẳn và không render nữa?")) return;
      try {
        cancelBtn.disabled = true;
        const res = await fetch(`/api/projects/${projectId}/cancel`, { method: "POST" });
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.detail || "cancel failed");
        status = data.status || "draft";
        if (statusText) statusText.textContent = status;
        updateProgress(0, "Đã hủy render");
        updateRenderControls();
      } catch (err) {
        alert(err.message || "Không hủy được render");
        updateRenderControls();
      }
    });
  }

  // ---- Script tabs + autosave ----
  function clamp(n, a, b) {
    return Math.max(a, Math.min(b, n));
  }

  function readFrameFor(name) {
    const q = (key) =>
      document.querySelector(`[data-frame-ctrl="${name}"][data-key="${key}"]`);
    const modeEl = q("mode");
    const zoomEl = q("zoom");
    const xEl = q("x");
    const yEl = q("y");
    const mode = (modeEl && modeEl.value) || "cover";
    const zoom = Number(zoomEl && zoomEl.value) || 1;
    const x = Number(xEl && xEl.value);
    const y = Number(yEl && yEl.value);
    return {
      mode: mode === "contain" ? "contain" : "cover",
      zoom: clamp(zoom, 1, 3),
      x: clamp(Number.isFinite(x) ? x : 0.5, 0, 1),
      y: clamp(Number.isFinite(y) ? y : 0.5, 0, 1),
    };
  }

  function syncImageFrames() {
    const hidden = document.getElementById("image_frames_json");
    if (!hidden) return;
    const names = [
      ...new Set(
        [...document.querySelectorAll("[data-frame-ctrl]")].map((el) =>
          el.getAttribute("data-frame-ctrl")
        )
      ),
    ].filter(Boolean);
    const frames = {};
    names.forEach((name) => {
      frames[name] = readFrameFor(name);
    });
    hidden.value = JSON.stringify(frames);
    const cards = [...document.querySelectorAll(".frame-card[data-img-name]")];
    const setLegacy = (idx, fr) => {
      const n = idx + 1;
      const mode = document.getElementById(`legacy_frame_${n}_mode`);
      const zoom = document.getElementById(`legacy_frame_${n}_zoom`);
      const x = document.getElementById(`legacy_frame_${n}_x`);
      const y = document.getElementById(`legacy_frame_${n}_y`);
      if (!fr || !mode) return;
      mode.value = fr.mode;
      zoom.value = String(fr.zoom);
      x.value = String(fr.x);
      y.value = String(fr.y);
    };
    if (cards[0]) setLegacy(0, frames[cards[0].getAttribute("data-img-name")]);
    if (cards[1]) setLegacy(1, frames[cards[1].getAttribute("data-img-name")]);
  }

  const scriptCountEl = document.getElementById("script-count");
  const scriptTabsEl = document.getElementById("script-tabs");
  const scriptPanelsEl = document.getElementById("script-panels");
  const scriptCombined = document.getElementById("script-combined");
  const autosaveStatus = document.getElementById("autosave-status");
  const imagesMeta = Array.isArray(window.AIVIDEO_IMAGES) ? window.AIVIDEO_IMAGES : [];
  let activeScriptTab = 0;
  let autosaveTimer = null;
  let autosaving = false;

  const savedFrames = (window.AIVIDEO_IMAGE_FRAMES && typeof window.AIVIDEO_IMAGE_FRAMES === "object")
    ? { ...window.AIVIDEO_IMAGE_FRAMES }
    : {};

  function imageOptionsHtml(selected) {
    let html = `<option value="">— Mặc định —</option>`;
    imagesMeta.forEach((img, idx) => {
      const sel = selected === img.name ? " selected" : "";
      const label = (img.original || img.name || "").replace(/</g, "&lt;");
      html += `<option value="${img.name}"${sel}>${idx + 1}. ${label}</option>`;
    });
    return html;
  }

  function resolvePair(si) {
    const leftSel = scriptPanelsEl && scriptPanelsEl.querySelector(`.seg-left[data-seg="${si}"]`);
    const rightSel = scriptPanelsEl && scriptPanelsEl.querySelector(`.seg-right[data-seg="${si}"]`);
    const leftName = (leftSel && leftSel.value) || (imagesMeta[2 * si] && imagesMeta[2 * si].name) || "";
    const rightName = (rightSel && rightSel.value) || (imagesMeta[2 * si + 1] && imagesMeta[2 * si + 1].name) || leftName;
    const left = imagesMeta.find((x) => x.name === leftName) || null;
    const right = imagesMeta.find((x) => x.name === rightName) || null;
    return { left, right };
  }

  function frameDefaults(name) {
    const cur = savedFrames[name] || {};
    return {
      mode: cur.mode === "contain" ? "contain" : "cover",
      zoom: Number(cur.zoom) || 1,
      x: cur.x != null ? Number(cur.x) : 0.5,
      y: cur.y != null ? Number(cur.y) : 0.5,
    };
  }

  function frameCardHtml(img, label) {
    if (!img) return "";
    const fr = frameDefaults(img.name);
    const n = img.name;
    const orig = (img.original || n).replace(/</g, "&lt;");
    return `
      <div class="frame-card" data-frame-card="${n}" data-img-name="${n}">
        <strong>Ảnh ${label} — ${orig}</strong>
        <label class="field">
          <span>Cách fit</span>
          <select data-frame-ctrl="${n}" data-key="mode">
            <option value="cover"${fr.mode !== "contain" ? " selected" : ""}>Cover — lấp đầy (có cắt)</option>
            <option value="contain"${fr.mode === "contain" ? " selected" : ""}>Contain — hiện đủ ảnh</option>
          </select>
        </label>
        <label class="field">
          <span>Zoom <em class="frame-val" data-frame-val="${n}-zoom">${fr.zoom.toFixed(2)}</em></span>
          <input type="range" min="1" max="2.5" step="0.05" value="${fr.zoom}" data-frame-ctrl="${n}" data-key="zoom" />
        </label>
        <label class="field">
          <span>Focus ngang <em class="frame-val" data-frame-val="${n}-x">${fr.x.toFixed(2)}</em></span>
          <input type="range" min="0" max="1" step="0.01" value="${fr.x}" data-frame-ctrl="${n}" data-key="x" />
        </label>
        <label class="field">
          <span>Focus dọc <em class="frame-val" data-frame-val="${n}-y">${fr.y.toFixed(2)}</em></span>
          <input type="range" min="0" max="1" step="0.01" value="${fr.y}" data-frame-ctrl="${n}" data-key="y" />
        </label>
      </div>`;
  }

  function previewPanelHtml(img, label) {
    if (!img) return "";
    return `
      <div class="frame-preview-panel">
        <div class="frame-preview-viewport" data-frame="${img.name}">
          <img class="frame-preview-img" data-frame="${img.name}"
               src="/projects/${projectId}/images/${img.name}" alt="Preview ${label}" />
        </div>
        <span class="frame-preview-label">Ảnh ${label}</span>
      </div>`;
  }

  function renderScriptFrameBlock(si) {
    const panel = scriptPanelsEl && scriptPanelsEl.querySelector(`.script-panel[data-panel="${si}"]`);
    if (!panel) return;
    let block = panel.querySelector(`.script-frame-block[data-frame-seg="${si}"]`);
    if (!block) {
      block = document.createElement("div");
      block.className = "script-frame-block";
      block.dataset.frameSeg = String(si);
      panel.appendChild(block);
    }
    // Persist current controls before rebuild
    panel.querySelectorAll("[data-frame-ctrl][data-key='mode']").forEach((el) => {
      const name = el.getAttribute("data-frame-ctrl");
      if (name) savedFrames[name] = readFrameFor(name);
    });
    const { left, right } = resolvePair(si);
    if (!left && !right) {
      block.innerHTML = `
        <div class="panel-head">
          <h4>Khung hình kịch bản ${si + 1}</h4>
          <span class="hint">Demo live — zoom / focus ảnh trái &amp; phải của tab này</span>
        </div>
        <p class="empty-sm">Chưa có ảnh cho kịch bản này — upload ảnh hoặc chọn ở trên.</p>`;
      return;
    }
    block.innerHTML = `
      <div class="panel-head">
        <h4>Khung hình kịch bản ${si + 1}</h4>
        <span class="hint">Demo live — zoom / focus ảnh trái &amp; phải của tab này</span>
      </div>
      <div class="frame-preview-stage" data-frame-stage="${si}">
        ${previewPanelHtml(left, "trái")}
        ${previewPanelHtml(right, "phải")}
      </div>
      <div class="frame-grid" data-frame-grid="${si}">
        ${frameCardHtml(left, "trái")}
        ${frameCardHtml(right, "phải")}
      </div>`;
    block.querySelectorAll("[data-frame-ctrl]").forEach((el) => {
      const evt = el.tagName === "SELECT" ? "change" : "input";
      el.addEventListener(evt, () => {
        const side = el.getAttribute("data-frame-ctrl");
        applyFramePreview(side);
        const fr = readFrameFor(side);
        savedFrames[side] = fr;
        scheduleAutosave();
      });
    });
    block.querySelectorAll(".frame-preview-img").forEach((img) => {
      const run = () => applyFramePreview(img.getAttribute("data-frame"));
      if (img.complete && img.naturalWidth) run();
      else img.addEventListener("load", run);
    });
  }

  function ensureScriptPanels(count) {
    if (!scriptPanelsEl) return;
    const existing = [...scriptPanelsEl.querySelectorAll(".script-panel")];
    while (existing.length > count) {
      existing.pop().remove();
    }
    for (let i = 0; i < count; i++) {
      let panel = scriptPanelsEl.querySelector(`.script-panel[data-panel="${i}"]`);
      if (!panel) {
        panel = document.createElement("div");
        panel.className = "script-panel";
        panel.dataset.panel = String(i);
        panel.hidden = true;
        panel.innerHTML = `
          <label class="field">
            <span>Nội dung kịch bản ${i + 1}</span>
            <textarea class="script-tab-text" data-seg="${i}" rows="8" placeholder="1. Câu ảnh trái…\n\n2. Câu ảnh phải…"></textarea>
          </label>
          <div class="row wrap">
            <label class="field grow">
              <span>Ảnh trái (mặc định ảnh ${2 * (i + 1) - 1})</span>
              <select class="seg-left" data-seg="${i}">${imageOptionsHtml("")}</select>
            </label>
            <label class="field grow">
              <span>Ảnh phải (mặc định ảnh ${2 * (i + 1)})</span>
              <select class="seg-right" data-seg="${i}">${imageOptionsHtml("")}</select>
            </label>
          </div>
          <div class="row wrap">
            <label class="field grow">
              <span>Ghi chú trái</span>
              <input type="text" class="seg-cap1" data-seg="${i}" maxlength="60" placeholder="Tuỳ chọn" />
            </label>
            <label class="field grow">
              <span>Ghi chú phải</span>
              <input type="text" class="seg-cap2" data-seg="${i}" maxlength="60" placeholder="Tuỳ chọn" />
            </label>
          </div>
          <div class="script-frame-block" data-frame-seg="${i}"></div>`;
        scriptPanelsEl.appendChild(panel);
        bindScriptPanelEvents(panel);
      }
      renderScriptFrameBlock(i);
    }
    renderScriptTabs(count);
    showScriptTab(Math.min(activeScriptTab, count - 1));
    syncScriptCombined();
    syncSceneSetup();
  }

  function renderScriptTabs(count) {
    if (!scriptTabsEl) return;
    scriptTabsEl.innerHTML = "";
    for (let i = 0; i < count; i++) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "script-tab" + (i === activeScriptTab ? " active" : "");
      btn.textContent = `Kịch bản ${i + 1}`;
      btn.dataset.tab = String(i);
      btn.addEventListener("click", () => showScriptTab(i));
      scriptTabsEl.appendChild(btn);
    }
  }

  function showScriptTab(index) {
    activeScriptTab = index;
    if (!scriptPanelsEl || !scriptTabsEl) return;
    scriptPanelsEl.querySelectorAll(".script-panel").forEach((panel) => {
      const i = Number(panel.dataset.panel);
      const on = i === index;
      panel.hidden = !on;
      panel.classList.toggle("active", on);
    });
    scriptTabsEl.querySelectorAll(".script-tab").forEach((btn) => {
      btn.classList.toggle("active", Number(btn.dataset.tab) === index);
    });
    renderScriptFrameBlock(index);
    setTimeout(() => {
      const panel = scriptPanelsEl.querySelector(`.script-panel[data-panel="${index}"]`);
      if (!panel) return;
      panel.querySelectorAll(".frame-preview-img").forEach((img) => {
        applyFramePreview(img.getAttribute("data-frame"));
      });
    }, 30);
  }

  function syncScriptCombined() {
    if (!scriptCombined || !scriptPanelsEl) return;
    const count = Number(scriptCountEl && scriptCountEl.value) || 1;
    const parts = [];
    for (let i = 0; i < count; i++) {
      const el = scriptPanelsEl.querySelector(`.script-tab-text[data-seg="${i}"]`);
      const text = ((el && el.value) || "").trim();
      // Skip empty tabs so we don't create junk "#" segments
      if (text) parts.push(text);
    }
    scriptCombined.value = parts.join("\n#\n");
  }

  function syncSceneSetup() {
    const hidden = document.getElementById("scene_setup_json");
    if (!hidden || !scriptPanelsEl) return;
    const count = Number(scriptCountEl && scriptCountEl.value) || 1;
    const setup = [];
    for (let i = 0; i < count; i++) {
      const left = scriptPanelsEl.querySelector(`.seg-left[data-seg="${i}"]`);
      const right = scriptPanelsEl.querySelector(`.seg-right[data-seg="${i}"]`);
      const cap1 = scriptPanelsEl.querySelector(`.seg-cap1[data-seg="${i}"]`);
      const cap2 = scriptPanelsEl.querySelector(`.seg-cap2[data-seg="${i}"]`);
      setup.push({
        left: (left && left.value) || null,
        right: (right && right.value) || null,
        caption_1: (cap1 && cap1.value.trim()) || "",
        caption_2: (cap2 && cap2.value.trim()) || "",
      });
    }
    hidden.value = JSON.stringify(setup);
  }

  function bindScriptPanelEvents(root) {
    root.querySelectorAll(".script-tab-text, .seg-left, .seg-right, .seg-cap1, .seg-cap2").forEach((el) => {
      el.addEventListener("input", () => {
        syncScriptCombined();
        syncSceneSetup();
        scheduleAutosave();
      });
      el.addEventListener("change", () => {
        syncScriptCombined();
        syncSceneSetup();
        if (el.classList.contains("seg-left") || el.classList.contains("seg-right")) {
          const si = Number(el.getAttribute("data-seg"));
          renderScriptFrameBlock(si);
        }
        scheduleAutosave();
      });
    });
  }

  function collectAutosavePayload() {
    syncScriptCombined();
    syncSceneSetup();
    syncImageFrames();
    const form = document.getElementById("save-form");
    if (!form) return null;
    const fd = new FormData(form);
    const karaoke = form.querySelector('[name="karaoke"]');
    const clean = form.querySelector('[name="clean_export"]');
    const autoPose = form.querySelector('[name="auto_pose"]');
    let imageFrames = {};
    let sceneSetup = [];
    try { imageFrames = JSON.parse(fd.get("image_frames_json") || "{}"); } catch (_) {}
    try { sceneSetup = JSON.parse(fd.get("scene_setup_json") || "[]"); } catch (_) {}
    return {
      title: fd.get("title") || "",
      script: fd.get("script") || "",
      voice: fd.get("voice"),
      character_id: fd.get("character_id"),
      character_position: fd.get("character_position"),
      brand_name: fd.get("brand_name") || "",
      caption_1: (sceneSetup[0] && sceneSetup[0].caption_1) || "",
      caption_2: (sceneSetup[0] && sceneSetup[0].caption_2) || "",
      frame_1_mode: fd.get("frame_1_mode"),
      frame_1_zoom: fd.get("frame_1_zoom"),
      frame_1_x: fd.get("frame_1_x"),
      frame_1_y: fd.get("frame_1_y"),
      frame_2_mode: fd.get("frame_2_mode"),
      frame_2_zoom: fd.get("frame_2_zoom"),
      frame_2_x: fd.get("frame_2_x"),
      frame_2_y: fd.get("frame_2_y"),
      speed: fd.get("speed"),
      render_fps: fd.get("render_fps"),
      karaoke: !!(karaoke && karaoke.checked),
      clean_export: !!(clean && clean.checked),
      auto_pose: !!(autoPose && autoPose.checked),
      scene_setup: sceneSetup,
      image_frames: imageFrames,
      script_count: Number(fd.get("script_count") || 1),
    };
  }

  async function runAutosave() {
    if (autosaving) return;
    const payload = collectAutosavePayload();
    if (!payload) return;
    autosaving = true;
    if (autosaveStatus) autosaveStatus.textContent = "Đang lưu…";
    try {
      const res = await fetch(`/api/projects/${projectId}/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Lỗi lưu");
      if (autosaveStatus) {
        const t = new Date();
        const hh = String(t.getHours()).padStart(2, "0");
        const mm = String(t.getMinutes()).padStart(2, "0");
        const ss = String(t.getSeconds()).padStart(2, "0");
        autosaveStatus.textContent = `Đã lưu ${hh}:${mm}:${ss}`;
      }
      if (Array.isArray(data.scenes)) {
        renderScenesList(data.scenes);
      }
    } catch (_) {
      if (autosaveStatus) autosaveStatus.textContent = "Lỗi lưu — thử lại";
    } finally {
      autosaving = false;
    }
  }

  function renderScenesList(scenes) {
    const box = document.getElementById("scenes-box");
    if (!box) return;
    if (!scenes.length) {
      box.innerHTML = `<p class="empty-sm" id="scenes-empty">Chưa tách được cảnh — kiểm tra nội dung tab kịch bản.</p>`;
      return;
    }
    const targetLabel = (t) =>
      t === "point_1" ? "→ trái" : t === "point_2" ? "→ phải" : "→ giữa";
    const items = scenes
      .map(
        (s) => `<li>
          <span>${s.index}</span>
          <div>
            <small class="hint" style="margin:0">
              KB ${s.segment || 1}
              · ${targetLabel(s.target)}
              · không đọc số
            </small>
            <div>${String(s.text || "").replace(/</g, "&lt;")}</div>
          </div>
        </li>`
      )
      .join("");
    box.innerHTML = `<ol class="scenes" id="scenes-list">${items}</ol>`;
  }

  function scheduleAutosave() {
    clearTimeout(autosaveTimer);
    if (autosaveStatus) autosaveStatus.textContent = "Chưa lưu…";
    autosaveTimer = setTimeout(runAutosave, 700);
  }

  if (scriptCountEl) {
    scriptCountEl.addEventListener("change", () => {
      ensureScriptPanels(Number(scriptCountEl.value) || 1);
      scheduleAutosave();
    });
  }
  if (scriptPanelsEl) {
    scriptPanelsEl.querySelectorAll(".script-panel").forEach(bindScriptPanelEvents);
    ensureScriptPanels(Number(scriptCountEl && scriptCountEl.value) || window.AIVIDEO_SCRIPT_COUNT || 1);
  }

  const saveForm = document.getElementById("save-form");
  if (saveForm) {
    saveForm.addEventListener("submit", (e) => {
      e.preventDefault();
      runAutosave();
    });
    saveForm.addEventListener("input", scheduleAutosave);
    saveForm.addEventListener("change", scheduleAutosave);
  }

  syncSceneSetup();
  syncImageFrames();
  setTimeout(runAutosave, 400);

    if (renderForm) {
    renderForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (["queued", "rendering", "paused"].includes(status)) return;
      status = "queued";
      if (statusText) statusText.textContent = "queued";
      updateProgress(1, "Đang xếp hàng…");
      updateRenderControls();
      poll();
      try {
        const res = await fetch(`/api/projects/${projectId}/render`, { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || "Không bắt đầu được render");
        status = data.status || "queued";
        if (statusText) statusText.textContent = status;
        updateProgress(data.progress || 1, data.progress_message || "Đang xếp hàng…");
        updateRenderControls();
        poll();
      } catch (err) {
        status = "error";
        if (statusText) statusText.textContent = "error";
        updateProgress(0, err.message || "Lỗi render");
        updateRenderControls();
        alert(err.message || "Lỗi render");
      }
    });
  }

  // Live demo for every image frame (matches renderer _fit_framed)
  function applyFramePreview(side) {
    const viewport = document.querySelector(`.frame-preview-viewport[data-frame="${side}"]`);
    const img = document.querySelector(`.frame-preview-img[data-frame="${side}"]`);
    if (!viewport || !img) return;
    const srcW = img.naturalWidth;
    const srcH = img.naturalHeight;
    if (!srcW || !srcH) return;

    const boxW = viewport.clientWidth;
    const boxH = viewport.clientHeight;
    if (!boxW || !boxH) return;

    const modeEl = document.querySelector(`[data-frame-ctrl="${side}"][data-key="mode"]`);
    const zoomEl = document.querySelector(`[data-frame-ctrl="${side}"][data-key="zoom"]`);
    const xEl = document.querySelector(`[data-frame-ctrl="${side}"][data-key="x"]`);
    const yEl = document.querySelector(`[data-frame-ctrl="${side}"][data-key="y"]`);
    const mode = ((modeEl && modeEl.value) || "cover").toLowerCase();
    const zoom = clamp(Number(zoomEl && zoomEl.value) || 1, 1, 3);
    const fx = clamp(Number(xEl && xEl.value), 0, 1);
    const fy = clamp(Number(yEl && yEl.value), 0, 1);

    const setVal = (key, val) => {
      const el = document.querySelector(`[data-frame-val="${side}-${key}"]`);
      if (el) el.textContent = Number(val).toFixed(2);
    };
    setVal("zoom", zoom);
    setVal("x", fx);
    setVal("y", fy);

    let scale;
    if (mode === "contain") {
      scale = Math.min(boxW / srcW, boxH / srcH) * zoom;
    } else {
      scale = Math.max(boxW / srcW, boxH / srcH) * zoom;
    }
    const newW = Math.max(1, srcW * scale);
    const newH = Math.max(1, srcH * scale);

    let left;
    let top;
    if (mode === "contain") {
      left = newW <= boxW ? (boxW - newW) / 2 : -(newW - boxW) * fx;
      top = newH <= boxH ? (boxH - newH) / 2 : -(newH - boxH) * fy;
      viewport.style.background = "#ebebee";
    } else {
      left = -Math.max(0, newW - boxW) * fx;
      top = -Math.max(0, newH - boxH) * fy;
      viewport.style.background = "#111";
    }

    img.style.width = `${newW}px`;
    img.style.height = `${newH}px`;
    img.style.left = `${left}px`;
    img.style.top = `${top}px`;
    syncImageFrames();
    if (typeof scheduleAutosave === "function") scheduleAutosave();
  }

  function refreshFramePreviews() {
    document.querySelectorAll(".frame-preview-img").forEach((img) => {
      applyFramePreview(img.getAttribute("data-frame"));
    });
  }

  document.querySelectorAll("[data-frame-ctrl]").forEach((el) => {
    const evt = el.tagName === "SELECT" ? "change" : "input";
    el.addEventListener(evt, () => {
      const side = el.getAttribute("data-frame-ctrl");
      applyFramePreview(side);
    });
  });

  document.querySelectorAll(".frame-preview-img").forEach((img) => {
    const run = () => applyFramePreview(img.getAttribute("data-frame"));
    if (img.complete && img.naturalWidth) run();
    else img.addEventListener("load", run);
  });

  window.addEventListener("resize", () => {
    clearTimeout(window.__framePreviewResize);
    window.__framePreviewResize = setTimeout(refreshFramePreviews, 80);
  });

  refreshFramePreviews();

  buildRuler();
  renderClips();
  updateRenderControls();
  if (["queued", "rendering", "paused"].includes(status)) {
    updateProgress(1, "Đang render…");
    poll();
  }
})();
