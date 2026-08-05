from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

from app.config import DATA_DIR

GRAPH_VERSION = "v21.0"
GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"
GRAPH_VIDEO = f"https://graph-video.facebook.com/{GRAPH_VERSION}"

DEFAULTS_PATH = DATA_DIR / "facebook.json"


def default_facebook() -> dict[str, Any]:
    return {
        "page_id": "",
        "access_token": "",
        "caption": "",
        "last_post_id": None,
        "last_error": None,
        "last_posted_at": None,
    }


def normalize_facebook(raw: dict | None) -> dict[str, Any]:
    base = default_facebook()
    cur = raw if isinstance(raw, dict) else {}
    base["page_id"] = str(cur.get("page_id") or "").strip()
    base["access_token"] = str(cur.get("access_token") or "").strip()
    base["caption"] = str(cur.get("caption") or "")
    base["last_post_id"] = cur.get("last_post_id") or None
    base["last_error"] = cur.get("last_error") or None
    base["last_posted_at"] = cur.get("last_posted_at") or None
    return base


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_app_defaults() -> dict[str, str]:
    raw = _read_json(DEFAULTS_PATH)
    return {
        "page_id": str(raw.get("page_id") or "").strip(),
        "access_token": str(raw.get("access_token") or "").strip(),
    }


def save_app_defaults(*, page_id: str, access_token: str) -> None:
    cur = _read_json(DEFAULTS_PATH)
    payload = {
        **cur,
        "page_id": (page_id or "").strip(),
        "access_token": (access_token or "").strip(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(DEFAULTS_PATH, payload)


def merge_facebook_for_ui(project_fb: dict | None) -> dict[str, Any]:
    """Project settings override app defaults for page_id / token."""
    fb = normalize_facebook(project_fb)
    defaults = load_app_defaults()
    if not fb["page_id"]:
        fb["page_id"] = defaults.get("page_id") or ""
    if not fb["access_token"]:
        fb["access_token"] = defaults.get("access_token") or ""
    return fb


def public_facebook(fb: dict[str, Any]) -> dict[str, Any]:
    out = dict(fb)
    tok = str(out.get("access_token") or "")
    if len(tok) > 10:
        out["access_token_masked"] = f"{tok[:6]}…{tok[-4:]}"
    else:
        out["access_token_masked"] = "••••" if tok else ""
    return out


def _format_graph_error(body: Any, status: int, body_text: str = "") -> str:
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        msg = err.get("message") or err.get("error_user_msg") or str(err)
        code = err.get("code")
        if code == 100 and "global id" in str(msg).lower():
            return (
                f"{msg}\n\n"
                "ID này không phải Page ID. Dán User token → Lấy danh sách Page → chọn Page."
            )
        if code in {190, 102} or "session has expired" in str(msg).lower():
            return f"{msg}\n\nToken hết hạn/không hợp lệ. Tạo token mới từ Graph API Explorer."
        return str(msg)
    return body_text or f"HTTP {status}"


async def _graph_get(
    path: str,
    token: str | None = None,
    params: dict | None = None,
    *,
    absolute_url: str | None = None,
) -> dict[str, Any]:
    q = dict(params or {})
    if token:
        q["access_token"] = token
    url = absolute_url or f"{GRAPH}/{path.lstrip('/')}"
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params=q) as resp:
            body_text = await resp.text()
            try:
                body = json.loads(body_text) if body_text else {}
            except json.JSONDecodeError:
                body = {"raw": body_text}
            if resp.status >= 400:
                raise RuntimeError(_format_graph_error(body, resp.status, body_text))
            if not isinstance(body, dict):
                raise RuntimeError(f"Facebook trả về dữ liệu lạ: {body_text[:300]}")
            return body


async def list_managed_pages(access_token: str) -> list[dict[str, str]]:
    """Return Pages the token can manage: [{id, name, access_token}]."""
    token = (access_token or "").strip()
    if not token:
        raise ValueError("Thiếu Facebook access token.")

    pages: list[dict[str, str]] = []
    after: str | None = None
    for _ in range(10):
        params: dict[str, Any] = {
            "fields": "id,name,access_token",
            "limit": 100,
        }
        if after:
            params["after"] = after
        body = await _graph_get("me/accounts", token, params)
        for item in body.get("data") or []:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("id") or "").strip()
            if not pid:
                continue
            pages.append(
                {
                    "id": pid,
                    "name": str(item.get("name") or pid),
                    "access_token": str(item.get("access_token") or "").strip(),
                }
            )
        paging = body.get("paging") if isinstance(body.get("paging"), dict) else {}
        cursors = paging.get("cursors") if isinstance(paging.get("cursors"), dict) else {}
        after = str(cursors.get("after") or "").strip() or None
        if not after or not paging.get("next"):
            break

    if not pages:
        raise RuntimeError(
            "Token này không quản lý Page nào.\n"
            "Cần User token có quyền pages_show_list (+ pages_manage_posts để đăng), "
            "và tài khoản phải là Admin của Page."
        )
    return pages


async def resolve_page_credentials(
    *, page_id: str, access_token: str
) -> tuple[str, str, str]:
    """Return (page_id, page_access_token, page_name)."""
    pid = (page_id or "").strip()
    token = (access_token or "").strip()
    if not pid:
        raise ValueError("Thiếu Page ID.")
    if not token:
        raise ValueError("Thiếu Facebook access token.")

    try:
        pages = await list_managed_pages(token)
        match = next((p for p in pages if p["id"] == pid), None)
        if match is not None:
            page_token = match["access_token"] or token
            return match["id"], page_token, match["name"]
        names = ", ".join(f"{p['name']} ({p['id']})" for p in pages[:8])
        raise ValueError(
            f"ID «{pid}» không khớp Page nào token này quản lý.\n"
            f"Page khả dụng: {names}"
        )
    except RuntimeError as exc:
        if "không quản lý Page" in str(exc):
            raise
        # Token may already be a Page token — upload with it directly.
        return pid, token, pid


async def upload_page_video(
    *,
    page_id: str,
    access_token: str,
    video_path: Path,
    caption: str = "",
    title: str = "",
) -> dict[str, Any]:
    """Upload an MP4 to a Facebook Page via Graph Video API."""
    if not video_path.exists():
        raise FileNotFoundError(f"Không tìm thấy video: {video_path}")

    pid, token, page_name = await resolve_page_credentials(
        page_id=page_id, access_token=access_token
    )

    url = f"{GRAPH_VIDEO}/{pid}/videos"
    timeout = aiohttp.ClientTimeout(total=900, sock_connect=30, sock_read=900)

    form = aiohttp.FormData()
    form.add_field("access_token", token)
    form.add_field("published", "true")
    if caption:
        form.add_field("description", caption)
    if title:
        form.add_field("title", title[:255])

    data = video_path.read_bytes()
    form.add_field(
        "source",
        data,
        filename=video_path.name or "video.mp4",
        content_type="video/mp4",
    )

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, data=form) as resp:
            body_text = await resp.text()
            try:
                body = json.loads(body_text) if body_text else {}
            except json.JSONDecodeError:
                body = {"raw": body_text}
            if resp.status >= 400:
                raise RuntimeError(
                    "Facebook API lỗi: "
                    + _format_graph_error(body, resp.status, body_text)
                )
            video_id = body.get("id") if isinstance(body, dict) else None
            if not video_id:
                raise RuntimeError(f"Facebook không trả về video id: {body_text[:400]}")
            return {
                "id": str(video_id),
                "page_id": pid,
                "page_name": page_name,
                "raw": body,
            }
