# astrbot_plugin_tiancai

AstrBot 插件：本地天菜库 + 可选公共天菜源。

仓库：https://github.com/sxd55/astrbot_plugin_tiancai

## 功能（v1.5.0）

- 本地：收进 / 看看 / 删除 / 详情 / 编号 / 默认标签「天菜」/ WebUI 预览
- 公共源（只读）：同步 GitHub 菜单，经代理下载视频，支持 local/public/mixed
- 维护者发布：配置 `github_token` + `admin_passphrase` 后，WebUI「维护」解锁，批量发布本地视频到 GitHub Release，并更新 `public/public_index.json`

详细运营说明：[`docs/PUBLIC_LIBRARY.md`](./docs/PUBLIC_LIBRARY.md)

## 指令

| 指令 | 说明 |
| --- | --- |
| `收进天菜` | 回复视频入库（管理员/白名单） |
| `看看天菜` | 按 library_mode 随机发送 |
| `同步天菜源` | 手动同步公共菜单 |
| `天菜数量` | 本地/公共数量 |
| `删除天菜 <编号>` | 软删除，如 `删除天菜 3` |
| `天菜详情 <编号>` | 查看详情 |
| `清空天菜` | 管理员清空到回收站 |
| `天菜帮助` | 帮助 |

## WebUI

插件详情 → **天菜管理台**

- 普通：浏览/预览/上传本地/回收站
- 维护：点右上角 **维护**，输入配置中的口令后，可 **发布到公共库**

## 配置要点

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `public_enabled` | false | 启用公共源读取 |
| `public_index_url` | 空 | 菜单 raw URL |
| `library_mode` | local | local / public / mixed |
| `github_proxy` | 空→`https://gh-proxy.com/` | GitHub 代理前缀 |
| `github_token` | 空 | 仅维护者，secret |
| `admin_passphrase` | 空 | 仅维护者，secret |
| `github_repo` | `sxd55/astrbot_plugin_tiancai` | 公共仓库 |
| `github_index_path` | `public/public_index.json` | 菜单路径 |
| `github_release_tag` | `tiancai-videos` | 视频 Release |
| `max_public_upload_mb` | 95 | 单文件上传上限 |

推荐公共菜单地址：

```text
https://raw.githubusercontent.com/sxd55/astrbot_plugin_tiancai/main/public/public_index.json
```

## 安装

```bash
cd AstrBot/data/plugins
git clone https://github.com/sxd55/astrbot_plugin_tiancai.git
# 更新：git pull 后重载插件
```

## 许可证

MIT
