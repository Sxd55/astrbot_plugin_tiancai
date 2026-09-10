"""AstrBot 天菜视频库插件。

功能：
1. 回复群视频消息并发送「收进天菜」：下载并保存到本地全局视频库
2. 发送「看看天菜」：从全局库随机抽取一条视频发送到当前会话
"""

from __future__ import annotations

import json
import random
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import File, Reply, Video
from astrbot.api.star import Context, Star, register
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

PLUGIN_NAME = "astrbot_plugin_tiancai"
INDEX_FILENAME = "index.json"
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv"}


@register(
    PLUGIN_NAME,
    "sxd55",
    "收藏群视频到本地，随机「看看天菜」",
    "1.0.0",
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
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.videos_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_index()

    async def initialize(self):
        logger.info(
            "天菜视频库已加载，目录=%s，当前数量=%s",
            self.videos_dir,
            len(self._load_index().get("videos", [])),
        )

    # ------------------------------------------------------------------
    # 指令
    # ------------------------------------------------------------------

    @filter.command("收进天菜", alias={"加入天菜", "天菜入库"})
    async def collect_tiancai(self, event: AstrMessageEvent):
        """回复一条视频消息后发送本指令，将视频保存到全局天菜库。"""
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
                for item in index.get("videos", [])
            )
        ):
            yield event.plain_result("这条视频已经在天菜库里啦～")
            return

        max_videos = int(self.config.get("max_videos", 0) or 0)
        if max_videos > 0 and len(index.get("videos", [])) >= max_videos:
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

        record = {
            "id": video_id,
            "filename": dest.name,
            "saved_at": int(time.time()),
            "source_message_id": source_msg_id,
            "source_group_id": str(source_meta.get("group_id") or event.get_group_id() or ""),
            "collector_id": str(event.get_sender_id() or ""),
            "collector_name": str(event.get_sender_name() or ""),
            "size": dest.stat().st_size,
        }
        index.setdefault("videos", []).append(record)
        self._save_index(index)

        yield event.plain_result(
            f"已收进天菜！当前共 {len(index['videos'])} 条。\n编号：{video_id[:8]}"
        )

    @filter.command("看看天菜", alias={"来点天菜", "天菜"})
    async def show_tiancai(self, event: AstrMessageEvent):
        """从全局天菜库随机发送一条视频。"""
        index = self._load_index()
        videos = [
            item
            for item in index.get("videos", [])
            if (self.videos_dir / str(item.get("filename", ""))).is_file()
        ]
        if not videos:
            yield event.plain_result(
                "天菜库还是空的。回复一条群视频并发送「收进天菜」先囤一点吧。"
            )
            return

        # 清理索引里已丢失文件的条目
        if len(videos) != len(index.get("videos", [])):
            index["videos"] = videos
            self._save_index(index)

        chosen = random.choice(videos)
        path = self.videos_dir / str(chosen["filename"])
        video = Video.fromFileSystem(path=str(path))
        yield event.chain_result([video])

    @filter.command("天菜数量", alias={"天菜库", "天菜列表"})
    async def tiancai_count(self, event: AstrMessageEvent):
        """查看天菜库当前数量。"""
        index = self._load_index()
        videos = [
            item
            for item in index.get("videos", [])
            if (self.videos_dir / str(item.get("filename", ""))).is_file()
        ]
        if len(videos) != len(index.get("videos", [])):
            index["videos"] = videos
            self._save_index(index)
        yield event.plain_result(
            f"天菜库现有 {len(videos)} 条视频，目录：{self.videos_dir}"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("清空天菜")
    async def clear_tiancai(self, event: AstrMessageEvent):
        """管理员：清空全局天菜库（不可恢复）。"""
        index = self._load_index()
        removed = 0
        for item in index.get("videos", []):
            path = self.videos_dir / str(item.get("filename", ""))
            if path.is_file():
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    logger.exception("删除视频失败: %s", path)
        self._save_index({"videos": []})
        yield event.plain_result(f"已清空天菜库，删除文件 {removed} 个。")

    # ------------------------------------------------------------------
    # 视频提取
    # ------------------------------------------------------------------

    async def _extract_video_from_event(
        self, event: AstrMessageEvent
    ) -> tuple[Video | None, dict[str, Any]]:
        """优先从被回复消息中找视频，其次从当前消息找。"""
        messages = event.get_messages() or []

        # 1) 回复引用
        for comp in messages:
            if isinstance(comp, Reply):
                video = self._find_video_in_chain(comp.chain or [])
                if video is not None:
                    return video, {
                        "message_id": comp.id,
                        "group_id": event.get_group_id(),
                    }

                # 部分适配器不会填充 Reply.chain，尝试走协议端拉取
                fetched = await self._fetch_video_by_message_id(event, str(comp.id))
                if fetched is not None:
                    return fetched, {
                        "message_id": comp.id,
                        "group_id": event.get_group_id(),
                    }

        # 2) 当前消息本身带视频
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
            # 有些协议端会把短视频当成 File
            if isinstance(comp, File):
                name = (comp.name or "").lower()
                url = (comp.url or "").lower()
                file_hint = (comp.file_ or "").lower()
                if any(
                    hint.endswith(suffix) or suffix in hint
                    for hint in (name, url, file_hint)
                    for suffix in VIDEO_SUFFIXES
                ):
                    # 包装成 Video，复用 convert_to_file_path
                    source = comp.url or comp.file_ or ""
                    if source.startswith("http://") or source.startswith("https://"):
                        return Video.fromURL(url=source)
                    if source:
                        return Video.fromFileSystem(path=source)
        return None

    async def _fetch_video_by_message_id(
        self, event: AstrMessageEvent, message_id: str
    ) -> Video | None:
        """尝试通过 aiocqhttp / OneBot 拉取被引用消息中的视频。"""
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

        # OneBot: {"message":[...]} 或 {"data":{"message":[...]}}
        payload = raw.get("data", raw) if isinstance(raw, dict) else {}
        segments = payload.get("message") if isinstance(payload, dict) else None
        if isinstance(segments, str):
            # CQ 码字符串，简单提取 file=
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
                    # file:// 或本地路径 / 裸文件名
                    return Video(file=file_val, url=url or "", path=data.get("path") or "")
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
        # 粗略解析 [CQ:video,file=xxx,url=yyy]
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
    # 索引
    # ------------------------------------------------------------------

    def _ensure_index(self) -> None:
        if not self.index_path.exists():
            self._save_index({"videos": []})

    def _load_index(self) -> dict[str, Any]:
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {"videos": []}
            videos = data.get("videos", [])
            if not isinstance(videos, list):
                videos = []
            data["videos"] = videos
            return data
        except Exception:  # noqa: BLE001
            logger.exception("读取天菜索引失败，将重置")
            return {"videos": []}

    def _save_index(self, data: dict[str, Any]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.index_path)

    async def terminate(self):
        logger.info("天菜视频库插件已卸载")
