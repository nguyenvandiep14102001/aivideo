(() => {
  const projectId = window.AIVIDEO_PROJECT_ID;
  let status = window.AIVIDEO_STATUS;
  if (!projectId) return;

  const statusText = document.getElementById("status-text");
  const renderBtn = document.getElementById("render-btn");
  const pauseBtn = document.getElementById("pause-btn");
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

  // Live demo for image frame 1 & 2 (matches renderer _fit_framed)
  function clamp(n, a, b) {
    return Math.max(a, Math.min(b, n));
  }

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
  }

  function refreshFramePreviews() {
    applyFramePreview(1);
    applyFramePreview(2);
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
