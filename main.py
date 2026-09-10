"""AstrBot 天菜视频库插件。

Batch 1：索引 v2、权限白名单、冷却、软删除指令、降权随机
Batch 2：WebUI 管理台（总览 / 列表 / 回收站 / 上传下载）
"""

from __future__ import annotations

import json
import random
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

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
INDEX_VERSION = 2
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv"}
SAFE_ID_RE = re.compile(r"^[a-fA-F0-9]{8,64}$")


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
    "1.2.0",
)
class TiancaiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        self.data_dir = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        self.videos_dir = self.data_dir / str(
            self.config.get("storage_subdir", "videos") or "videos"
        )
        self.index_path = self.data_dir / INDEX_FILENAME
        self.log_path = self.data_dir / LOG_FILENAME
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.videos_dir.mkdir(parents=True, exist_ok=True)
        self._cooldowns: dict[str, float] = {}
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
            ("logs", self.api_logs, ["GET"], "审计日志"),
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
                blob = " ".join(
                    [
                        str(v.get("id") or ""),
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
        if not video_id or not SAFE_ID_RE.match(video_id):
            return error_response("invalid id", status_code=400)

        index = self._load_index()
        target = None
        for item in index.get("videos", []):
            if str(item.get("id")) == video_id:
                target = item
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
        record = self._new_record(
            video_id=video_id,
            filename=dest.name,
            size=size,
            source_message_id="",
            source_group_id="",
            collector_id=f"web:{request.username or 'dashboard'}",
            collector_name=str(request.username or "dashboard"),
        )
        record["note"] = f"WebUI 上传 · {filename}"[:200]
        index.setdefault("videos", []).append(record)
        self._save_index(index)
        self._audit(
            "web_upload",
            video_id=video_id,
            detail=f"name={filename};size={size};by={request.username}",
        )
        return json_response({"item": self._public_item(record)})

    async def api_download_video(self):
        video_id = str(request.query.get("id", "") or "").strip()
        if not video_id or not SAFE_ID_RE.match(video_id):
            return error_response("invalid id", status_code=400)

        index = self._load_index()
        target = None
        for item in index.get("videos", []):
            if str(item.get("id")) == video_id:
                target = item
                break
        if target is None:
            return error_response("not found", status_code=404)

        path = self.videos_dir / str(target.get("filename", ""))
        if not path.is_file():
            return error_response("file missing", status_code=404)

        name = f"tiancai_{video_id[:8]}{path.suffix or '.mp4'}"
        return file_response(path, filename=name, content_type="video/mp4")

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

    def _normalize_ids(self, raw: Any) -> set[str]:
        ids: set[str] = set()
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            return ids
        for item in raw:
            text = str(item).strip()
            if SAFE_ID_RE.match(text):
                ids.add(text)
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
        return {
            "id": item.get("id"),
            "id_short": str(item.get("id") or "")[:8],
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
            "tags": item.get("tags") or [],
            "play_count": int(item.get("play_count") or 0),
            "last_played_at": item.get("last_played_at"),
            "last_played_at_human": self._fmt_time(item.get("last_played_at")) or "",
            "pinned": bool(item.get("pinned")),
            "deleted_at": item.get("deleted_at"),
            "deleted_at_human": self._fmt_time(item.get("deleted_at")) or "",
            "deleted_by": item.get("deleted_by") or "",
            "file_exists": exists,
            "in_trash": item.get("deleted_at") is not None,
        }

    # ------------------------------------------------------------------
    # 指令
    # ------------------------------------------------------------------

    @filter.command("收进天菜", alias={"加入天菜", "天菜入库"})
    async def collect_tiancai(self, event: AstrMessageEvent):
        """回复一条视频消息后发送本指令，将视频保存到全局天菜库。"""
        if not self._can_collect(event):
            yield event.plain_result(
                "你没有入库权限。仅 AstrBot 管理员或白名单用户可「收进天菜」。"
            )
            return

        video_comp, source_meta = await self._extract_video_from_event(event)
        if video_comp is None:
            yield event.plain_result(
                "请先回复一条包含视频的消息，再发送「收进天菜」。"
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
        )
        index.setdefault("videos", []).append(record)
        self._save_index(index)
        self._audit(
            "collect",
            event,
            video_id=video_id,
            detail=f"size={record['size']}",
        )

        yield event.plain_result(
            f"已收进天菜！当前在库 {len(self._active_videos(index))} 条。\n"
            f"编号：{video_id[:8]}"
        )

    @filter.command("看看天菜", alias={"来点天菜", "天菜"})
    async def show_tiancai(self, event: AstrMessageEvent):
        """从全局天菜库随机发送一条视频（降权少重复）。"""
        cooled = self._check_cooldown(event)
        if cooled is not None:
            yield event.plain_result(cooled)
            return

        index = self._load_index()
        videos = self._existing_active_videos(index)
        if not videos:
            yield event.plain_result(
                "天菜库还是空的。回复一条群视频并发送「收进天菜」先囤一点吧。"
            )
            return

        chosen = self._weighted_choice(index, videos)
        path = self.videos_dir / str(chosen["filename"])
        video = Video.fromFileSystem(path=str(path))

        chosen["play_count"] = int(chosen.get("play_count") or 0) + 1
        chosen["last_played_at"] = _now()
        recent = index.setdefault("recent_sent_ids", [])
        recent.insert(0, chosen["id"])
        keep_n = max(int(self.config.get("recent_penalty_count", 8) or 8) * 2, 16)
        index["recent_sent_ids"] = recent[:keep_n]
        self._save_index(index)
        self._mark_cooldown(event)
        self._audit("play", event, video_id=str(chosen["id"]))

        yield event.chain_result([video])

    @filter.command("天菜数量", alias={"天菜库", "天菜列表"})
    async def tiancai_count(self, event: AstrMessageEvent):
        """查看天菜库当前数量。"""
        index = self._load_index()
        active = self._existing_active_videos(index)
        deleted = [
            item
            for item in index.get("videos", [])
            if item.get("deleted_at") is not None
        ]
        yield event.plain_result(
            f"天菜库在库 {len(active)} 条，回收站 {len(deleted)} 条。\n"
            f"目录：{self.videos_dir}"
        )

    @filter.command("删除天菜", alias={"天菜删除"})
    async def delete_tiancai(self, event: AstrMessageEvent, code: str = ""):
        """软删除一条天菜。用法：删除天菜 <编号前缀>"""
        code = (code or "").strip().lower()
        if not code:
            yield event.plain_result("用法：删除天菜 <编号前缀>，例如：删除天菜 ab12cd34")
            return

        index = self._load_index()
        matches = [
            item
            for item in self._active_videos(index)
            if str(item.get("id", "")).lower().startswith(code)
        ]
        if not matches:
            yield event.plain_result(f"没有找到编号以「{code}」开头的在库天菜。")
            return
        if len(matches) > 1:
            preview = "、".join(str(m["id"])[:8] for m in matches[:5])
            yield event.plain_result(
                f"匹配到 {len(matches)} 条，请把编号写得更完整一些。\n候选：{preview}"
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
            f"已将天菜移入回收站。\n编号：{str(item['id'])[:8]}\n"
            "可在 WebUI「天菜管理台」回收站恢复或永久删除。"
        )

    @filter.command("天菜详情", alias={"天菜信息"})
    async def tiancai_detail(self, event: AstrMessageEvent, code: str = ""):
        """查看一条天菜的元信息。用法：天菜详情 <编号前缀>"""
        code = (code or "").strip().lower()
        if not code:
            yield event.plain_result("用法：天菜详情 <编号前缀>")
            return

        index = self._load_index()
        matches = [
            item
            for item in index.get("videos", [])
            if str(item.get("id", "")).lower().startswith(code)
        ]
        if not matches:
            yield event.plain_result(f"没有找到编号以「{code}」开头的天菜。")
            return
        if len(matches) > 1:
            preview = "、".join(str(m["id"])[:8] for m in matches[:5])
            yield event.plain_result(
                f"匹配到 {len(matches)} 条，请把编号写得更完整。\n候选：{preview}"
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
            f"编号：{item.get('id')}\n"
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

    @filter.command("天菜帮助", alias={"天菜说明", "天菜指令"})
    async def tiancai_help(self, event: AstrMessageEvent):
        """查看天菜插件指令说明。"""
        yield event.plain_result(
            "天菜视频库指令\n"
            "· 收进天菜：回复视频后入库（管理员/白名单）\n"
            "· 看看天菜：随机发一条（带冷却，少重复）\n"
            "· 天菜数量：查看在库/回收站数量\n"
            "· 删除天菜 <编号>：移入回收站\n"
            "· 天菜详情 <编号>：查看元信息\n"
            "· 清空天菜：管理员将全部在库移入回收站\n"
            "· 天菜帮助：查看本说明\n"
            "\n"
            "WebUI：插件详情 → 天菜管理台（浏览/上传/回收站）"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("清空天菜")
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
    ) -> dict[str, Any]:
        return {
            "id": video_id,
            "filename": filename,
            "saved_at": _now(),
            "source_message_id": source_message_id,
            "source_group_id": source_group_id,
            "collector_id": collector_id,
            "collector_name": collector_name,
            "size": size,
            "note": "",
            "tags": [],
            "play_count": 0,
            "last_played_at": None,
            "pinned": False,
            "deleted_at": None,
            "deleted_by": None,
            "sha256": None,
        }

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
        }

    def _migrate_index(self, data: dict[str, Any]) -> dict[str, Any]:
        version = int(data.get("version") or 1)
        videos_in = data.get("videos", [])
        if not isinstance(videos_in, list):
            videos_in = []

        videos: list[dict[str, Any]] = []
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
            if not isinstance(tags, list):
                item["tags"] = []
            item.setdefault("play_count", 0)
            item.setdefault("last_played_at", None)
            item.setdefault("pinned", False)
            item.setdefault("deleted_at", None)
            item.setdefault("deleted_by", None)
            item.setdefault("sha256", None)
            videos.append(item)

        migrated = {
            "version": INDEX_VERSION,
            "videos": videos,
            "recent_sent_ids": [
                str(x)
                for x in (data.get("recent_sent_ids") or [])
                if x is not None
            ],
        }
        if version < INDEX_VERSION:
            logger.info("天菜索引已从 v%s 迁移到 v%s", version, INDEX_VERSION)
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
