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
from app.services.renderer import apply_sfx_export, render_project
from app.services.script_parser import parse_script

ensure_dirs()
character_store.ensure_builtin_characters()
sfx_store.ensure_sfx_library()

app = FastAPI(title="AIvideo", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
RENDER_PAUSE_EVENTS: dict[str, asyncio.Event] = {}


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
    duration = project.get("duration_sec") or sfx_store.estimate_script_duration(
        project.get("script", "")
    )
    return _render(
        request,
        "project.html",
        project=project,
        scenes=scenes,
        voices=VOICES,
        characters=character_store.list_characters(),
        positions=CHARACTER_POSITIONS,
        sfx_list=sfx_store.list_sfx(),
        timeline_duration=duration,
    )


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
    karaoke: str | None = Form(None),
    clean_export: str | None = Form(None),
    auto_pose: str | None = Form(None),
):
    try:
        project = project_store.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    project["title"] = title.strip() or project["title"]
    project["script"] = script
    project["voice"] = voice
    project["character_id"] = character_id
    project["character_position"] = character_position
    project["brand_name"] = brand_name.strip()[:40]
    project["caption_1"] = caption_1.strip()[:60]
    project["caption_2"] = caption_2.strip()[:60]

    def _frame(mode: str, zoom: str, x: str, y: str) -> dict:
        try:
            z = float(zoom)
        except ValueError:
            z = 1.0
        try:
            fx = float(x)
        except ValueError:
            fx = 0.5
        try:
            fy = float(y)
        except ValueError:
            fy = 0.5
        return {
            "mode": "contain" if mode == "contain" else "cover",
            "zoom": max(1.0, min(3.0, z)),
            "x": max(0.0, min(1.0, fx)),
            "y": max(0.0, min(1.0, fy)),
        }

    project["frame_1"] = _frame(frame_1_mode, frame_1_zoom, frame_1_x, frame_1_y)
    project["frame_2"] = _frame(frame_2_mode, frame_2_zoom, frame_2_x, frame_2_y)
    try:
        from app.services.tts import normalize_speed

        project["speed"] = normalize_speed(speed)
    except Exception:  # noqa: BLE001
        project["speed"] = 1.0
    project["karaoke"] = karaoke is not None
    project["clean_export"] = clean_export is not None
    project["auto_pose"] = auto_pose is not None
    if not project.get("duration_sec"):
        project["duration_sec"] = round(
            sfx_store.estimate_script_duration(script), 2
        )
    project_store.save_project(project)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


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
    pause_event = RENDER_PAUSE_EVENTS.get(project_id)
    if pause_event is None:
        pause_event = asyncio.Event()
        pause_event.set()
        RENDER_PAUSE_EVENTS[project_id] = pause_event
    try:
        folder = project_store.project_dir(project_id)
        out = await render_project(project, folder, pause_event=pause_event)
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
    except Exception as exc:  # noqa: BLE001
        project = project_store.load_project(project_id)
        project["status"] = "error"
        project["error"] = f"{exc}\n{traceback.format_exc()[-800:]}"
        project_store.save_project(project)
    finally:
        RENDER_PAUSE_EVENTS.pop(project_id, None)


@app.post("/projects/{project_id}/render")
async def start_render(project_id: str, background_tasks: BackgroundTasks):
    try:
        project = project_store.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    if not (project.get("script") or "").strip():
        project["status"] = "error"
        project["error"] = (
            "Kịch bản đang trống. Nhập nội dung → bấm Lưu dự án → rồi Render."
        )
        project_store.save_project(project)
        return RedirectResponse(url=f"/projects/{project_id}", status_code=303)
    if project.get("status") in {"queued", "rendering", "paused"}:
        return RedirectResponse(url=f"/projects/{project_id}", status_code=303)
    pause_event = asyncio.Event()
    pause_event.set()
    RENDER_PAUSE_EVENTS[project_id] = pause_event
    background_tasks.add_task(_run_render, project_id)
    project["status"] = "queued"
    project["error"] = None
    project_store.save_project(project)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


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


@app.get("/api/projects/{project_id}/status")
async def project_status(project_id: str):
    try:
        project = project_store.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    return JSONResponse(
        {
            "status": project.get("status"),
            "output_file": project.get("output_file"),
            "error": project.get("error"),
            "duration_sec": project.get("duration_sec"),
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
