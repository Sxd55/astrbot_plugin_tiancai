# astrbot_plugin_tiancai

本地天菜库 + 公共天菜源。默认启用公共菜单，支持自定义指令、UI 改配置、发布到你自己的 GitHub 仓库。

仓库：https://github.com/sxd55/astrbot_plugin_tiancai

## v1.6.0 要点

- 默认公共菜单：`https://raw.githubusercontent.com/sxd55/astrbot_plugin_tiancai/main/public/public_index.json`
- 默认启用公共源，抽取模式默认 `mixed`
- 公共视频下载后**默认自动导入本地库**
- 管理台新增「设置」页：改配置 / 改指令别名 / 填 Token 与仓库
- 去掉维护口令；「发布到公共库」对配置了 Token+仓库的用户开放（发到**自己的仓库**）
- GitHub 代理留空默认 `https://gh-proxy.com/`
- 建库教程：[`docs/SETUP_PUBLIC_REPO.md`](./docs/SETUP_PUBLIC_REPO.md)

## 快速使用

1. 安装/更新插件并重载  
2. 直接「看看天菜」可抽默认公共源（需网络）  
3. 想发布自己的库：按教程建仓库，在设置页填 `github_token`、`github_repo`  
4. 想改指令：设置页把「随机发送指令」改成任意词，例如 `来点好吃的,看看天菜`

## 安装

```bash
cd AstrBot/data/plugins
git clone https://github.com/sxd55/astrbot_plugin_tiancai.git
# 更新
cd astrbot_plugin_tiancai && git pull
```

重载插件后打开：插件详情 → 天菜管理台。

## 许可证

MIT
