"""AstrBot 天菜视频库插件。

Batch 1：索引 v2、权限白名单、冷却、软删除指令、降权随机
Batch 2：WebUI 管理台（总览 / 列表 / 回收站 / 上传下载）
Batch 3：顺序编号、默认标签「天菜」、卡片内视频预览
Batch 4：公共天菜源（GitHub index + URL 视频，只读同步/缓存/混合抽取）
Batch 5：GitHub Token 上传 Release、代理拉取
Batch 6：默认公共源、UI 改配置/指令、公共视频自动入库、开放发布、去口令
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import mimetypes
import random
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import File, Reply, Video
from astrbot.api.star import Context, Star, register
from astrbot.api.web import (
    PluginUploadFile,
    error_response,
    file_response,
    json_response,
    request,
)
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

PLUGIN_NAME = "astrbot_plugin_tiancai"
INDEX_FILENAME = "index.json"
LOG_FILENAME = "audit.log"
PUBLIC_INDEX_CACHE = "public_index.cache.json"
PUBLIC_META_FILE = "public_sync_meta.json"
INDEX_VERSION = 3
DEFAULT_TAGS = ["天菜"]
# 预览走 base64，过大则提示改用下载（避免拖垮 Dashboard）
PREVIEW_MAX_BYTES = 48 * 1024 * 1024
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv"}
SAFE_ID_RE = re.compile(r"^[a-fA-F0-9]{8,64}$")
SAFE_CODE_RE = re.compile(r"^[0-9a-fA-F]{1,64}$")
PUBLIC_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")
DEFAULT_GITHUB_PROXY = "https://gh-proxy.com/"
DEFAULT_PUBLIC_INDEX_URL = (
    "https://raw.githubusercontent.com/sxd55/astrbot_plugin_tiancai/"
    "main/public/public_index.json"
)
GITHUB_API = "https://api.github.com"

# UI/配置可改的键（不含 secret 回显）
CONFIG_PUBLIC_KEYS = [
    "storage_subdir",
    "max_videos",
    "allow_duplicate",
    "collect_whitelist",
    "cooldown_seconds",
    "recent_penalty_count",
    "recent_penalty_weight",
    "pinned_weight",
    "public_enabled",
    "public_index_url",
    "library_mode",
    "public_sync_hours",
    "public_auto_import",
    "public_weight",
    "github_proxy",
    "github_repo",
    "github_branch",
    "github_index_path",
    "github_release_tag",
    "max_public_upload_mb",
    "cmd_collect",
    "cmd_show",
    "cmd_count",
    "cmd_delete",
    "cmd_detail",
    "cmd_help",
    "cmd_clear",
    "cmd_sync",
]
CONFIG_SECRET_KEYS = ["github_token"]


def _now() -> int:
    return int(time.time())


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                out.append(text)
        return out
    text = str(value).strip()
    return [text] if text else []


@register(
    PLUGIN_NAME,
    "sxd55",
    "收藏群视频到本地，随机「看看天菜」",
    "1.7.1",
)
class TiancaiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        self.data_dir = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        self.videos_dir = self.data_dir / str(
            self.config.get("storage_subdir", "videos") or "videos"
        )
        self.public_cache_dir = self.data_dir / "public_cache"
        self.index_path = self.data_dir / INDEX_FILENAME
        self.log_path = self.data_dir / LOG_FILENAME
        self.public_index_path = self.data_dir / PUBLIC_INDEX_CACHE
        self.public_meta_path = self.data_dir / PUBLIC_META_FILE
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.videos_dir.mkdir(parents=True, exist_ok=True)
        self.public_cache_dir.mkdir(parents=True, exist_ok=True)
        self._cooldowns: dict[str, float] = {}
        self._public_sync_lock = asyncio.Lock()
        self._publish_lock = asyncio.Lock()
        self._ensure_index()
        self._register_web_apis()

    def _register_web_apis(self) -> None:
        apis = [
            ("stats", self.api_stats, ["GET"], "天菜库总览统计"),
            ("videos", self.api_list_videos, ["GET"], "天菜列表"),
            ("videos/delete", self.api_delete_videos, ["POST"], "软删除天菜"),
            ("videos/restore", self.api_restore_videos, ["POST"], "恢复天菜"),
            ("videos/purge", self.api_purge_videos, ["POST"], "永久删除天菜"),
            ("videos/update", self.api_update_video, ["POST"], "更新备注/标签/置顶"),
            ("videos/upload", self.api_upload_video, ["POST"], "上传视频入库"),
            ("videos/download", self.api_download_video, ["GET"], "下载视频文件"),
            ("videos/media", self.api_media_video, ["GET"], "预览用媒体数据"),
            ("logs", self.api_logs, ["GET"], "审计日志"),
            ("public/status", self.api_public_status, ["GET"], "公共源状态"),
            ("public/sync", self.api_public_sync, ["POST"], "手动同步公共菜单"),
            ("public/publish", self.api_public_publish, ["POST"], "批量发布到公共库"),
            ("public/managed/list", self.api_public_managed_list, ["GET"], "列出可管理的公共库"),
            ("public/managed/update", self.api_public_managed_update, ["POST"], "编辑公共库条目"),
            ("public/managed/delete", self.api_public_managed_delete, ["POST"], "删除公共库条目"),
            ("public/managed/import", self.api_public_managed_import, ["POST"], "公共库下载到本地"),
            ("public/managed/media", self.api_public_managed_media, ["GET"], "公共库预览媒体"),
            ("config/get", self.api_config_get, ["GET"], "读取插件配置"),
            ("config/save", self.api_config_save, ["POST"], "保存插件配置"),
        ]
        for path, handler, methods, desc in apis:
            self.context.register_web_api(
                f"/{PLUGIN_NAME}/{path}",
                handler,
                methods,
                desc,
            )

    async def initialize(self):
        index = self._load_index()
        active = self._active_videos(index)
        logger.info(
            "天菜视频库已加载 v%s，目录=%s，在库=%s，回收站=%s",
            index.get("version", 1),
            self.videos_dir,
            len(active),
            len(index.get("videos", [])) - len(active),
        )
        if self._public_enabled():
            try:
                result = await self._sync_public_index(force=False)
                logger.info("公共天菜源同步：%s", result.get("message"))
            except Exception:  # noqa: BLE001
                logger.exception("启动时同步公共天菜源失败")

    # ------------------------------------------------------------------
    # Web API（管理台）
    # ------------------------------------------------------------------

    async def api_stats(self):
        index = self._load_index()
        videos = [v for v in index.get("videos", []) if isinstance(v, dict)]
        active = [v for v in videos if v.get("deleted_at") is None]
        trash = [v for v in videos if v.get("deleted_at") is not None]
        total_size = 0
        missing = 0
        for item in active:
            path = self.videos_dir / str(item.get("filename", ""))
            if path.is_file():
                try:
                    total_size += path.stat().st_size
                except OSError:
                    pass
            else:
                missing += 1

        day_start = _now() - (_now() % 86400)
        collected_today = sum(
            1 for v in active if int(v.get("saved_at") or 0) >= day_start
        )
        played_today = sum(
            1 for v in active if int(v.get("last_played_at") or 0) >= day_start
        )

        recent = sorted(
            videos,
            key=lambda x: int(x.get("saved_at") or 0),
            reverse=True,
        )[:8]
        recent_play = sorted(
            [v for v in active if v.get("last_played_at")],
            key=lambda x: int(x.get("last_played_at") or 0),
            reverse=True,
        )[:8]

        return json_response(
            {
                "version": index.get("version", INDEX_VERSION),
                "active_count": len(active),
                "trash_count": len(trash),
                "missing_count": missing,
                "total_size": total_size,
                "total_size_human": self._fmt_size(total_size),
                "collected_today": collected_today,
                "played_today": played_today,
                "videos_dir": str(self.videos_dir),
                "cooldown_seconds": int(self.config.get("cooldown_seconds", 15) or 0),
                "max_videos": int(self.config.get("max_videos", 0) or 0),
                "recent_collected": [self._public_item(v) for v in recent],
                "recent_played": [self._public_item(v) for v in recent_play],
                "public": self._public_status_dict(),
            }
        )

    async def api_list_videos(self):
        index = self._load_index()
        scope = str(request.query.get("scope", "active") or "active").lower()
        q = str(request.query.get("q", "") or "").strip().lower()
        tag = str(request.query.get("tag", "") or "").strip().lower()
        sort = str(request.query.get("sort", "saved_at") or "saved_at")
        order = str(request.query.get("order", "desc") or "desc").lower()
        try:
            page = max(int(request.query.get("page", 1) or 1), 1)
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = int(request.query.get("page_size", 20) or 20)
        except (TypeError, ValueError):
            page_size = 20
        page_size = min(max(page_size, 1), 100)

        items = [v for v in index.get("videos", []) if isinstance(v, dict)]
        if scope == "trash":
            items = [v for v in items if v.get("deleted_at") is not None]
        elif scope == "all":
            pass
        else:
            items = [v for v in items if v.get("deleted_at") is None]

        if q:
            def match(v: dict[str, Any]) -> bool:
                seq = str(v.get("seq") or "")
                blob = " ".join(
                    [
                        str(v.get("id") or ""),
                        seq,
                        f"#{seq}" if seq else "",
                        str(v.get("note") or ""),
                        str(v.get("collector_name") or ""),
                        str(v.get("collector_id") or ""),
                        str(v.get("source_group_id") or ""),
                        " ".join(str(t) for t in (v.get("tags") or [])),
                    ]
                ).lower()
                return q in blob

            items = [v for v in items if match(v)]

        if tag:
            items = [
                v
                for v in items
                if any(str(t).lower() == tag for t in (v.get("tags") or []))
            ]

        reverse = order != "asc"
        if sort == "size":
            items.sort(key=lambda x: int(x.get("size") or 0), reverse=reverse)
        elif sort == "play_count":
            items.sort(key=lambda x: int(x.get("play_count") or 0), reverse=reverse)
        elif sort == "last_played_at":
            items.sort(
                key=lambda x: int(x.get("last_played_at") or 0), reverse=reverse
            )
        elif sort == "seq":
            items.sort(key=lambda x: int(x.get("seq") or 0), reverse=reverse)
        else:
            items.sort(key=lambda x: int(x.get("saved_at") or 0), reverse=reverse)

        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = items[start:end]

        return json_response(
            {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": [self._public_item(v) for v in page_items],
            }
        )

    async def api_delete_videos(self):
        payload = await request.json(default={})
        ids = self._normalize_ids(payload.get("ids"))
        if not ids:
            return error_response("ids required", status_code=400)

        index = self._load_index()
        moved = 0
        for item in index.get("videos", []):
            if str(item.get("id")) in ids and item.get("deleted_at") is None:
                item["deleted_at"] = _now()
                item["deleted_by"] = f"web:{request.username or 'dashboard'}"
                moved += 1
                self._audit(
                    "web_soft_delete",
                    video_id=str(item.get("id")),
                    detail=f"by={request.username}",
                )
        self._save_index(index)
        return json_response({"moved": moved})

    async def api_restore_videos(self):
        payload = await request.json(default={})
        ids = self._normalize_ids(payload.get("ids"))
        if not ids:
            return error_response("ids required", status_code=400)

        index = self._load_index()
        restored = 0
        for item in index.get("videos", []):
            if str(item.get("id")) in ids and item.get("deleted_at") is not None:
                path = self.videos_dir / str(item.get("filename", ""))
                if not path.is_file():
                    continue
                item["deleted_at"] = None
                item["deleted_by"] = None
                restored += 1
                self._audit(
                    "web_restore",
                    video_id=str(item.get("id")),
                    detail=f"by={request.username}",
                )
        self._save_index(index)
        return json_response({"restored": restored})

    async def api_purge_videos(self):
        payload = await request.json(default={})
        ids = self._normalize_ids(payload.get("ids"))
        if not ids:
            return error_response("ids required", status_code=400)

        index = self._load_index()
        kept: list[dict[str, Any]] = []
        purged = 0
        for item in index.get("videos", []):
            vid = str(item.get("id") or "")
            if vid in ids and item.get("deleted_at") is not None:
                path = self.videos_dir / str(item.get("filename", ""))
                if path.is_file():
                    try:
                        path.unlink()
                    except OSError:
                        logger.exception("永久删除文件失败: %s", path)
                purged += 1
                self._audit(
                    "web_purge",
                    video_id=vid,
                    detail=f"by={request.username}",
                )
            else:
                kept.append(item)
        index["videos"] = kept
        # 清理 recent
        index["recent_sent_ids"] = [
            x for x in index.get("recent_sent_ids", []) if str(x) not in ids
        ]
        self._save_index(index)
        return json_response({"purged": purged})

    async def api_update_video(self):
        payload = await request.json(default={})
        video_id = str(payload.get("id") or "").strip()
        target = None
        index = self._load_index()

        if video_id and SAFE_ID_RE.match(video_id):
            for item in index.get("videos", []):
                if str(item.get("id")) == video_id:
                    target = item
                    break
        else:
            # 也允许用顺序编号更新
            try:
                seq = int(payload.get("seq") or payload.get("id") or 0)
            except (TypeError, ValueError):
                seq = 0
            if seq > 0:
                for item in index.get("videos", []):
                    if int(item.get("seq") or 0) == seq:
                        target = item
                        video_id = str(item.get("id"))
                        break

        if target is None:
            return error_response("not found", status_code=404)

        if "note" in payload:
            note = str(payload.get("note") or "")
            target["note"] = note[:200]
        if "tags" in payload:
            tags_raw = payload.get("tags")
            tags: list[str] = []
            if isinstance(tags_raw, list):
                for t in tags_raw:
                    text = str(t).strip()
                    if text and text not in tags:
                        tags.append(text[:32])
            elif isinstance(tags_raw, str):
                for part in re.split(r"[,，\s]+", tags_raw):
                    text = part.strip()
                    if text and text not in tags:
                        tags.append(text[:32])
            if not tags:
                tags = list(DEFAULT_TAGS)
            target["tags"] = tags[:20]
        if "pinned" in payload:
            target["pinned"] = bool(payload.get("pinned"))

        self._save_index(index)
        self._audit(
            "web_update",
            video_id=video_id,
            detail=f"by={request.username}",
        )
        return json_response({"item": self._public_item(target)})

    async def api_upload_video(self):
        files = await request.files()
        upload: PluginUploadFile | None = files.get("file")
        if not isinstance(upload, PluginUploadFile):
            return error_response("missing file", status_code=400)

        filename = Path(upload.filename or "upload.mp4").name
        suffix = Path(filename).suffix.lower() or ".mp4"
        if suffix not in VIDEO_SUFFIXES:
            return error_response(
                f"unsupported type {suffix}, allow: {', '.join(sorted(VIDEO_SUFFIXES))}",
                status_code=400,
            )

        index = self._load_index()
        max_videos = int(self.config.get("max_videos", 0) or 0)
        active_count = len(self._active_videos(index))
        if max_videos > 0 and active_count >= max_videos:
            return error_response(f"library full (max {max_videos})", status_code=400)

        video_id = uuid.uuid4().hex
        dest = self.videos_dir / f"{video_id}{suffix}"
        try:
            await upload.save(dest)
        except Exception as exc:  # noqa: BLE001
            logger.exception("上传保存失败")
            return error_response(f"save failed: {exc}", status_code=500)

        size = dest.stat().st_size if dest.is_file() else 0
        seq = self._next_seq(index)
        record = self._new_record(
            video_id=video_id,
            filename=dest.name,
            size=size,
            source_message_id="",
            source_group_id="",
            collector_id=f"web:{request.username or 'dashboard'}",
            collector_name=str(request.username or "dashboard"),
            seq=seq,
        )
        record["note"] = f"WebUI 上传 · {filename}"[:200]
        index.setdefault("videos", []).append(record)
        index["next_seq"] = seq + 1
        self._save_index(index)
        self._audit(
            "web_upload",
            video_id=video_id,
            detail=f"name={filename};size={size};seq={seq};by={request.username}",
        )
        return json_response({"item": self._public_item(record)})

    async def api_download_video(self):
        target = self._find_by_query_id()
        if target is None:
            return error_response("not found", status_code=404)

        path = self.videos_dir / str(target.get("filename", ""))
        if not path.is_file():
            return error_response("file missing", status_code=404)

        seq = int(target.get("seq") or 0)
        name = f"tiancai_{seq or str(target.get('id'))[:8]}{path.suffix or '.mp4'}"
        mime, _ = mimetypes.guess_type(str(path))
        return file_response(
            path,
            filename=name,
            content_type=mime or "video/mp4",
        )

    async def api_media_video(self):
        """返回 data URL，供管理台 <video> 预览（小文件）。"""
        target = self._find_by_query_id()
        if target is None:
            return error_response("not found", status_code=404)

        path = self.videos_dir / str(target.get("filename", ""))
        if not path.is_file():
            return error_response("file missing", status_code=404)

        size = path.stat().st_size
        if size > PREVIEW_MAX_BYTES:
            return error_response(
                f"file too large for inline preview ({self._fmt_size(size)}), use download",
                status_code=413,
            )

        mime, _ = mimetypes.guess_type(str(path))
        mime = mime or "video/mp4"
        try:
            data = path.read_bytes()
        except OSError as exc:
            return error_response(f"read failed: {exc}", status_code=500)

        b64 = base64.b64encode(data).decode("ascii")
        return json_response(
            {
                "id": target.get("id"),
                "seq": target.get("seq"),
                "mime": mime,
                "size": size,
                "data_url": f"data:{mime};base64,{b64}",
            }
        )

    def _find_by_query_id(self) -> dict[str, Any] | None:
        raw = str(request.query.get("id", "") or "").strip()
        seq_raw = str(request.query.get("seq", "") or "").strip()
        index = self._load_index()
        if raw and SAFE_ID_RE.match(raw):
            for item in index.get("videos", []):
                if str(item.get("id")) == raw:
                    return item
        # 纯数字：当顺序号
        code = raw or seq_raw
        if code.isdigit():
            seq = int(code)
            for item in index.get("videos", []):
                if int(item.get("seq") or 0) == seq:
                    return item
        return None

    async def api_logs(self):
        try:
            limit = int(request.query.get("limit", 50) or 50)
        except (TypeError, ValueError):
            limit = 50
        limit = min(max(limit, 1), 200)

        if not self.log_path.exists():
            return json_response({"items": []})

        try:
            lines = self.log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return error_response("read log failed", status_code=500)

        items = []
        for line in reversed(lines[-limit:]):
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            items.append(
                {
                    "raw": line,
                    "ts": parts[0] if parts else "",
                    "action": parts[1] if len(parts) > 1 else "",
                    "user": parts[2] if len(parts) > 2 else "",
                    "group": parts[3] if len(parts) > 3 else "",
                    "video": parts[4] if len(parts) > 4 else "",
                    "detail": parts[5] if len(parts) > 5 else "",
                }
            )
        return json_response({"items": items})

    async def api_public_status(self):
        return json_response(self._public_status_dict())

    async def api_public_sync(self):
        if not self._public_enabled():
            return error_response("public source disabled", status_code=400)
        try:
            result = await self._sync_public_index(force=True)
        except Exception as exc:  # noqa: BLE001
            logger.exception("手动同步公共源失败")
            return error_response(str(exc), status_code=500)
        return json_response(result)

    async def api_public_publish(self):
        token = str(self.config.get("github_token") or "").strip()
        repo = str(self.config.get("github_repo") or "").strip()
        if not token:
            return error_response(
                "未配置 github_token。请在「设置」页填写你自己的 GitHub Token。",
                status_code=400,
            )
        if not repo:
            return error_response(
                "未配置 github_repo。发布必须填写你自己的仓库（owner/repo），"
                "例如 yourname/tiancai-public。不会默认写到官方仓库。",
                status_code=400,
            )

        payload = await request.json(default={})
        ids = self._normalize_ids(payload.get("ids"))
        if not ids:
            return error_response("ids required", status_code=400)

        async with self._publish_lock:
            try:
                result = await asyncio.to_thread(
                    self._publish_local_ids_to_github, ids, token
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("发布公共库失败")
                return error_response(str(exc), status_code=500)
        self._audit(
            "public_publish",
            detail=(
                f"user={request.username};ok={result.get('published')};"
                f"fail={result.get('failed')};repo={repo}"
            ),
        )
        return json_response(result)

    def _require_managed_repo(self) -> tuple[str, str] | Any:
        token = str(self.config.get("github_token") or "").strip()
        repo = str(self.config.get("github_repo") or "").strip()
        if not token:
            return error_response(
                "未配置 github_token。管理公共库需要 Token。",
                status_code=400,
            )
        if not repo:
            return error_response(
                "未配置 github_repo。请填写你自己的仓库 owner/repo。",
                status_code=400,
            )
        if not re.match(r"^[^/\s]+/[^/\s]+$", repo):
            return error_response("github_repo 格式应为 owner/repo", status_code=400)
        return token, repo

    def _public_item_view(self, item: dict[str, Any]) -> dict[str, Any]:
        size = int(item.get("size") or 0)
        return {
            "id": item.get("id"),
            "seq": int(item.get("seq") or 0),
            "title": item.get("title") or "",
            "tags": item.get("tags") or [],
            "url": item.get("url") or "",
            "size": size,
            "size_human": self._fmt_size(size),
            "created_at": item.get("created_at"),
            "created_at_human": self._fmt_time(item.get("created_at")) or "",
            "source_local_id": item.get("source_local_id") or "",
            "source_local_seq": item.get("source_local_seq"),
            "can_preview": bool(size) and size <= PREVIEW_MAX_BYTES,
        }

    async def api_public_managed_list(self):
        req = self._require_managed_repo()
        if not isinstance(req, tuple):
            return req
        token, repo = req
        branch = str(self.config.get("github_branch") or "main").strip() or "main"
        index_path = (
            str(self.config.get("github_index_path") or "public/public_index.json").strip()
            or "public/public_index.json"
        )
        try:
            remote = await asyncio.to_thread(
                self._github_get_index_file, repo, branch, index_path, token
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("读取可管理公共库失败")
            return error_response(str(exc), status_code=500)

        videos = [
            self._public_item_view(v)
            for v in (remote.get("videos") or [])
            if isinstance(v, dict)
        ]
        videos.sort(key=lambda x: int(x.get("seq") or 0))
        # 同步一份到本地公共缓存，方便抽取
        cache_payload = {k: v for k, v in remote.items() if not str(k).startswith("_")}
        try:
            self.public_index_path.write_text(
                json.dumps(cache_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            logger.exception("写入公共菜单缓存失败")

        return json_response(
            {
                "repo": repo,
                "branch": branch,
                "index_path": index_path,
                "name": remote.get("name") or "",
                "updated_at": remote.get("updated_at"),
                "updated_at_human": self._fmt_time(remote.get("updated_at")) or "",
                "total": len(videos),
                "items": videos,
            }
        )

    async def api_public_managed_update(self):
        req = self._require_managed_repo()
        if not isinstance(req, tuple):
            return req
        token, repo = req
        payload = await request.json(default={})
        item_id = str(payload.get("id") or "").strip()
        if not item_id:
            return error_response("id required", status_code=400)

        branch = str(self.config.get("github_branch") or "main").strip() or "main"
        index_path = (
            str(self.config.get("github_index_path") or "public/public_index.json").strip()
            or "public/public_index.json"
        )

        async with self._publish_lock:
            try:
                remote = await asyncio.to_thread(
                    self._github_get_index_file, repo, branch, index_path, token
                )
                videos = remote.get("videos") or []
                if not isinstance(videos, list):
                    return error_response("remote index invalid", status_code=500)
                target = None
                for v in videos:
                    if isinstance(v, dict) and str(v.get("id")) == item_id:
                        target = v
                        break
                if target is None:
                    return error_response("not found", status_code=404)

                if "title" in payload:
                    target["title"] = str(payload.get("title") or "")[:200]
                if "tags" in payload:
                    tags_raw = payload.get("tags")
                    tags: list[str] = []
                    if isinstance(tags_raw, list):
                        for t in tags_raw:
                            text = str(t).strip()
                            if text and text not in tags:
                                tags.append(text[:32])
                    elif isinstance(tags_raw, str):
                        for part in re.split(r"[,，\s]+", tags_raw):
                            text = part.strip()
                            if text and text not in tags:
                                tags.append(text[:32])
                    if not tags:
                        tags = list(DEFAULT_TAGS)
                    target["tags"] = tags[:20]

                remote["updated_at"] = _now()
                await asyncio.to_thread(
                    self._github_put_index_file, repo, branch, index_path, remote, token
                )
                cache_payload = {
                    k: v for k, v in remote.items() if not str(k).startswith("_")
                }
                self.public_index_path.write_text(
                    json.dumps(cache_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("更新公共库条目失败")
                return error_response(str(exc), status_code=500)

        self._audit(
            "public_managed_update",
            detail=f"user={request.username};id={item_id};repo={repo}",
        )
        return json_response({"ok": True, "item": self._public_item_view(target)})

    async def api_public_managed_delete(self):
        req = self._require_managed_repo()
        if not isinstance(req, tuple):
            return req
        token, repo = req
        payload = await request.json(default={})
        raw_ids = payload.get("ids")
        if isinstance(raw_ids, str):
            raw_ids = [raw_ids]
        if not isinstance(raw_ids, list) or not raw_ids:
            return error_response("ids required", status_code=400)
        ids = {str(x).strip() for x in raw_ids if str(x).strip()}
        if not ids:
            return error_response("ids required", status_code=400)

        branch = str(self.config.get("github_branch") or "main").strip() or "main"
        index_path = (
            str(self.config.get("github_index_path") or "public/public_index.json").strip()
            or "public/public_index.json"
        )
        release_tag = (
            str(self.config.get("github_release_tag") or "tiancai-videos").strip()
            or "tiancai-videos"
        )

        async with self._publish_lock:
            try:
                result = await asyncio.to_thread(
                    self._managed_delete_public_ids,
                    token,
                    repo,
                    branch,
                    index_path,
                    release_tag,
                    ids,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("删除公共库条目失败")
                return error_response(str(exc), status_code=500)

        self._audit(
            "public_managed_delete",
            detail=(
                f"user={request.username};deleted={result.get('deleted')};"
                f"repo={repo}"
            ),
        )
        return json_response(result)

    async def api_public_managed_import(self):
        req = self._require_managed_repo()
        if not isinstance(req, tuple):
            return req
        token, repo = req
        payload = await request.json(default={})
        raw_ids = payload.get("ids")
        if isinstance(raw_ids, str):
            raw_ids = [raw_ids]
        if not isinstance(raw_ids, list) or not raw_ids:
            return error_response("ids required", status_code=400)
        ids = {str(x).strip() for x in raw_ids if str(x).strip()}

        branch = str(self.config.get("github_branch") or "main").strip() or "main"
        index_path = (
            str(self.config.get("github_index_path") or "public/public_index.json").strip()
            or "public/public_index.json"
        )
        try:
            remote = await asyncio.to_thread(
                self._github_get_index_file, repo, branch, index_path, token
            )
        except Exception as exc:  # noqa: BLE001
            return error_response(str(exc), status_code=500)

        by_id = {
            str(v.get("id")): v
            for v in (remote.get("videos") or [])
            if isinstance(v, dict) and v.get("id")
        }
        imported = []
        failed = []
        skipped = []
        for item_id in ids:
            item = by_id.get(item_id)
            if not item:
                failed.append({"id": item_id, "error": "公共库中不存在"})
                continue
            # 已存在则跳过
            index = self._load_index()
            exists = any(
                isinstance(v, dict)
                and v.get("deleted_at") is None
                and str(v.get("source_public_id") or "") == item_id
                for v in index.get("videos", [])
            )
            if exists:
                skipped.append({"id": item_id, "error": "本地已导入"})
                continue
            try:
                url = str(item.get("url") or "")
                suffix = Path(urlparse(url).path).suffix.lower() or ".mp4"
                if suffix not in VIDEO_SUFFIXES:
                    suffix = ".mp4"
                cache_path = self.public_cache_dir / f"{item_id}{suffix}"
                await asyncio.to_thread(self._http_download, url, cache_path)
                record = self._import_cached_public_video(item, cache_path)
                if record is None:
                    failed.append({"id": item_id, "error": "导入失败（库满或写入失败）"})
                else:
                    imported.append(
                        {
                            "id": item_id,
                            "local_id": record.get("id"),
                            "seq": record.get("seq"),
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                failed.append({"id": item_id, "error": str(exc)})

        self._audit(
            "public_managed_import",
            detail=(
                f"user={request.username};ok={len(imported)};"
                f"fail={len(failed)};repo={repo}"
            ),
        )
        return json_response(
            {
                "imported": len(imported),
                "failed": len(failed),
                "skipped": len(skipped),
                "items": imported,
                "errors": failed,
                "skipped_items": skipped,
            }
        )

    def _managed_delete_public_ids(
        self,
        token: str,
        repo: str,
        branch: str,
        index_path: str,
        release_tag: str,
        ids: set[str],
    ) -> dict[str, Any]:
        remote = self._github_get_index_file(repo, branch, index_path, token)
        videos = remote.get("videos") or []
        if not isinstance(videos, list):
            raise RuntimeError("remote index invalid")

        kept: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []
        for v in videos:
            if not isinstance(v, dict):
                continue
            vid = str(v.get("id") or "")
            if vid in ids:
                removed.append(v)
            else:
                kept.append(v)

        # 尝试删除 Release 附件
        asset_errors: list[dict[str, str]] = []
        try:
            release = self._github_ensure_release(repo, release_tag, token)
            release_id = release.get("id")
            assets = release.get("assets") or []
            if not isinstance(assets, list) and release_id:
                assets = self._http_json(
                    "GET",
                    f"{GITHUB_API}/repos/{repo}/releases/{release_id}/assets",
                    token=token,
                )
            name_to_asset = {
                str(a.get("name")): a
                for a in (assets or [])
                if isinstance(a, dict) and a.get("name")
            }
            for item in removed:
                url = str(item.get("url") or "")
                asset_name = Path(urlparse(url).path).name
                # 也尝试 id + 常见后缀
                candidates = [asset_name] if asset_name else []
                pid = str(item.get("id") or "")
                for suf in VIDEO_SUFFIXES:
                    candidates.append(f"{pid}{suf}")
                deleted_asset = False
                for name in candidates:
                    asset = name_to_asset.get(name)
                    if not asset:
                        continue
                    asset_id = asset.get("id")
                    if not asset_id:
                        continue
                    try:
                        self._http_json(
                            "DELETE",
                            f"{GITHUB_API}/repos/{repo}/releases/assets/{asset_id}",
                            token=token,
                        )
                        deleted_asset = True
                        break
                    except Exception as exc:  # noqa: BLE001
                        asset_errors.append({"id": pid, "error": str(exc)})
                if not deleted_asset and asset_name:
                    # 附件可能已不在，不算致命
                    pass
        except Exception as exc:  # noqa: BLE001
            asset_errors.append({"id": "*", "error": f"release cleanup: {exc}"})

        remote["videos"] = kept
        remote["updated_at"] = _now()
        self._github_put_index_file(repo, branch, index_path, remote, token)
        cache_payload = {k: v for k, v in remote.items() if not str(k).startswith("_")}
        self.public_index_path.write_text(
            json.dumps(cache_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "deleted": len(removed),
            "remaining": len(kept),
            "items": [self._public_item_view(v) for v in removed],
            "asset_errors": asset_errors,
            "repo": repo,
        }

    async def api_public_managed_media(self):
        """下载公共视频到缓存后返回 data URL，供公共库页预览。"""
        req = self._require_managed_repo()
        if not isinstance(req, tuple):
            return req
        token, repo = req
        item_id = str(request.query.get("id", "") or "").strip()
        if not item_id:
            return error_response("id required", status_code=400)

        branch = str(self.config.get("github_branch") or "main").strip() or "main"
        index_path = (
            str(self.config.get("github_index_path") or "public/public_index.json").strip()
            or "public/public_index.json"
        )
        try:
            remote = await asyncio.to_thread(
                self._github_get_index_file, repo, branch, index_path, token
            )
        except Exception as exc:  # noqa: BLE001
            return error_response(str(exc), status_code=500)

        target = None
        for v in remote.get("videos") or []:
            if isinstance(v, dict) and str(v.get("id")) == item_id:
                target = v
                break
        if target is None:
            return error_response("not found", status_code=404)

        url = str(target.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return error_response("invalid url", status_code=400)

        size_hint = int(target.get("size") or 0)
        if size_hint > PREVIEW_MAX_BYTES:
            return error_response(
                f"file too large for inline preview ({self._fmt_size(size_hint)}), use download",
                status_code=413,
            )

        suffix = Path(urlparse(url).path).suffix.lower() or ".mp4"
        if suffix not in VIDEO_SUFFIXES:
            suffix = ".mp4"
        cache_path = self.public_cache_dir / f"{item_id}{suffix}"
        try:
            if not (cache_path.is_file() and cache_path.stat().st_size > 0):
                await asyncio.to_thread(self._http_download, url, cache_path)
            if not cache_path.is_file():
                return error_response("download failed", status_code=500)
            size = cache_path.stat().st_size
            if size > PREVIEW_MAX_BYTES:
                return error_response(
                    f"file too large for inline preview ({self._fmt_size(size)}), use download",
                    status_code=413,
                )
            mime, _ = mimetypes.guess_type(str(cache_path))
            mime = mime or "video/mp4"
            data = await asyncio.to_thread(cache_path.read_bytes)
            b64 = base64.b64encode(data).decode("ascii")
            return json_response(
                {
                    "id": item_id,
                    "seq": target.get("seq"),
                    "mime": mime,
                    "size": size,
                    "data_url": f"data:{mime};base64,{b64}",
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("公共库预览失败")
            return error_response(str(exc), status_code=500)

    async def api_config_get(self):
        data = {}
        for key in CONFIG_PUBLIC_KEYS:
            if key == "collect_whitelist":
                data[key] = _as_str_list(self.config.get(key))
            else:
                data[key] = self.config.get(key)
        # 默认值补齐
        if not data.get("public_index_url"):
            data["public_index_url"] = DEFAULT_PUBLIC_INDEX_URL
        if data.get("public_enabled") is None:
            data["public_enabled"] = True
        if data.get("public_auto_import") is None:
            data["public_auto_import"] = True
        if not data.get("library_mode"):
            data["library_mode"] = "mixed"
        data["github_token_configured"] = bool(
            str(self.config.get("github_token") or "").strip()
        )
        data["github_proxy_effective"] = self._github_proxy_prefix()
        return json_response({"config": data})

    async def api_config_save(self):
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("invalid payload", status_code=400)

        changed = []
        for key in CONFIG_PUBLIC_KEYS + CONFIG_SECRET_KEYS:
            if key not in payload:
                continue
            value = payload.get(key)
            if key == "collect_whitelist":
                if isinstance(value, str):
                    value = [x.strip() for x in re.split(r"[,，\s]+", value) if x.strip()]
                elif not isinstance(value, list):
                    value = _as_str_list(value)
            if key in {
                "public_enabled",
                "allow_duplicate",
                "public_auto_import",
            }:
                value = bool(value)
            if key in {
                "max_videos",
                "cooldown_seconds",
                "recent_penalty_count",
                "max_public_upload_mb",
            }:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            if key in {
                "recent_penalty_weight",
                "pinned_weight",
                "public_sync_hours",
                "public_weight",
            }:
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue
            if key == "library_mode":
                value = str(value or "mixed").strip().lower()
                if value not in {"local", "public", "mixed"}:
                    value = "mixed"
            if key.startswith("cmd_"):
                value = str(value or "").strip()
                if not value:
                    continue
            if key == "github_token":
                # 空字符串表示不修改已有 token
                if value is None or str(value) == "":
                    continue
                value = str(value).strip()
            self.config[key] = value
            changed.append(key)

        try:
            if hasattr(self.config, "save_config"):
                self.config.save_config()
        except Exception:  # noqa: BLE001
            logger.exception("保存配置失败")
            return error_response("save_config failed", status_code=500)

        # 目录可能变更
        self.videos_dir = self.data_dir / str(
            self.config.get("storage_subdir", "videos") or "videos"
        )
        self.videos_dir.mkdir(parents=True, exist_ok=True)
        self._audit(
            "config_save",
            detail=f"user={request.username};keys={','.join(changed)}",
        )
        return json_response({"saved": True, "changed": changed})

    def _normalize_ids(self, raw: Any) -> set[str]:
        """支持完整 uuid，或顺序编号（会解析成对应 uuid）。"""
        ids: set[str] = set()
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            return ids
        index = self._load_index()
        seq_map = {
            int(v.get("seq") or 0): str(v.get("id"))
            for v in index.get("videos", [])
            if isinstance(v, dict) and int(v.get("seq") or 0) > 0
        }
        for item in raw:
            text = str(item).strip()
            if SAFE_ID_RE.match(text):
                ids.add(text)
            elif text.isdigit():
                mapped = seq_map.get(int(text))
                if mapped:
                    ids.add(mapped)
        return ids

    def _public_item(self, item: dict[str, Any]) -> dict[str, Any]:
        path = self.videos_dir / str(item.get("filename", ""))
        exists = path.is_file()
        size = int(item.get("size") or 0)
        if exists:
            try:
                size = path.stat().st_size
            except OSError:
                pass
        seq = int(item.get("seq") or 0)
        return {
            "id": item.get("id"),
            "seq": seq,
            "id_short": str(seq) if seq > 0 else str(item.get("id") or "")[:8],
            "filename": item.get("filename"),
            "saved_at": item.get("saved_at"),
            "saved_at_human": self._fmt_time(item.get("saved_at")),
            "source_message_id": item.get("source_message_id") or "",
            "source_group_id": item.get("source_group_id") or "",
            "collector_id": item.get("collector_id") or "",
            "collector_name": item.get("collector_name") or "",
            "size": size,
            "size_human": self._fmt_size(size),
            "note": item.get("note") or "",
            "tags": item.get("tags") or list(DEFAULT_TAGS),
            "play_count": int(item.get("play_count") or 0),
            "last_played_at": item.get("last_played_at"),
            "last_played_at_human": self._fmt_time(item.get("last_played_at")) or "",
            "pinned": bool(item.get("pinned")),
            "deleted_at": item.get("deleted_at"),
            "deleted_at_human": self._fmt_time(item.get("deleted_at")) or "",
            "deleted_by": item.get("deleted_by") or "",
            "file_exists": exists,
            "in_trash": item.get("deleted_at") is not None,
            "can_preview": exists and size <= PREVIEW_MAX_BYTES,
        }

    # ------------------------------------------------------------------
    # 指令（可配置文案）
    # ------------------------------------------------------------------

    def _cmd_aliases(self, key: str, default: str) -> list[str]:
        raw = str(self.config.get(key) or default)
        parts = [p.strip() for p in re.split(r"[,，]", raw) if p.strip()]
        return parts or [x.strip() for x in default.split(",") if x.strip()]

    def _match_cmd(self, text: str, key: str, default: str) -> tuple[bool, str]:
        """返回 (是否匹配, 去掉指令后的参数)。支持全等或「指令 + 空格 + 参数」。"""
        msg = (text or "").strip()
        if not msg:
            return False, ""
        aliases = sorted(self._cmd_aliases(key, default), key=len, reverse=True)
        for alias in aliases:
            if msg == alias:
                return True, ""
            prefix = alias + " "
            if msg.startswith(prefix):
                return True, msg[len(prefix) :].strip()
        return False, ""

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_tiancai_commands(self, event: AstrMessageEvent):
        text = (event.message_str or "").strip()
        if not text:
            return

        ok, _ = self._match_cmd(text, "cmd_collect", "收进天菜,加入天菜,天菜入库")
        if ok:
            async for r in self.collect_tiancai(event):
                yield r
            event.stop_event()
            return

        ok, _ = self._match_cmd(text, "cmd_show", "看看天菜,来点天菜,天菜")
        if ok:
            async for r in self.show_tiancai(event):
                yield r
            event.stop_event()
            return

        ok, _ = self._match_cmd(text, "cmd_sync", "同步天菜源,天菜同步,同步公共天菜")
        if ok:
            async for r in self.sync_public_cmd(event):
                yield r
            event.stop_event()
            return

        ok, _ = self._match_cmd(text, "cmd_count", "天菜数量,天菜库,天菜列表")
        if ok:
            async for r in self.tiancai_count(event):
                yield r
            event.stop_event()
            return

        ok, arg = self._match_cmd(text, "cmd_delete", "删除天菜,天菜删除")
        if ok:
            async for r in self.delete_tiancai(event, arg):
                yield r
            event.stop_event()
            return

        ok, arg = self._match_cmd(text, "cmd_detail", "天菜详情,天菜信息")
        if ok:
            async for r in self.tiancai_detail(event, arg):
                yield r
            event.stop_event()
            return

        ok, _ = self._match_cmd(text, "cmd_help", "天菜帮助,天菜说明,天菜指令")
        if ok:
            async for r in self.tiancai_help(event):
                yield r
            event.stop_event()
            return

        ok, _ = self._match_cmd(text, "cmd_clear", "清空天菜")
        if ok:
            if not event.is_admin():
                yield event.plain_result("仅管理员可清空天菜库。")
                event.stop_event()
                return
            async for r in self.clear_tiancai(event):
                yield r
            event.stop_event()
            return

    async def collect_tiancai(self, event: AstrMessageEvent):
        """回复一条视频消息后发送本指令，将视频保存到全局天菜库。"""
        collect_name = self._cmd_aliases("cmd_collect", "收进天菜,加入天菜,天菜入库")[0]
        if not self._can_collect(event):
            yield event.plain_result(
                f"你没有入库权限。仅 AstrBot 管理员或白名单用户可「{collect_name}」。"
            )
            return

        video_comp, source_meta = await self._extract_video_from_event(event)
        if video_comp is None:
            yield event.plain_result(
                f"请先回复一条包含视频的消息，再发送「{collect_name}」。"
            )
            return

        allow_duplicate = bool(self.config.get("allow_duplicate", False))
        index = self._load_index()
        source_msg_id = str(source_meta.get("message_id") or "")
        if (
            not allow_duplicate
            and source_msg_id
            and any(
                str(item.get("source_message_id") or "") == source_msg_id
                and item.get("deleted_at") is None
                for item in index.get("videos", [])
            )
        ):
            yield event.plain_result("这条视频已经在天菜库里啦～")
            return

        max_videos = int(self.config.get("max_videos", 0) or 0)
        active_count = len(self._active_videos(index))
        if max_videos > 0 and active_count >= max_videos:
            yield event.plain_result(
                f"天菜库已满（上限 {max_videos} 条），请先清理后再收。"
            )
            return

        try:
            local_path = await video_comp.convert_to_file_path()
        except Exception as exc:  # noqa: BLE001
            logger.exception("下载/定位视频失败")
            yield event.plain_result(f"保存失败：无法获取视频文件（{exc}）")
            return

        src = Path(local_path)
        if not src.exists() or not src.is_file():
            yield event.plain_result("保存失败：找不到视频文件。")
            return

        suffix = src.suffix.lower() or ".mp4"
        if suffix not in VIDEO_SUFFIXES:
            suffix = ".mp4"

        video_id = uuid.uuid4().hex
        dest = self.videos_dir / f"{video_id}{suffix}"
        try:
            shutil.copy2(src, dest)
        except Exception as exc:  # noqa: BLE001
            logger.exception("复制视频到天菜库失败")
            yield event.plain_result(f"保存失败：写入本地目录出错（{exc}）")
            return

        seq = self._next_seq(index)
        record = self._new_record(
            video_id=video_id,
            filename=dest.name,
            size=dest.stat().st_size,
            source_message_id=source_msg_id,
            source_group_id=str(
                source_meta.get("group_id") or event.get_group_id() or ""
            ),
            collector_id=str(event.get_sender_id() or ""),
            collector_name=str(event.get_sender_name() or ""),
            seq=seq,
        )
        index.setdefault("videos", []).append(record)
        index["next_seq"] = seq + 1
        self._save_index(index)
        self._audit(
            "collect",
            event,
            video_id=video_id,
            detail=f"size={record['size']};seq={seq}",
        )

        yield event.plain_result(
            f"已收进天菜！当前在库 {len(self._active_videos(index))} 条。\n"
            f"编号：#{seq}"
        )

    async def show_tiancai(self, event: AstrMessageEvent):
        """从本地/公共天菜库随机发送一条视频（降权少重复）。"""
        cooled = self._check_cooldown(event)
        if cooled is not None:
            yield event.plain_result(cooled)
            return

        mode = self._library_mode()
        if self._public_enabled() and mode in {"public", "mixed"}:
            try:
                await self._sync_public_index(force=False)
            except Exception:  # noqa: BLE001
                logger.exception("抽取前同步公共源失败")

        index = self._load_index()
        local_videos = self._existing_active_videos(index)
        public_videos = self._load_public_videos() if self._public_enabled() else []

        pool: list[tuple[str, dict[str, Any]]] = []
        if mode in {"local", "mixed"}:
            pool.extend(("local", v) for v in local_videos)
        if mode in {"public", "mixed"}:
            pool.extend(("public", v) for v in public_videos)

        show_name = self._cmd_aliases("cmd_show", "看看天菜,来点天菜,天菜")[0]
        collect_name = self._cmd_aliases("cmd_collect", "收进天菜,加入天菜,天菜入库")[0]
        if not pool:
            if mode == "public":
                yield event.plain_result(
                    "公共天菜库还是空的。请检查 public_index_url，或先同步公共菜单。"
                )
            elif mode == "mixed":
                yield event.plain_result(
                    f"本地和公共库都还是空的。可先「{collect_name}」，或配置公共源。"
                )
            else:
                yield event.plain_result(
                    f"天菜库还是空的。回复一条群视频并发送「{collect_name}」先囤一点吧。"
                )
            return

        source, chosen = self._weighted_choice_pool(index, pool)
        try:
            if source == "local":
                path = self.videos_dir / str(chosen["filename"])
                video = Video.fromFileSystem(path=str(path))
                chosen["play_count"] = int(chosen.get("play_count") or 0) + 1
                chosen["last_played_at"] = _now()
                recent = index.setdefault("recent_sent_ids", [])
                recent.insert(0, chosen["id"])
                keep_n = max(
                    int(self.config.get("recent_penalty_count", 8) or 8) * 2, 16
                )
                index["recent_sent_ids"] = recent[:keep_n]
                self._save_index(index)
                self._mark_cooldown(event)
                self._audit("play", event, video_id=str(chosen["id"]))
                yield event.chain_result([video])
                return

            video_comp = await self._resolve_public_video(chosen)
            # 自动入库后，chosen 可能已变成本地条目；刷新 recent
            index = self._load_index()
            recent = index.setdefault("recent_sent_ids", [])
            recent.insert(0, f"public:{chosen.get('id')}")
            keep_n = max(int(self.config.get("recent_penalty_count", 8) or 8) * 2, 16)
            index["recent_sent_ids"] = recent[:keep_n]
            self._save_index(index)
            self._mark_cooldown(event)
            self._audit(
                "play_public",
                event,
                video_id=str(chosen.get("id") or ""),
                detail=f"seq={chosen.get('seq')}",
            )
            yield event.chain_result([video_comp])
        except Exception as exc:  # noqa: BLE001
            logger.exception("发送天菜失败")
            yield event.plain_result(f"发送失败：{exc}")

    async def sync_public_cmd(self, event: AstrMessageEvent):
        """手动同步公共天菜菜单。"""
        if not self._public_enabled():
            yield event.plain_result(
                "公共源未启用。请在设置页打开 public_enabled 并填写 public_index_url。"
            )
            return
        try:
            result = await self._sync_public_index(force=True)
            yield event.plain_result(result.get("message") or "同步完成")
        except Exception as exc:  # noqa: BLE001
            logger.exception("指令同步公共源失败")
            yield event.plain_result(f"同步失败：{exc}")

    async def tiancai_count(self, event: AstrMessageEvent):
        """查看天菜库当前数量。"""
        index = self._load_index()
        active = self._existing_active_videos(index)
        deleted = [
            item
            for item in index.get("videos", [])
            if item.get("deleted_at") is not None
        ]
        pub_n = len(self._load_public_videos()) if self._public_enabled() else 0
        mode = self._library_mode()
        extra = ""
        if self._public_enabled():
            extra = f"\n公共源：{pub_n} 条（模式 {mode}）"
        yield event.plain_result(
            f"天菜库在库 {len(active)} 条，回收站 {len(deleted)} 条。"
            f"{extra}\n目录：{self.videos_dir}"
        )

    async def delete_tiancai(self, event: AstrMessageEvent, code: str = ""):
        """软删除一条天菜。"""
        delete_name = self._cmd_aliases("cmd_delete", "删除天菜,天菜删除")[0]
        code = (code or "").strip().lstrip("#")
        if not code:
            yield event.plain_result(f"用法：{delete_name} <编号>，例如：{delete_name} 3")
            return

        index = self._load_index()
        matches = self._match_videos(self._active_videos(index), code)
        if not matches:
            yield event.plain_result(f"没有找到编号「{code}」的在库天菜。")
            return
        if len(matches) > 1:
            preview = "、".join(
                f"#{m.get('seq')}" for m in matches[:5] if m.get("seq")
            )
            yield event.plain_result(
                f"匹配到 {len(matches)} 条，请使用精确数字编号。\n候选：{preview}"
            )
            return

        item = matches[0]
        sender_id = str(event.get_sender_id() or "")
        if not self._can_delete(event, item):
            yield event.plain_result("你没有权限删除这条天菜（需管理员，或本人收藏）。")
            return

        item["deleted_at"] = _now()
        item["deleted_by"] = sender_id
        self._save_index(index)
        self._audit("soft_delete", event, video_id=str(item["id"]))
        yield event.plain_result(
            f"已将天菜移入回收站。\n编号：#{item.get('seq') or str(item['id'])[:8]}\n"
            "可在 WebUI「天菜管理台」回收站恢复或永久删除。"
        )

    async def tiancai_detail(self, event: AstrMessageEvent, code: str = ""):
        """查看一条天菜的元信息。"""
        detail_name = self._cmd_aliases("cmd_detail", "天菜详情,天菜信息")[0]
        code = (code or "").strip().lstrip("#")
        if not code:
            yield event.plain_result(f"用法：{detail_name} <编号>，例如：{detail_name} 3")
            return

        index = self._load_index()
        matches = self._match_videos(index.get("videos", []), code)
        if not matches:
            yield event.plain_result(f"没有找到编号「{code}」的天菜。")
            return
        if len(matches) > 1:
            preview = "、".join(
                f"#{m.get('seq')}" for m in matches[:5] if m.get("seq")
            )
            yield event.plain_result(
                f"匹配到 {len(matches)} 条，请使用精确数字编号。\n候选：{preview}"
            )
            return

        item = matches[0]
        path = self.videos_dir / str(item.get("filename", ""))
        exists = path.is_file()
        tags = item.get("tags") or []
        tag_text = "、".join(str(t) for t in tags) if tags else "（无）"
        status = "回收站" if item.get("deleted_at") else ("在库" if exists else "文件缺失")
        saved_at = self._fmt_time(item.get("saved_at"))
        last_played = self._fmt_time(item.get("last_played_at")) or "尚未抽出"
        yield event.plain_result(
            "天菜详情\n"
            f"编号：#{item.get('seq') or '-'}\n"
            f"内部ID：{item.get('id')}\n"
            f"状态：{status}\n"
            f"大小：{self._fmt_size(item.get('size'))}\n"
            f"入库：{saved_at}\n"
            f"收藏人：{item.get('collector_name') or '-'} ({item.get('collector_id') or '-'})\n"
            f"来源群：{item.get('source_group_id') or '-'}\n"
            f"备注：{item.get('note') or '（无）'}\n"
            f"标签：{tag_text}\n"
            f"置顶：{'是' if item.get('pinned') else '否'}\n"
            f"抽中次数：{int(item.get('play_count') or 0)}\n"
            f"最近抽出：{last_played}"
        )

    async def tiancai_help(self, event: AstrMessageEvent):
        """查看天菜插件指令说明。"""
        c = lambda k, d: " / ".join(self._cmd_aliases(k, d))
        yield event.plain_result(
            "天菜视频库指令（可在设置页自定义）\n"
            f"· {c('cmd_collect', '收进天菜,加入天菜,天菜入库')}：回复视频后入库\n"
            f"· {c('cmd_show', '看看天菜,来点天菜,天菜')}：随机发一条\n"
            f"· {c('cmd_sync', '同步天菜源,天菜同步,同步公共天菜')}：同步公共菜单\n"
            f"· {c('cmd_count', '天菜数量,天菜库,天菜列表')}：查看数量\n"
            f"· {c('cmd_delete', '删除天菜,天菜删除')} <编号>：移入回收站\n"
            f"· {c('cmd_detail', '天菜详情,天菜信息')} <编号>：查看元信息\n"
            f"· {c('cmd_clear', '清空天菜')}：管理员清空到回收站\n"
            f"· {c('cmd_help', '天菜帮助,天菜说明,天菜指令')}：本说明\n"
            "\n"
            "公共库：配置 Token 后可在管理台发布到你自己的 GitHub 仓库。\n"
            "教程：docs/SETUP_PUBLIC_REPO.md"
        )

    async def clear_tiancai(self, event: AstrMessageEvent):
        """管理员：将全部在库天菜移入回收站（软删除）。"""
        index = self._load_index()
        moved = 0
        sender_id = str(event.get_sender_id() or "")
        for item in index.get("videos", []):
            if item.get("deleted_at") is None:
                item["deleted_at"] = _now()
                item["deleted_by"] = sender_id
                moved += 1
        self._save_index(index)
        self._audit("soft_clear", event, detail=f"moved={moved}")
        yield event.plain_result(
            f"已将 {moved} 条天菜移入回收站（可在 WebUI 管理台恢复/永久删除）。"
        )

    # ------------------------------------------------------------------
    # 权限 / 冷却 / 随机
    # ------------------------------------------------------------------

    def _can_collect(self, event: AstrMessageEvent) -> bool:
        if event.is_admin():
            return True
        sender = str(event.get_sender_id() or "")
        whitelist = set(_as_str_list(self.config.get("collect_whitelist")))
        return sender in whitelist

    def _can_delete(self, event: AstrMessageEvent, item: dict[str, Any]) -> bool:
        if event.is_admin():
            return True
        sender = str(event.get_sender_id() or "")
        return bool(sender) and sender == str(item.get("collector_id") or "")

    def _check_cooldown(self, event: AstrMessageEvent) -> str | None:
        seconds = int(self.config.get("cooldown_seconds", 15) or 0)
        if seconds <= 0 or event.is_admin():
            return None
        key = f"{event.unified_msg_origin}:{event.get_sender_id()}"
        last = self._cooldowns.get(key)
        now = time.time()
        if last is not None and now - last < seconds:
            remain = int(seconds - (now - last)) + 1
            return f"冷却中，请 {remain} 秒后再「看看天菜」。"
        return None

    def _mark_cooldown(self, event: AstrMessageEvent) -> None:
        key = f"{event.unified_msg_origin}:{event.get_sender_id()}"
        self._cooldowns[key] = time.time()

    def _weighted_choice(
        self, index: dict[str, Any], videos: list[dict[str, Any]]
    ) -> dict[str, Any]:
        recent_ids = [
            str(x) for x in (index.get("recent_sent_ids") or []) if x is not None
        ]
        penalty_n = max(int(self.config.get("recent_penalty_count", 8) or 8), 0)
        recent_set = set(recent_ids[:penalty_n])
        recent_weight = float(self.config.get("recent_penalty_weight", 0.15) or 0.15)
        pinned_weight = float(self.config.get("pinned_weight", 3.0) or 3.0)
        if recent_weight < 0:
            recent_weight = 0.0

        weights: list[float] = []
        for item in videos:
            weight = pinned_weight if item.get("pinned") else 1.0
            if str(item.get("id")) in recent_set:
                weight *= recent_weight
            weights.append(max(weight, 0.0001))

        return random.choices(videos, weights=weights, k=1)[0]

    def _weighted_choice_pool(
        self,
        index: dict[str, Any],
        pool: list[tuple[str, dict[str, Any]]],
    ) -> tuple[str, dict[str, Any]]:
        recent_ids = [
            str(x) for x in (index.get("recent_sent_ids") or []) if x is not None
        ]
        penalty_n = max(int(self.config.get("recent_penalty_count", 8) or 8), 0)
        recent_set = set(recent_ids[:penalty_n])
        recent_weight = float(self.config.get("recent_penalty_weight", 0.15) or 0.15)
        pinned_weight = float(self.config.get("pinned_weight", 3.0) or 3.0)
        public_weight = float(self.config.get("public_weight", 1.0) or 1.0)
        if recent_weight < 0:
            recent_weight = 0.0
        if public_weight <= 0:
            public_weight = 0.0001

        weights: list[float] = []
        for source, item in pool:
            weight = pinned_weight if item.get("pinned") else 1.0
            if source == "public":
                weight *= public_weight
                rid = f"public:{item.get('id')}"
            else:
                rid = str(item.get("id"))
            if rid in recent_set:
                weight *= recent_weight
            weights.append(max(weight, 0.0001))

        return random.choices(pool, weights=weights, k=1)[0]

    # ------------------------------------------------------------------
    # 公共天菜源
    # ------------------------------------------------------------------

    def _public_enabled(self) -> bool:
        # 默认启用；仅当显式关闭时禁用
        if "public_enabled" not in self.config:
            enabled = True
        else:
            enabled = bool(self.config.get("public_enabled", True))
        if not enabled:
            return False
        url = str(self.config.get("public_index_url") or DEFAULT_PUBLIC_INDEX_URL).strip()
        return url.startswith("http://") or url.startswith("https://")

    def _library_mode(self) -> str:
        mode = str(self.config.get("library_mode") or "mixed").strip().lower()
        if mode not in {"local", "public", "mixed"}:
            return "mixed"
        if mode in {"public", "mixed"} and not self._public_enabled():
            return "local"
        return mode

    def _public_status_dict(self) -> dict[str, Any]:
        meta = self._load_public_meta()
        videos = self._load_public_videos() if self.public_index_path.exists() else []
        return {
            "enabled": self._public_enabled(),
            "mode": self._library_mode(),
            "index_url": str(
                self.config.get("public_index_url") or DEFAULT_PUBLIC_INDEX_URL
            ),
            "auto_import": bool(self.config.get("public_auto_import", True)),
            "sync_hours": float(self.config.get("public_sync_hours", 12) or 12),
            "public_count": len(videos),
            "last_sync_at": meta.get("last_sync_at"),
            "last_sync_at_human": self._fmt_time(meta.get("last_sync_at")) or "",
            "last_error": meta.get("last_error") or "",
            "name": meta.get("name") or "",
            "proxy": self._github_proxy_prefix(),
            "repo": str(self.config.get("github_repo") or ""),
            "token_configured": bool(str(self.config.get("github_token") or "").strip()),
        }

    def _load_public_meta(self) -> dict[str, Any]:
        if not self.public_meta_path.exists():
            return {}
        try:
            data = json.loads(self.public_meta_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def _save_public_meta(self, data: dict[str, Any]) -> None:
        self.public_meta_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_public_videos(self) -> list[dict[str, Any]]:
        if not self.public_index_path.exists():
            return []
        try:
            data = json.loads(self.public_index_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logger.exception("读取公共菜单缓存失败")
            return []
        videos = data.get("videos", []) if isinstance(data, dict) else []
        out: list[dict[str, Any]] = []
        if not isinstance(videos, list):
            return out
        for raw in videos:
            if not isinstance(raw, dict):
                continue
            url = str(raw.get("url") or "").strip()
            vid = str(raw.get("id") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            if not vid or not PUBLIC_ID_RE.match(vid):
                continue
            item = dict(raw)
            item["id"] = vid
            item["url"] = url
            item["source"] = "public"
            tags = item.get("tags")
            if not isinstance(tags, list) or not tags:
                item["tags"] = list(DEFAULT_TAGS)
            try:
                item["seq"] = int(item.get("seq") or 0)
            except (TypeError, ValueError):
                item["seq"] = 0
            out.append(item)
        return out

    async def _sync_public_index(self, *, force: bool = False) -> dict[str, Any]:
        if not self._public_enabled():
            return {"ok": False, "message": "公共源未启用"}

        async with self._public_sync_lock:
            meta = self._load_public_meta()
            sync_hours = float(self.config.get("public_sync_hours", 12) or 12)
            last = int(meta.get("last_sync_at") or 0)
            now = _now()
            if (
                not force
                and sync_hours > 0
                and last
                and now - last < sync_hours * 3600
                and self.public_index_path.exists()
            ):
                return {
                    "ok": True,
                    "skipped": True,
                    "message": (
                        f"距上次同步不足 {sync_hours} 小时，已跳过。"
                        f"公共条目 {len(self._load_public_videos())} 条。"
                    ),
                }

            url = str(
                self.config.get("public_index_url") or DEFAULT_PUBLIC_INDEX_URL
            ).strip()
            fetch_url = self._with_github_proxy(url)
            try:
                text = await asyncio.to_thread(self._http_get_text, fetch_url)
                data = json.loads(text)
                if not isinstance(data, dict) or not isinstance(
                    data.get("videos"), list
                ):
                    raise ValueError("菜单格式无效：需要包含 videos 数组的 JSON 对象")
                self.public_index_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                count = len(self._load_public_videos())
                meta.update(
                    {
                        "last_sync_at": now,
                        "last_error": "",
                        "name": str(data.get("name") or ""),
                        "source_url": url,
                        "fetch_url": fetch_url,
                        "count": count,
                    }
                )
                self._save_public_meta(meta)
                self._audit("public_sync", detail=f"count={count}")
                return {
                    "ok": True,
                    "skipped": False,
                    "count": count,
                    "message": f"公共菜单同步成功，共 {count} 条。",
                }
            except Exception as exc:  # noqa: BLE001
                meta["last_error"] = str(exc)
                meta["last_sync_attempt_at"] = now
                self._save_public_meta(meta)
                raise

    def _github_proxy_prefix(self) -> str:
        raw = str(self.config.get("github_proxy") or "").strip()
        if not raw:
            raw = DEFAULT_GITHUB_PROXY
        if not raw.endswith("/"):
            raw += "/"
        return raw

    def _with_github_proxy(self, url: str) -> str:
        """对 github / gh 资源拼代理；已是代理地址则原样返回。"""
        u = (url or "").strip()
        if not u.startswith(("http://", "https://")):
            return u
        proxy = self._github_proxy_prefix()
        if u.startswith(proxy):
            return u
        host = (urlparse(u).hostname or "").lower()
        github_hosts = {
            "github.com",
            "raw.githubusercontent.com",
            "objects.githubusercontent.com",
            "codeload.github.com",
            "release-assets.githubusercontent.com",
        }
        if host not in github_hosts and not host.endswith(".githubusercontent.com"):
            return u
        # gh-proxy 常见用法：https://gh-proxy.com/https://raw.githubusercontent.com/...
        return proxy + u

    def _http_get_text(self, url: str, timeout: int = 30, token: str = "") -> str:
        headers = {"User-Agent": "astrbot_plugin_tiancai/1.5"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            headers["Accept"] = "application/vnd.github+json"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        req = Request(url, headers=headers, method="GET")
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")

    def _http_download(self, url: str, dest: Path, timeout: int = 120) -> None:
        fetch_url = self._with_github_proxy(url)
        req = Request(
            fetch_url,
            headers={"User-Agent": "astrbot_plugin_tiancai/1.5"},
            method="GET",
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        with urlopen(req, timeout=timeout) as resp, tmp.open("wb") as fp:  # noqa: S310
            shutil.copyfileobj(resp, fp)
        tmp.replace(dest)

    def _http_json(
        self,
        method: str,
        url: str,
        *,
        token: str,
        data: bytes | None = None,
        content_type: str = "application/json",
        timeout: int = 60,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        headers = {
            "User-Agent": "astrbot_plugin_tiancai/1.5",
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if data is not None:
            headers["Content-Type"] = content_type
        if extra_headers:
            headers.update(extra_headers)
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=timeout) as resp:  # noqa: S310
                raw = resp.read()
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API {method} {url} -> {exc.code}: {body}") from exc

    def _publish_local_ids_to_github(
        self, ids: set[str], token: str
    ) -> dict[str, Any]:
        repo = str(self.config.get("github_repo") or "").strip()
        branch = str(self.config.get("github_branch") or "main").strip() or "main"
        index_path = (
            str(self.config.get("github_index_path") or "public/public_index.json").strip()
            or "public/public_index.json"
        )
        release_tag = (
            str(self.config.get("github_release_tag") or "tiancai-videos").strip()
            or "tiancai-videos"
        )
        max_mb = int(self.config.get("max_public_upload_mb", 95) or 95)
        max_bytes = max(1, max_mb) * 1024 * 1024

        if not re.match(r"^[^/\s]+/[^/\s]+$", repo):
            raise ValueError("github_repo 格式应为 owner/repo")

        index = self._load_index()
        locals_map = {
            str(v.get("id")): v
            for v in index.get("videos", [])
            if isinstance(v, dict) and v.get("deleted_at") is None
        }

        # 读取/创建远程菜单
        remote_index = self._github_get_index_file(repo, branch, index_path, token)
        videos = remote_index.setdefault("videos", [])
        if not isinstance(videos, list):
            videos = []
            remote_index["videos"] = videos
        existing_ids = {
            str(v.get("id"))
            for v in videos
            if isinstance(v, dict) and v.get("id")
        }
        next_seq = 1
        for v in videos:
            if isinstance(v, dict):
                try:
                    next_seq = max(next_seq, int(v.get("seq") or 0) + 1)
                except (TypeError, ValueError):
                    pass

        release = self._github_ensure_release(repo, release_tag, token)
        upload_url_template = str(release.get("upload_url") or "")
        if not upload_url_template:
            raise RuntimeError("无法获取 Release upload_url")
        upload_base = upload_url_template.split("{", 1)[0]

        published: list[dict[str, Any]] = []
        failed: list[dict[str, str]] = []
        skipped: list[dict[str, str]] = []

        for vid in sorted(ids):
            item = locals_map.get(vid)
            if not item:
                failed.append({"id": vid, "error": "本地不存在或已在回收站"})
                continue
            pub_id = f"local_{vid}"
            if pub_id in existing_ids or vid in existing_ids:
                skipped.append({"id": vid, "error": "公共库已存在同来源条目"})
                continue
            path = self.videos_dir / str(item.get("filename") or "")
            if not path.is_file():
                failed.append({"id": vid, "error": "本地文件缺失"})
                continue
            size = path.stat().st_size
            if size > max_bytes:
                failed.append(
                    {
                        "id": vid,
                        "error": f"文件过大 {self._fmt_size(size)} > {max_mb}MB",
                    }
                )
                continue

            suffix = path.suffix.lower() or ".mp4"
            asset_name = f"{pub_id}{suffix}"
            try:
                asset = self._github_upload_release_asset(
                    upload_base, asset_name, path, token
                )
                browser_url = str(
                    asset.get("browser_download_url") or asset.get("url") or ""
                )
                if not browser_url:
                    raise RuntimeError("上传成功但未返回下载地址")
                entry = {
                    "id": pub_id,
                    "seq": next_seq,
                    "title": item.get("note") or f"天菜#{item.get('seq') or ''}",
                    "tags": item.get("tags") or list(DEFAULT_TAGS),
                    "url": browser_url,
                    "size": size,
                    "sha256": self._sha256_file(path),
                    "created_at": _now(),
                    "source_local_id": vid,
                    "source_local_seq": item.get("seq"),
                }
                videos.append(entry)
                existing_ids.add(pub_id)
                next_seq += 1
                published.append(
                    {
                        "id": vid,
                        "public_id": pub_id,
                        "seq": entry["seq"],
                        "url": browser_url,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                failed.append({"id": vid, "error": str(exc)})

        remote_index["version"] = int(remote_index.get("version") or 1)
        remote_index["updated_at"] = _now()
        remote_index.setdefault("name", "天菜公共库")
        remote_index.setdefault(
            "license_note",
            "仅放维护者有权公开分发的内容。用户插件只读同步，不能上传。",
        )
        remote_index["maintainer"] = "sxd55"
        remote_index["videos"] = videos

        if published:
            self._github_put_index_file(
                repo, branch, index_path, remote_index, token
            )
            # 刷新本地公共缓存
            self.public_index_path.write_text(
                json.dumps(remote_index, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return {
            "published": len(published),
            "failed": len(failed),
            "skipped": len(skipped),
            "items": published,
            "errors": failed,
            "skipped_items": skipped,
            "repo": repo,
            "index_path": index_path,
            "release_tag": release_tag,
        }

    def _github_get_index_file(
        self, repo: str, branch: str, path: str, token: str
    ) -> dict[str, Any]:
        api = f"{GITHUB_API}/repos/{repo}/contents/{quote(path)}?ref={quote(branch)}"
        try:
            data = self._http_json("GET", api, token=token)
            content = base64.b64decode(data.get("content") or "").decode("utf-8")
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                raise ValueError("remote index is not object")
            parsed["_sha"] = data.get("sha")
            return parsed
        except RuntimeError as exc:
            if "404" in str(exc):
                return {
                    "version": 1,
                    "updated_at": _now(),
                    "name": "天菜公共库",
                    "videos": [],
                    "_sha": None,
                }
            raise

    def _github_put_index_file(
        self,
        repo: str,
        branch: str,
        path: str,
        index_data: dict[str, Any],
        token: str,
    ) -> None:
        payload_data = {k: v for k, v in index_data.items() if not str(k).startswith("_")}
        body = json.dumps(payload_data, ensure_ascii=False, indent=2).encode("utf-8")
        sha = index_data.get("_sha")
        api = f"{GITHUB_API}/repos/{repo}/contents/{quote(path)}"
        payload = {
            "message": f"chore(tiancai): update public index ({_now()})",
            "content": base64.b64encode(body).decode("ascii"),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        self._http_json(
            "PUT",
            api,
            token=token,
            data=json.dumps(payload).encode("utf-8"),
        )

    def _github_ensure_release(
        self, repo: str, tag: str, token: str
    ) -> dict[str, Any]:
        api_get = f"{GITHUB_API}/repos/{repo}/releases/tags/{quote(tag)}"
        try:
            return self._http_json("GET", api_get, token=token)
        except RuntimeError as exc:
            if "404" not in str(exc):
                raise
        api_create = f"{GITHUB_API}/repos/{repo}/releases"
        payload = {
            "tag_name": tag,
            "name": "Tiancai Public Videos",
            "body": "天菜公共库视频附件（由插件维护者发布，普通用户只读下载）",
            "draft": False,
            "prerelease": False,
        }
        return self._http_json(
            "POST",
            api_create,
            token=token,
            data=json.dumps(payload).encode("utf-8"),
        )

    def _github_upload_release_asset(
        self, upload_base: str, asset_name: str, path: Path, token: str
    ) -> dict[str, Any]:
        # 若同名资产已存在，先删再传
        # upload_base like https://uploads.github.com/repos/../releases/123/assets
        url = f"{upload_base}?name={quote(asset_name)}"
        data = path.read_bytes()
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        headers = {
            "User-Agent": "astrbot_plugin_tiancai/1.5",
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": mime,
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Length": str(len(data)),
        }
        req = Request(url, data=data, headers=headers, method="POST")
        try:
            with urlopen(req, timeout=300) as resp:  # noqa: S310
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            # 已存在则尝试删除后重传
            if exc.code in {422, 409} or "already_exists" in body:
                self._github_delete_release_asset_by_name(
                    upload_base, asset_name, token
                )
                req2 = Request(url, data=data, headers=headers, method="POST")
                with urlopen(req2, timeout=300) as resp2:  # noqa: S310
                    return json.loads(resp2.read().decode("utf-8"))
            raise RuntimeError(f"上传资产失败 {exc.code}: {body}") from exc

    def _github_delete_release_asset_by_name(
        self, upload_base: str, asset_name: str, token: str
    ) -> None:
        # upload_base: https://uploads.github.com/repos/{owner}/{repo}/releases/{id}/assets
        parts = urlparse(upload_base).path.strip("/").split("/")
        # repos / owner / repo / releases / id / assets
        if len(parts) < 6:
            return
        owner, repo, release_id = parts[1], parts[2], parts[4]
        api = f"{GITHUB_API}/repos/{owner}/{repo}/releases/{release_id}/assets"
        assets = self._http_json("GET", api, token=token)
        if not isinstance(assets, list):
            return
        for asset in assets:
            if str(asset.get("name")) == asset_name:
                asset_id = asset.get("id")
                if asset_id:
                    del_api = (
                        f"{GITHUB_API}/repos/{owner}/{repo}/releases/assets/{asset_id}"
                    )
                    self._http_json("DELETE", del_api, token=token)

    @staticmethod
    def _sha256_file(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fp:
            for chunk in iter(lambda: fp.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    async def _resolve_public_video(self, item: dict[str, Any]) -> Video:
        url = str(item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("公共条目缺少有效 url")

        auto_import = bool(self.config.get("public_auto_import", True))
        vid = str(item.get("id") or "unknown")
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix not in VIDEO_SUFFIXES:
            suffix = ".mp4"

        # 已导入过同一公共 id？
        index = self._load_index()
        for local in index.get("videos", []):
            if (
                isinstance(local, dict)
                and local.get("deleted_at") is None
                and str(local.get("source_public_id") or "") == vid
            ):
                path = self.videos_dir / str(local.get("filename") or "")
                if path.is_file():
                    local["play_count"] = int(local.get("play_count") or 0) + 1
                    local["last_played_at"] = _now()
                    self._save_index(index)
                    return Video.fromFileSystem(path=str(path))

        cache_path = self.public_cache_dir / f"{vid}{suffix}"
        if not (cache_path.is_file() and cache_path.stat().st_size > 0):
            await asyncio.to_thread(self._http_download, url, cache_path)
        if not (cache_path.is_file() and cache_path.stat().st_size > 0):
            # 回退 URL 发送
            return Video.fromURL(url=self._with_github_proxy(url))

        if auto_import:
            imported = self._import_cached_public_video(item, cache_path)
            if imported is not None:
                path = self.videos_dir / str(imported.get("filename") or "")
                if path.is_file():
                    return Video.fromFileSystem(path=str(path))

        return Video.fromFileSystem(path=str(cache_path))

    def _import_cached_public_video(
        self, public_item: dict[str, Any], cache_path: Path
    ) -> dict[str, Any] | None:
        """把已下载的公共视频写入本地库。"""
        try:
            index = self._load_index()
            pub_id = str(public_item.get("id") or "")
            for local in index.get("videos", []):
                if (
                    isinstance(local, dict)
                    and local.get("deleted_at") is None
                    and str(local.get("source_public_id") or "") == pub_id
                ):
                    return local

            max_videos = int(self.config.get("max_videos", 0) or 0)
            if max_videos > 0 and len(self._active_videos(index)) >= max_videos:
                logger.warning("本地库已满，跳过公共视频自动导入")
                return None

            suffix = cache_path.suffix.lower() or ".mp4"
            video_id = uuid.uuid4().hex
            dest = self.videos_dir / f"{video_id}{suffix}"
            shutil.copy2(cache_path, dest)
            seq = self._next_seq(index)
            record = self._new_record(
                video_id=video_id,
                filename=dest.name,
                size=dest.stat().st_size,
                source_message_id="",
                source_group_id="",
                collector_id="public-import",
                collector_name="公共源自动导入",
                seq=seq,
            )
            record["source_public_id"] = pub_id
            record["note"] = str(public_item.get("title") or f"公共#{public_item.get('seq') or ''}")[
                :200
            ]
            tags = public_item.get("tags")
            if isinstance(tags, list) and tags:
                record["tags"] = [str(t)[:32] for t in tags][:20]
            record["play_count"] = 1
            record["last_played_at"] = _now()
            index.setdefault("videos", []).append(record)
            index["next_seq"] = seq + 1
            self._save_index(index)
            self._audit(
                "public_auto_import",
                video_id=video_id,
                detail=f"public_id={pub_id};seq={seq}",
            )
            return record
        except Exception:  # noqa: BLE001
            logger.exception("公共视频自动导入失败")
            return None

    # ------------------------------------------------------------------
    # 视频提取
    # ------------------------------------------------------------------

    async def _extract_video_from_event(
        self, event: AstrMessageEvent
    ) -> tuple[Video | None, dict[str, Any]]:
        messages = event.get_messages() or []

        for comp in messages:
            if isinstance(comp, Reply):
                video = self._find_video_in_chain(comp.chain or [])
                if video is not None:
                    return video, {
                        "message_id": comp.id,
                        "group_id": event.get_group_id(),
                    }

                fetched = await self._fetch_video_by_message_id(event, str(comp.id))
                if fetched is not None:
                    return fetched, {
                        "message_id": comp.id,
                        "group_id": event.get_group_id(),
                    }

        video = self._find_video_in_chain(messages)
        if video is not None:
            return video, {
                "message_id": getattr(event.message_obj, "message_id", ""),
                "group_id": event.get_group_id(),
            }

        return None, {}

    def _find_video_in_chain(self, chain: list[Any]) -> Video | None:
        for comp in chain or []:
            if isinstance(comp, Video):
                return comp
            if isinstance(comp, File):
                name = (comp.name or "").lower()
                url = (comp.url or "").lower()
                file_hint = (comp.file_ or "").lower()
                if any(
                    hint.endswith(suffix) or suffix in hint
                    for hint in (name, url, file_hint)
                    for suffix in VIDEO_SUFFIXES
                ):
                    source = comp.url or comp.file_ or ""
                    if source.startswith("http://") or source.startswith("https://"):
                        return Video.fromURL(url=source)
                    if source:
                        return Video.fromFileSystem(path=source)
        return None

    async def _fetch_video_by_message_id(
        self, event: AstrMessageEvent, message_id: str
    ) -> Video | None:
        if not message_id:
            return None

        client = getattr(event, "bot", None) or getattr(event, "client", None)
        if client is None:
            return None

        raw = None
        for method_name in ("get_msg", "get_message"):
            method = getattr(client, method_name, None)
            if method is None:
                continue
            try:
                raw = await method(message_id=int(message_id))
            except Exception:  # noqa: BLE001
                try:
                    raw = await method(message_id=message_id)
                except Exception:  # noqa: BLE001
                    logger.debug("通过 %s 拉取消息失败: %s", method_name, message_id)
                    continue
            break

        if raw is None:
            return None

        payload = raw.get("data", raw) if isinstance(raw, dict) else {}
        segments = payload.get("message") if isinstance(payload, dict) else None
        if isinstance(segments, str):
            return self._video_from_cq_code(segments)
        if not isinstance(segments, list):
            return None

        for seg in segments:
            if not isinstance(seg, dict):
                continue
            seg_type = str(seg.get("type", "")).lower()
            data = seg.get("data") or {}
            if seg_type == "video":
                file_val = data.get("file") or data.get("url") or ""
                url = data.get("url") or ""
                if isinstance(url, str) and url.startswith(("http://", "https://")):
                    return Video.fromURL(url=url)
                if isinstance(file_val, str) and file_val.startswith(
                    ("http://", "https://")
                ):
                    return Video.fromURL(url=file_val)
                if isinstance(file_val, str) and file_val:
                    return Video(
                        file=file_val, url=url or "", path=data.get("path") or ""
                    )
            if seg_type == "file":
                name = str(data.get("name") or "").lower()
                url = str(data.get("url") or "")
                file_val = str(data.get("file") or "")
                if any(name.endswith(s) for s in VIDEO_SUFFIXES) or any(
                    file_val.lower().endswith(s) for s in VIDEO_SUFFIXES
                ):
                    if url.startswith(("http://", "https://")):
                        return Video.fromURL(url=url)
                    if file_val.startswith(("http://", "https://")):
                        return Video.fromURL(url=file_val)
                    if file_val:
                        return Video.fromFileSystem(path=file_val)
        return None

    def _video_from_cq_code(self, cq: str) -> Video | None:
        if "CQ:video" not in cq and "CQ:file" not in cq:
            return None
        url = ""
        file_val = ""
        for part in cq.replace("]", "").split(","):
            if part.startswith("url="):
                url = part[4:]
            elif part.startswith("file="):
                file_val = part[5:]
        if url.startswith(("http://", "https://")):
            return Video.fromURL(url=url)
        if file_val.startswith(("http://", "https://")):
            return Video.fromURL(url=file_val)
        if file_val:
            return Video(file=file_val, url=url)
        return None

    # ------------------------------------------------------------------
    # 索引 / 审计
    # ------------------------------------------------------------------

    def _new_record(
        self,
        *,
        video_id: str,
        filename: str,
        size: int,
        source_message_id: str,
        source_group_id: str,
        collector_id: str,
        collector_name: str,
        seq: int,
    ) -> dict[str, Any]:
        return {
            "id": video_id,
            "seq": int(seq),
            "filename": filename,
            "saved_at": _now(),
            "source_message_id": source_message_id,
            "source_group_id": source_group_id,
            "collector_id": collector_id,
            "collector_name": collector_name,
            "size": size,
            "note": "",
            "tags": list(DEFAULT_TAGS),
            "play_count": 0,
            "last_played_at": None,
            "pinned": False,
            "deleted_at": None,
            "deleted_by": None,
            "sha256": None,
        }

    def _next_seq(self, index: dict[str, Any]) -> int:
        try:
            nxt = int(index.get("next_seq") or 0)
        except (TypeError, ValueError):
            nxt = 0
        if nxt <= 0:
            max_seq = 0
            for item in index.get("videos", []):
                try:
                    max_seq = max(max_seq, int(item.get("seq") or 0))
                except (TypeError, ValueError):
                    pass
            nxt = max_seq + 1
        return nxt

    def _match_videos(
        self, videos: list[dict[str, Any]], code: str
    ) -> list[dict[str, Any]]:
        code = (code or "").strip().lstrip("#")
        if not code:
            return []
        # 优先精确匹配顺序编号
        if code.isdigit():
            seq = int(code)
            exact = [v for v in videos if int(v.get("seq") or 0) == seq]
            if exact:
                return exact
        code_l = code.lower()
        return [
            v
            for v in videos
            if str(v.get("id") or "").lower().startswith(code_l)
            or str(v.get("seq") or "") == code
        ]

    def _ensure_index(self) -> None:
        if not self.index_path.exists():
            self._save_index(self._empty_index())
            return
        self._load_index()

    def _empty_index(self) -> dict[str, Any]:
        return {
            "version": INDEX_VERSION,
            "videos": [],
            "recent_sent_ids": [],
            "next_seq": 1,
        }

    def _migrate_index(self, data: dict[str, Any]) -> dict[str, Any]:
        version = int(data.get("version") or 1)
        videos_in = data.get("videos", [])
        if not isinstance(videos_in, list):
            videos_in = []

        # 按入库时间排序后分配缺失的 seq，保证旧数据从 1 连续编号
        prepared: list[dict[str, Any]] = []
        for raw in videos_in:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            item.setdefault("id", uuid.uuid4().hex)
            item.setdefault("filename", "")
            item.setdefault("saved_at", _now())
            item.setdefault("source_message_id", "")
            item.setdefault("source_group_id", "")
            item.setdefault("collector_id", "")
            item.setdefault("collector_name", "")
            item.setdefault("size", 0)
            item.setdefault("note", "")
            tags = item.get("tags")
            if not isinstance(tags, list) or not tags:
                item["tags"] = list(DEFAULT_TAGS)
            item.setdefault("play_count", 0)
            item.setdefault("last_played_at", None)
            item.setdefault("pinned", False)
            item.setdefault("deleted_at", None)
            item.setdefault("deleted_by", None)
            item.setdefault("sha256", None)
            prepared.append(item)

        prepared.sort(key=lambda x: (int(x.get("saved_at") or 0), str(x.get("id"))))
        used_seqs: set[int] = set()
        for item in prepared:
            try:
                seq_val = int(item.get("seq") or 0)
            except (TypeError, ValueError):
                seq_val = 0
            if seq_val > 0 and seq_val not in used_seqs:
                item["seq"] = seq_val
                used_seqs.add(seq_val)
            else:
                item["seq"] = 0

        next_free = 1
        for item in prepared:
            if int(item.get("seq") or 0) > 0:
                continue
            while next_free in used_seqs:
                next_free += 1
            item["seq"] = next_free
            used_seqs.add(next_free)
            next_free += 1

        max_seq = max(used_seqs) if used_seqs else 0
        try:
            next_seq = int(data.get("next_seq") or 0)
        except (TypeError, ValueError):
            next_seq = 0
        if next_seq <= max_seq:
            next_seq = max_seq + 1

        migrated = {
            "version": INDEX_VERSION,
            "videos": prepared,
            "recent_sent_ids": [
                str(x)
                for x in (data.get("recent_sent_ids") or [])
                if x is not None
            ],
            "next_seq": next_seq,
        }
        need_save = version < INDEX_VERSION or any(
            not raw.get("seq") for raw in videos_in if isinstance(raw, dict)
        )
        if need_save:
            logger.info("天菜索引已迁移到 v%s（含顺序编号）", INDEX_VERSION)
            self._save_index(migrated)
        return migrated

    def _load_index(self) -> dict[str, Any]:
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return self._empty_index()
            return self._migrate_index(data)
        except Exception:  # noqa: BLE001
            logger.exception("读取天菜索引失败，将重置")
            return self._empty_index()

    def _save_index(self, data: dict[str, Any]) -> None:
        payload = dict(data)
        payload["version"] = INDEX_VERSION
        if "videos" not in payload or not isinstance(payload["videos"], list):
            payload["videos"] = []
        if "recent_sent_ids" not in payload or not isinstance(
            payload["recent_sent_ids"], list
        ):
            payload["recent_sent_ids"] = []
        if "next_seq" not in payload:
            payload["next_seq"] = self._next_seq(payload)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.index_path)

    def _active_videos(self, index: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            item
            for item in index.get("videos", [])
            if isinstance(item, dict) and item.get("deleted_at") is None
        ]

    def _existing_active_videos(self, index: dict[str, Any]) -> list[dict[str, Any]]:
        existing: list[dict[str, Any]] = []
        changed = False
        for item in list(index.get("videos", [])):
            if item.get("deleted_at") is not None:
                continue
            path = self.videos_dir / str(item.get("filename", ""))
            if path.is_file():
                existing.append(item)
            else:
                item["deleted_at"] = _now()
                item["deleted_by"] = "system:missing_file"
                changed = True
                logger.warning("天菜文件缺失，已移入回收站: %s", item.get("id"))
        if changed:
            self._save_index(index)
        return existing

    def _audit(
        self,
        action: str,
        event: AstrMessageEvent | None = None,
        *,
        video_id: str = "",
        detail: str = "",
    ) -> None:
        try:
            sender = ""
            group = ""
            if event is not None:
                sender = str(event.get_sender_id() or "")
                group = str(event.get_group_id() or "")
            line = (
                f"{_now()}\t{action}\tuser={sender}\tgroup={group}\t"
                f"video={video_id}\t{detail}\n"
            )
            with self.log_path.open("a", encoding="utf-8") as fp:
                fp.write(line)
        except Exception:  # noqa: BLE001
            logger.exception("写入审计日志失败")

    @staticmethod
    def _fmt_size(size: Any) -> str:
        try:
            n = float(size or 0)
        except (TypeError, ValueError):
            return "-"
        units = ["B", "KB", "MB", "GB"]
        idx = 0
        while n >= 1024 and idx < len(units) - 1:
            n /= 1024
            idx += 1
        return f"{n:.1f} {units[idx]}"

    @staticmethod
    def _fmt_time(ts: Any) -> str:
        try:
            value = int(ts)
        except (TypeError, ValueError):
            return ""
        if value <= 0:
            return ""
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))

    async def terminate(self):
        logger.info("天菜视频库插件已卸载")
