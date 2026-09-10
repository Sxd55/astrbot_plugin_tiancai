# astrbot_plugin_tiancai

AstrBot 插件：把 QQ 群里的视频「收进天菜」存到本地全局库，发送「看看天菜」时随机上传一条到聊天。

> 基于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 插件体系开发。  
> 开发文档：[AstrBot 插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)

## 功能

- **收进天菜**：回复一条群视频消息，再发送指令，插件会下载该视频并保存到本地全局视频库
- **看看天菜**：从全局库随机选一条视频发送到当前会话
- **天菜数量**：查看当前库内视频数量
- **清空天菜**（管理员）：清空整个全局库

默认是**全局共用库**：所有群 / 私聊共用同一套本地视频。

## 指令

| 指令 | 别名 | 说明 |
| --- | --- | --- |
| `收进天菜` | `加入天菜` / `天菜入库` | 回复视频消息后入库 |
| `看看天菜` | `来点天菜` / `天菜` | 随机发送一条本地视频 |
| `天菜数量` | `天菜库` / `天菜列表` | 查看数量与存储目录 |
| `清空天菜` | — | 仅管理员，清空库 |

> 具体是否需要指令前缀（如 `/`），取决于你在 AstrBot 中的指令配置。

## 使用示例

1. 群里有人发了一段视频  
2. 回复该视频消息，发送：`收进天菜`  
3. 机器人回复「已收进天菜！」  
4. 之后任何人发送：`看看天菜`  
5. 机器人随机上传一条本地天菜视频

## 安装

### 方式一：AstrBot 插件市场 / 仓库安装

将本仓库地址填入 AstrBot 插件安装入口即可（安装后重载插件）。

### 方式二：手动安装

```bash
cd AstrBot/data/plugins
git clone https://github.com/sxd55/astrbot_plugin_tiancai.git
```

然后在 WebUI 插件管理中启用并重载。

### 首次推送到 GitHub

本机已安装并登录 [GitHub CLI](https://cli.github.com/) 时，可在插件目录双击或执行：

```bat
push_to_github.bat
```

会创建公开仓库 `sxd55/astrbot_plugin_tiancai` 并推送 `main` 分支。

## 数据目录

按 AstrBot 规范，大文件存放在：

```text
data/plugin_data/astrbot_plugin_tiancai/videos/
data/plugin_data/astrbot_plugin_tiancai/index.json
```

更新 / 重装插件不会清空该目录（除非你手动删除或执行「清空天菜」）。

## 配置项

在 WebUI 插件配置中可调整：

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `storage_subdir` | `videos` | 视频存储子目录名 |
| `max_videos` | `0` | 库容量上限，`0` 表示不限制 |
| `allow_duplicate` | `false` | 是否允许同一条原消息重复入库 |

## 平台说明

- 推荐配合 **aiocqhttp / OneBot v11**（如 NapCat、Lagrange 等）使用
- 「收进天菜」依赖协议端能提供被引用消息中的视频文件或可下载 URL
- 「看看天菜」通过 `Video.fromFileSystem` 发送本地文件，要求协议端与 AstrBot 能访问同一文件系统路径；若协议端在另一台机器，请配置 AstrBot 的 `callback_api_base` 文件回调

## 开发说明

主要实现文件：

- `main.py`：指令与入库 / 随机发送逻辑
- `metadata.yaml`：插件元数据
- `_conf_schema.json`：可视化配置

持久化索引为 `index.json`，每条记录包含：

- `id` / `filename` / `saved_at`
- `source_message_id` / `source_group_id`
- `collector_id` / `collector_name` / `size`

## 许可证

MIT
