# astrbot_plugin_tiancai

AstrBot 插件：把 QQ 群里的视频「收进天菜」存到本地全局库，发送「看看天菜」时随机上传一条到聊天。

仓库：https://github.com/sxd55/astrbot_plugin_tiancai

> 基于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 插件体系开发。  
> 开发文档：[AstrBot 插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)

## 功能（v1.2.0）

### Batch 1
- **收进天菜**：回复群视频后入库（管理员或白名单）
- **看看天菜**：降权少重复随机发送 + 冷却防刷
- **天菜数量 / 删除天菜 / 天菜详情 / 天菜帮助 / 清空天菜**
- 索引自动升级到 **v2**（备注/标签/置顶/播放统计/软删除）

### Batch 2 · WebUI 管理台
- 插件详情页 → **天菜管理台**
- 总览：在库/回收站/占用/今日统计
- 视频库：搜索、排序、编辑备注标签、置顶、批量移入回收站、下载
- 回收站：恢复 / 永久删除
- 上传视频直接入库
- 审计日志浏览

后续批次：标签抽/搜索/连抽/排行指令、hash 去重、定时推送等。详见 `FEATURE_DISCUSSION.md`。

## 指令

| 指令 | 别名 | 权限 | 说明 |
| --- | --- | --- | --- |
| `收进天菜` | `加入天菜` / `天菜入库` | 管理员或白名单 | 回复视频消息后入库 |
| `看看天菜` | `来点天菜` / `天菜` | 全员（有冷却） | 随机发送一条本地视频 |
| `天菜数量` | `天菜库` / `天菜列表` | 全员 | 查看数量 |
| `删除天菜 <编号>` | `天菜删除` | 管理员或原收藏人 | 移入回收站 |
| `天菜详情 <编号>` | `天菜信息` | 全员 | 查看元信息 |
| `天菜帮助` | `天菜说明` / `天菜指令` | 全员 | 查看帮助 |
| `清空天菜` | — | 仅管理员 | 全部移入回收站 |

## WebUI

1. 打开 AstrBot 管理面板 → 插件  
2. 进入 **天菜视频库** 详情  
3. 打开页面组件 **天菜管理台**

## 安装 / 更新

```bash
cd AstrBot/data/plugins
git clone https://github.com/sxd55/astrbot_plugin_tiancai.git
# 已安装：
cd astrbot_plugin_tiancai && git pull
```

然后在 WebUI 启用并**重载插件**（新增 Pages 目录后必须重载）。

## 数据目录

```text
data/plugin_data/astrbot_plugin_tiancai/videos/
data/plugin_data/astrbot_plugin_tiancai/index.json
data/plugin_data/astrbot_plugin_tiancai/audit.log
```

## 配置项

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `storage_subdir` | `videos` | 视频存储子目录名 |
| `max_videos` | `0` | 在库上限，`0` 不限制 |
| `allow_duplicate` | `false` | 是否允许同一原消息重复入库 |
| `collect_whitelist` | `[]` | 额外可入库的 QQ 号列表 |
| `cooldown_seconds` | `15` | 「看看天菜」冷却（管理员免冷却） |
| `recent_penalty_count` | `8` | 近期已发条数，用于降权 |
| `recent_penalty_weight` | `0.15` | 近期视频权重（普通为 1.0） |
| `pinned_weight` | `3.0` | 置顶视频权重 |

## 平台说明

- 推荐配合 **aiocqhttp / OneBot v11**（NapCat、Lagrange 等）
- 「收进天菜」依赖协议端提供被引用消息中的视频文件或可下载 URL
- 「看看天菜」通过 `Video.fromFileSystem` 发送；协议端与 AstrBot 不在同一机器时请配置 `callback_api_base`

## 路线图

见 [FEATURE_DISCUSSION.md](./FEATURE_DISCUSSION.md)。

## 许可证

MIT
