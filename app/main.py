from __future__ import annotations

import asyncio
import json
import traceback
from pathlib import Path

from fastapi import BackgroundTasks, Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import CHARACTER_POSITIONS, STATIC_DIR, TEMPLATES_DIR, VOICES, ensure_dirs
from app.services import characters as character_store
from app.services import projects as project_store
from app.services import sfx as sfx_store
from app.services.renderer import RenderCancelled, apply_sfx_export, render_project
from app.services.script_parser import list_script_segments, parse_script

ensure_dirs()
character_store.ensure_builtin_characters()
sfx_store.ensure_sfx_library()

app = FastAPI(title="AIvideo", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
RENDER_PAUSE_EVENTS: dict[str, asyncio.Event] = {}
RENDER_CANCEL_EVENTS: dict[str, asyncio.Event] = {}
RENDER_PROGRESS: dict[str, dict] = {}


def _set_render_progress(
    project_id: str,
    percent: float,
    message: str = "",
    *,
    persist: bool = True,
) -> None:
    pct = max(0, min(100, int(round(percent))))
    payload = {"percent": pct, "message": message or ""}
    RENDER_PROGRESS[project_id] = payload
    if not persist:
        return
    try:
        folder = project_store.project_dir(project_id)
        out = folder / "output"
        out.mkdir(parents=True, exist_ok=True)
        (out / "progress.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


def _queue_render(project_id: str, background_tasks: BackgroundTasks) -> dict:
    """Shared start-render logic for form + API."""
    project = project_store.load_project(project_id)
    if not (project.get("script") or "").strip():
        project["status"] = "error"
        project["error"] = (
            "Kịch bản đang trống. Nhập nội dung → bấm Lưu dự án → rồi Render."
        )
        project_store.save_project(project)
        return {"ok": False, "status": "error", "error": project["error"], "progress": 0}

    if project.get("status") in {"queued", "rendering", "paused"}:
        progress = _get_render_progress(project_id)
        return {
            "ok": True,
            "status": project.get("status"),
            "progress": progress.get("percent", 0),
            "progress_message": progress.get("message", ""),
            "already_running": True,
        }

    pause_event = asyncio.Event()
    pause_event.set()
    RENDER_PAUSE_EVENTS[project_id] = pause_event
    cancel_event = asyncio.Event()
    RENDER_CANCEL_EVENTS[project_id] = cancel_event
    background_tasks.add_task(_run_render, project_id)
    project["status"] = "queued"
    project["error"] = None
    project_store.save_project(project)
    _set_render_progress(project_id, 1, "Đang xếp hàng…")
    return {
        "ok": True,
        "status": "queued",
        "progress": 1,
        "progress_message": "Đang xếp hàng…",
        "already_running": False,
    }


def _get_render_progress(project_id: str) -> dict:
    live = RENDER_PROGRESS.get(project_id)
    if live:
        return live
    path = project_store.project_dir(project_id) / "output" / "progress.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {
                "percent": int(data.get("percent", 0)),
                "message": str(data.get("message") or ""),
            }
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    return {"percent": 0, "message": ""}


def _render(request: Request, name: str, **ctx):
    return templates.TemplateResponse(request=request, name=name, context=ctx)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return _render(
        request,
        "index.html",
        projects=project_store.list_projects(),
        voices=VOICES,
    )


@app.post("/projects")
async def create_project(title: str = Form("Dự án mới")):
    project = project_store.create_project(title)
    return RedirectResponse(url=f"/projects/{project['id']}", status_code=303)


@app.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_page(request: Request, project_id: str):
    try:
        project = project_store.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    scenes = parse_script(project.get("script", ""))
    segments = list_script_segments(project.get("script", ""))
    # Prefer explicit count, else derived from # splits
    count = max(int(project.get("script_count") or 1), len(segments) or 1, 1)
    count = min(6, count)
    project["script_count"] = count
    while len(segments) < count:
        segments.append({"index": len(segments) + 1, "raw": "", "scenes": []})
    duration = project.get("duration_sec") or sfx_store.estimate_script_duration(
        project.get("script", "")
    )
    return _render(
        request,
        "project.html",
        project=project,
        scenes=scenes,
        segments=segments[:count],
        voices=VOICES,
        characters=character_store.list_characters(),
        positions=CHARACTER_POSITIONS,
        sfx_list=sfx_store.list_sfx(),
        timeline_duration=duration,
    )


def _frame_from_values(mode: str, zoom, x, y) -> dict:
    try:
        z = float(zoom)
    except (TypeError, ValueError):
        z = 1.0
    try:
        fx = float(x)
    except (TypeError, ValueError):
        fx = 0.5
    try:
        fy = float(y)
    except (TypeError, ValueError):
        fy = 0.5
    return {
        "mode": "contain" if str(mode) == "contain" else "cover",
        "zoom": max(1.0, min(3.0, z)),
        "x": max(0.0, min(1.0, fx)),
        "y": max(0.0, min(1.0, fy)),
    }


def _apply_project_payload(project: dict, data: dict) -> dict:
    """Shared save logic for form POST and JSON autosave."""
    if "title" in data and data["title"] is not None:
        project["title"] = str(data["title"]).strip() or project["title"]
    if "script" in data and data["script"] is not None:
        project["script"] = str(data["script"])
    if "voice" in data and data["voice"]:
        project["voice"] = str(data["voice"])
    if "character_id" in data and data["character_id"]:
        project["character_id"] = str(data["character_id"])
    if "character_position" in data and data["character_position"]:
        project["character_position"] = str(data["character_position"])
    if "brand_name" in data and data["brand_name"] is not None:
        project["brand_name"] = str(data["brand_name"]).strip()[:40]
    if "caption_1" in data and data["caption_1"] is not None:
        project["caption_1"] = str(data["caption_1"]).strip()[:60]
    if "caption_2" in data and data["caption_2"] is not None:
        project["caption_2"] = str(data["caption_2"]).strip()[:60]
    if "script_count" in data and data["script_count"] is not None:
        try:
            project["script_count"] = max(1, min(6, int(data["script_count"])))
        except (TypeError, ValueError):
            pass

    if all(k in data for k in ("frame_1_mode", "frame_1_zoom", "frame_1_x", "frame_1_y")):
        project["frame_1"] = _frame_from_values(
            data["frame_1_mode"], data["frame_1_zoom"], data["frame_1_x"], data["frame_1_y"]
        )
    if all(k in data for k in ("frame_2_mode", "frame_2_zoom", "frame_2_x", "frame_2_y")):
        project["frame_2"] = _frame_from_values(
            data["frame_2_mode"], data["frame_2_zoom"], data["frame_2_x"], data["frame_2_y"]
        )

    raw_frames = data.get("image_frames")
    if raw_frames is None and data.get("image_frames_json"):
        try:
            raw_frames = json.loads(data["image_frames_json"])
        except (TypeError, json.JSONDecodeError):
            raw_frames = None
    if isinstance(raw_frames, dict):
        cleaned = {}
        for name, fr in raw_frames.items():
            if not name or not isinstance(fr, dict):
                continue
            cleaned[str(name)] = _frame_from_values(
                fr.get("mode", "cover"), fr.get("zoom", 1), fr.get("x", 0.5), fr.get("y", 0.5)
            )
        project["image_frames"] = cleaned
        imgs = project.get("images") or []
        if len(imgs) >= 1 and imgs[0].get("name") in cleaned:
            project["frame_1"] = cleaned[imgs[0]["name"]]
        if len(imgs) >= 2 and imgs[1].get("name") in cleaned:
            project["frame_2"] = cleaned[imgs[1]["name"]]

    if "speed" in data and data["speed"] is not None:
        try:
            from app.services.tts import normalize_speed

            project["speed"] = normalize_speed(data["speed"])
        except Exception:  # noqa: BLE001
            project["speed"] = 1.0
    if "render_fps" in data and data["render_fps"] is not None:
        try:
            fps = int(float(data["render_fps"]))
        except (TypeError, ValueError):
            fps = 24
        project["render_fps"] = fps if fps in {20, 24, 30} else 24

    if "karaoke" in data:
        project["karaoke"] = bool(data["karaoke"])
    if "clean_export" in data:
        project["clean_export"] = bool(data["clean_export"])
    if "auto_pose" in data:
        project["auto_pose"] = bool(data["auto_pose"])

    raw_setup = data.get("scene_setup")
    if raw_setup is None and data.get("scene_setup_json"):
        try:
            raw_setup = json.loads(data["scene_setup_json"])
        except (TypeError, json.JSONDecodeError):
            raw_setup = None
    if isinstance(raw_setup, list):
        project["scene_setup"] = raw_setup

    project["duration_sec"] = round(
        sfx_store.estimate_script_duration(project.get("script") or ""), 2
    )
    return project_store.save_project(project)


@app.post("/projects/{project_id}/save")
async def save_project(
    project_id: str,
    title: str = Form(...),
    script: str = Form(""),
    voice: str = Form(...),
    character_id: str = Form("tuti"),
    character_position: str = Form("center"),
    brand_name: str = Form(""),
    caption_1: str = Form(""),
    caption_2: str = Form(""),
    frame_1_mode: str = Form("cover"),
    frame_1_zoom: str = Form("1"),
    frame_1_x: str = Form("0.5"),
    frame_1_y: str = Form("0.5"),
    frame_2_mode: str = Form("cover"),
    frame_2_zoom: str = Form("1"),
    frame_2_x: str = Form("0.5"),
    frame_2_y: str = Form("0.5"),
    speed: str = Form("1"),
    render_fps: str = Form("24"),
    karaoke: str | None = Form(None),
    clean_export: str | None = Form(None),
    auto_pose: str | None = Form(None),
    scene_setup_json: str = Form("[]"),
    image_frames_json: str = Form("{}"),
    script_count: str = Form("1"),
):
    try:
        project = project_store.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    _apply_project_payload(
        project,
        {
            "title": title,
            "script": script,
            "voice": voice,
            "character_id": character_id,
            "character_position": character_position,
            "brand_name": brand_name,
            "caption_1": caption_1,
            "caption_2": caption_2,
            "frame_1_mode": frame_1_mode,
            "frame_1_zoom": frame_1_zoom,
            "frame_1_x": frame_1_x,
            "frame_1_y": frame_1_y,
            "frame_2_mode": frame_2_mode,
            "frame_2_zoom": frame_2_zoom,
            "frame_2_x": frame_2_x,
            "frame_2_y": frame_2_y,
            "speed": speed,
            "render_fps": render_fps,
            "karaoke": karaoke is not None,
            "clean_export": clean_export is not None,
            "auto_pose": auto_pose is not None,
            "scene_setup_json": scene_setup_json,
            "image_frames_json": image_frames_json,
            "script_count": script_count,
        },
    )
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@app.post("/api/projects/{project_id}/save")
async def api_save_project(project_id: str, payload: dict = Body(...)):
    try:
        project = project_store.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    saved = _apply_project_payload(project, payload)
    scenes = parse_script(saved.get("script") or "")
    return JSONResponse(
        {
            "ok": True,
            "updated_at": saved.get("updated_at"),
            "script_count": saved.get("script_count"),
            "duration_sec": saved.get("duration_sec"),
            "scenes": [
                {
                    "index": s.index,
                    "text": s.text,
                    "target": s.target,
                    "segment": s.segment,
                }
                for s in scenes
            ],
        }
    )


@app.post("/projects/{project_id}/images")
async def upload_images(project_id: str, files: list[UploadFile] = File(...)):
    try:
        project_store.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    for f in files:
        data = await f.read()
        if not data:
            continue
        try:
            project_store.add_image(project_id, f.filename or "image.jpg", data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@app.post("/projects/{project_id}/images/{name}/delete")
async def delete_image(project_id: str, name: str):
    try:
        project_store.remove_image(project_id, name)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@app.post("/characters/upload")
async def upload_character(
    file: UploadFile = File(...),
    label: str = Form(""),
    project_id: str = Form(""),
    as_sheet: str | None = Form(None),
    bg_removed: str | None = Form(None),
):
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    skip_rembg = bg_removed is not None
    try:
        # Sprite sheet (5 poses ngang) → animated pack
        if as_sheet is not None or (file.filename or "").lower().find("sheet") >= 0:
            from app.services.sprite_import import import_sprite_sheet

            entry = import_sprite_sheet(data, label or None, skip_rembg=skip_rembg)
            if project_id:
                project = project_store.load_project(project_id)
                project["character_id"] = entry["id"]
                project_store.save_project(project)
        else:
            # Single PNG character (static) OR treat wide images as sheets
            from PIL import Image
            from io import BytesIO

            im = Image.open(BytesIO(data))
            if im.width >= im.height * 2.2:
                from app.services.sprite_import import import_sprite_sheet

                entry = import_sprite_sheet(data, label or None, skip_rembg=skip_rembg)
                if project_id:
                    project = project_store.load_project(project_id)
                    project["character_id"] = entry["id"]
                    project_store.save_project(project)
            else:
                character_store.add_custom_character(file.filename or "char.png", data, label or None)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    if project_id:
        return RedirectResponse(url=f"/projects/{project_id}", status_code=303)
    return RedirectResponse(url="/", status_code=303)


@app.post("/characters/{character_id}/delete")
async def delete_character(character_id: str, project_id: str = Form("")):
    try:
        character_store.delete_custom_character(character_id)
    except FileNotFoundError:
        raise HTTPException(404, "Character not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if project_id:
        try:
            project = project_store.load_project(project_id)
            if project.get("character_id") == Path(character_id).name:
                project["character_id"] = "tuti"
                project_store.save_project(project)
        except FileNotFoundError:
            pass
    if project_id:
        return RedirectResponse(url=f"/projects/{project_id}", status_code=303)
    return RedirectResponse(url="/", status_code=303)


@app.post("/api/projects/{project_id}/sfx")
async def save_sfx(project_id: str, payload: dict = Body(...)):
    try:
        project_store.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    clips = payload.get("clips") or []
    if not isinstance(clips, list):
        raise HTTPException(400, "clips must be a list")
    project = project_store.update_sfx_clips(project_id, clips)
    return JSONResponse({"ok": True, "clips": project["sfx_clips"]})


@app.post("/api/projects/{project_id}/export-sfx")
async def export_with_sfx(project_id: str, payload: dict = Body(default=None)):
    """Apply SFX timeline onto already-rendered base video and refresh downloadable MP4."""
    try:
        project = project_store.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    if payload and isinstance(payload.get("clips"), list):
        project = project_store.update_sfx_clips(project_id, payload["clips"])
    try:
        out = apply_sfx_export(project, project_store.project_dir(project_id))
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Xuất SFX thất bại: {exc}") from exc
    project = project_store.load_project(project_id)
    project["output_file"] = out.name
    project["status"] = "ready"
    project_store.save_project(project)
    return JSONResponse(
        {
            "ok": True,
            "output_file": out.name,
            "url": f"/projects/{project_id}/video?t={project['updated_at']}",
            "clips": project.get("sfx_clips") or [],
        }
    )


@app.post("/projects/{project_id}/delete")
async def delete_project(project_id: str):
    project_store.delete_project(project_id)
    return RedirectResponse(url="/", status_code=303)


async def _run_render(project_id: str) -> None:
    project = project_store.load_project(project_id)
    project["status"] = "rendering"
    project["error"] = None
    project_store.save_project(project)
    _set_render_progress(project_id, 1, "Đang chuẩn bị render…")
    pause_event = RENDER_PAUSE_EVENTS.get(project_id)
    if pause_event is None:
        pause_event = asyncio.Event()
        pause_event.set()
        RENDER_PAUSE_EVENTS[project_id] = pause_event
    cancel_event = RENDER_CANCEL_EVENTS.get(project_id)
    if cancel_event is None:
        cancel_event = asyncio.Event()
        RENDER_CANCEL_EVENTS[project_id] = cancel_event

    last_saved = {"pct": -1, "t": 0.0}

    def on_progress(percent: float, message: str = "") -> None:
        import time

        now = time.monotonic()
        pct = max(0, min(100, int(round(percent))))
        # Always update memory; persist often so UI never stalls at 0%
        should_persist = (
            pct != last_saved["pct"]
            or now - last_saved["t"] >= 0.4
            or pct >= 100
            or pct <= 2
        )
        _set_render_progress(project_id, pct, message, persist=should_persist)
        if should_persist:
            last_saved["pct"] = pct
            last_saved["t"] = now

    try:
        folder = project_store.project_dir(project_id)
        out = await render_project(
            project,
            folder,
            pause_event=pause_event,
            cancel_event=cancel_event,
            progress_cb=on_progress,
        )
        project = project_store.load_project(project_id)
        # duration was computed inside render; re-read manifest if needed
        manifest_path = folder / "output" / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            project["duration_sec"] = manifest.get("duration_sec", project.get("duration_sec"))
        project["status"] = "ready"
        project["output_file"] = out.name
        project["base_file"] = "video_base.mp4"
        project["error"] = None
        project_store.save_project(project)
        _set_render_progress(project_id, 100, "Hoàn tất")
    except RenderCancelled:
        project = project_store.load_project(project_id)
        project["status"] = "draft"
        project["error"] = None
        project_store.save_project(project)
        _set_render_progress(project_id, 0, "Đã hủy render")
    except Exception as exc:  # noqa: BLE001
        project = project_store.load_project(project_id)
        project["status"] = "error"
        project["error"] = f"{exc}\n{traceback.format_exc()[-800:]}"
        project_store.save_project(project)
        _set_render_progress(project_id, 0, "Lỗi render")
    finally:
        RENDER_PAUSE_EVENTS.pop(project_id, None)
        RENDER_CANCEL_EVENTS.pop(project_id, None)


@app.post("/projects/{project_id}/render")
async def start_render(project_id: str, background_tasks: BackgroundTasks):
    try:
        project_store.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    _queue_render(project_id, background_tasks)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@app.post("/api/projects/{project_id}/render")
async def api_start_render(project_id: str, background_tasks: BackgroundTasks):
    try:
        project_store.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    result = _queue_render(project_id, background_tasks)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Không thể render")
    return JSONResponse(result)


@app.post("/api/projects/{project_id}/pause")
async def pause_render(project_id: str):
    try:
        project = project_store.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    if project.get("status") not in {"queued", "rendering"}:
        return JSONResponse({"ok": False, "status": project.get("status"), "detail": "Render is not running"})
    pause_event = RENDER_PAUSE_EVENTS.get(project_id)
    if pause_event is None:
        pause_event = asyncio.Event()
        RENDER_PAUSE_EVENTS[project_id] = pause_event
    pause_event.clear()
    project["status"] = "paused"
    project_store.save_project(project)
    return JSONResponse({"ok": True, "status": "paused"})


@app.post("/api/projects/{project_id}/resume")
async def resume_render(project_id: str):
    try:
        project = project_store.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    if project.get("status") != "paused":
        return JSONResponse({"ok": False, "status": project.get("status"), "detail": "Render is not paused"})
    pause_event = RENDER_PAUSE_EVENTS.get(project_id)
    if pause_event is None:
        return JSONResponse({"ok": False, "status": project.get("status"), "detail": "No paused render task found"})
    pause_event.set()
    project["status"] = "rendering"
    project_store.save_project(project)
    return JSONResponse({"ok": True, "status": "rendering"})


@app.post("/api/projects/{project_id}/cancel")
async def cancel_render(project_id: str):
    try:
        project = project_store.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    if project.get("status") not in {"queued", "rendering", "paused"}:
        return JSONResponse(
            {"ok": False, "status": project.get("status"), "detail": "Không có render đang chạy"}
        )
    cancel_event = RENDER_CANCEL_EVENTS.get(project_id)
    if cancel_event is None:
        cancel_event = asyncio.Event()
        RENDER_CANCEL_EVENTS[project_id] = cancel_event
    cancel_event.set()
    # Wake pause wait so cancel is noticed immediately
    pause_event = RENDER_PAUSE_EVENTS.get(project_id)
    if pause_event is not None:
        pause_event.set()
    project["status"] = "draft"
    project["error"] = None
    project_store.save_project(project)
    _set_render_progress(project_id, 0, "Đã hủy render")
    return JSONResponse({"ok": True, "status": "draft"})


@app.get("/api/projects/{project_id}/status")
async def project_status(project_id: str):
    try:
        project = project_store.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    progress = _get_render_progress(project_id)
    status = project.get("status")
    if status == "ready":
        progress = {"percent": 100, "message": progress.get("message") or "Hoàn tất"}
    elif status == "draft":
        progress = {"percent": 0, "message": ""}
    elif status == "queued":
        progress = {"percent": progress.get("percent", 0), "message": progress.get("message") or "Đang xếp hàng…"}
    return JSONResponse(
        {
            "status": status,
            "output_file": project.get("output_file"),
            "error": project.get("error"),
            "duration_sec": project.get("duration_sec"),
            "progress": progress.get("percent", 0),
            "progress_message": progress.get("message", ""),
        }
    )


@app.get("/projects/{project_id}/images/{name}")
async def serve_image(project_id: str, name: str):
    path = project_store.project_dir(project_id) / "images" / Path(name).name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/characters/{character_id}")
async def serve_character(character_id: str):
    try:
        path = character_store.character_file(character_id)
    except FileNotFoundError:
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/sfx/{sfx_id}")
async def serve_sfx(sfx_id: str):
    try:
        path = sfx_store.sfx_path(sfx_id)
    except FileNotFoundError:
        raise HTTPException(404)
    return FileResponse(path, media_type="audio/wav")


@app.get("/projects/{project_id}/video")
async def serve_video(project_id: str):
    project = project_store.load_project(project_id)
    name = project.get("output_file") or "video.mp4"
    path = project_store.project_dir(project_id) / "output" / name
    if not path.exists():
        raise HTTPException(404, "Video not ready")
    return FileResponse(path, media_type="video/mp4", filename=f"{project['title']}.mp4")


@app.get("/projects/{project_id}/download")
async def download_video(project_id: str):
    return await serve_video(project_id)
