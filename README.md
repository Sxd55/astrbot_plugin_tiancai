# astrbot_plugin_tiancai

本地天菜库 + 公共天菜源。默认启用公共菜单，支持自定义指令、UI 改配置、发布到你自己的 GitHub 仓库。

仓库：https://github.com/sxd55/astrbot_plugin_tiancai

## v1.7.0 要点

- 新增管理台 **「公共库」** 栏（在视频库旁边）
- 可用 `github_token` + `github_repo` 管理自己的公共库：浏览、刷新、编辑标题/标签、删除、下载到本地
- 设置面板分组说明、抽取模式下拉、菜单 URL 留空用官方默认
- 公共视频下载后默认自动导入本地库
- 发布仍需手填自己的 `github_repo`（读取官方菜单不依赖它）
- 设置说明：[`docs/SETTINGS.md`](./docs/SETTINGS.md)
- 建库教程：[`docs/SETUP_PUBLIC_REPO.md`](./docs/SETUP_PUBLIC_REPO.md)

## 快速使用

1. 安装/更新并重载插件
2. 直接发随机指令可抽默认公共源（需网络）
3. 自建并发布：按教程建仓库 → 设置页填 Token 与 `你的用户名/仓库名`
4. 改指令：设置页修改「随机发送指令」等字段

## 默认公共菜单

```text
https://raw.githubusercontent.com/sxd55/astrbot_plugin_tiancai/main/public/public_index.json
```

## 安装

```bash
cd AstrBot/data/plugins
git clone https://github.com/sxd55/astrbot_plugin_tiancai.git
# 更新
cd astrbot_plugin_tiancai && git pull
```

重载后打开：插件详情 → 天菜管理台。

## 许可证

MIT
