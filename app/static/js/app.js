(() => {
  const projectId = window.AIVIDEO_PROJECT_ID;
  let status = window.AIVIDEO_STATUS;
  if (!projectId) return;

  const statusText = document.getElementById("status-text");
  const renderBtn = document.getElementById("render-btn");
  const pauseBtn = document.getElementById("pause-btn");
  const videoBox = document.getElementById("video-box");
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

  let duration = Math.max(4, Number(window.AIVIDEO_DURATION) || 12);
  let clips = Array.isArray(window.AIVIDEO_SFX_CLIPS)
    ? window.AIVIDEO_SFX_CLIPS.map((c) => ({ ...c }))
    : [];

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
        if (saveStatus) saveStatus.textContent = `Lỗi ${status === "paused" ? "tiếp tục" : "tạm dừng"}: ${err.message || err}`;
        updateRenderControls();
      }
    });
  }

  buildRuler();
  renderClips();
  updateRenderControls();

  // Render does NOT need SFX — plain submit
  async function poll() {
    if (!["queued", "rendering", "paused"].includes(status)) return;
    try {
      const res = await fetch(`/api/projects/${projectId}/status`);
      const data = await res.json();
      status = data.status;
      if (statusText) statusText.textContent = status;
      updateRenderControls();
      if (status === "ready") {
        const url = `/projects/${projectId}/video?t=${Date.now()}`;
        if (data.duration_sec) {
          duration = Number(data.duration_sec) || duration;
        }
        loadVideoIntoTimeline(url);
        if (videoBox) {
          videoBox.classList.remove("hidden");
          const v = videoBox.querySelector("video");
          if (v) v.src = url;
        }
        if (saveStatus) {
          saveStatus.textContent = "Video đã vào timeline — kéo SFX rồi bấm Xuất video + SFX";
        }
        // Scroll timeline into view
        if (sfxPanel) sfxPanel.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      if (status === "error") {
        location.reload();
        return;
      }
    } catch (_) {}
    setTimeout(poll, 1500);
  }

  if (["queued", "rendering", "paused"].includes(status)) poll();
})();
