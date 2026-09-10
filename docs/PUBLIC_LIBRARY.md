# 天菜公共库运营说明

推荐架构：**本仓库 `public/public_index.json` 做菜单 + GitHub Release 存视频**。  
拉取时可走代理（默认 `https://gh-proxy.com/`）。

---

## 1. 角色

| 角色 | 职责 | Token / 口令 |
| --- | --- | --- |
| 普通用户 | 同步菜单、「看看天菜」、本机收藏 | 无 |
| 维护者（你） | 审核内容；在 WebUI 解锁后批量发布 | `github_token` + `admin_passphrase` |

**铁律：**

- 口令与 Token 只写在**你的服务器插件配置**里（secret），不要写进开源仓库
- 群里「收进天菜」只进本地库，不会自动进公共库
- 没有 Token 的人即使看到按钮，也无法发布

---

## 2. 维护者配置（你的 AstrBot）

| 配置 | 示例 | 说明 |
| --- | --- | --- |
| `github_token` | `ghp_xxx` | 有 `repo` 权限的 PAT |
| `admin_passphrase` | 你自己设的口令 | 解锁 WebUI「发布到公共库」 |
| `github_repo` | `sxd55/astrbot_plugin_tiancai` | 公共库所在仓库 |
| `github_branch` | `main` | 菜单分支 |
| `github_index_path` | `public/public_index.json` | 菜单路径 |
| `github_release_tag` | `tiancai-videos` | 视频 Release 标签 |
| `github_proxy` | 留空 | 默认 `https://gh-proxy.com/` |
| `public_enabled` | `true` | 启用公共源读取 |
| `public_index_url` | raw 地址 | 见下 |
| `library_mode` | `mixed` | 本地+公共混合抽 |

`public_index_url` 示例：

```text
https://raw.githubusercontent.com/sxd55/astrbot_plugin_tiancai/main/public/public_index.json
```

插件拉取时会自动加代理前缀（可用 `github_proxy` 覆盖默认）。

---

## 3. 发布流程（只有你能做）

1. 本地「收进天菜」或管理台上传到**本地库**
2. 天菜管理台 → 右上角 **维护** → 输入 `admin_passphrase`
3. 在「视频库」勾选 → **发布到公共库**
4. 插件会：上传 mp4 到 Release `tiancai-videos`，并更新 `public/public_index.json`
5. 其他用户同步菜单后即可抽到

单文件默认上限 **95MB**（GitHub 硬顶 100MB）。

---

## 4. 普通用户

1. `public_enabled = true`
2. 填写同一 `public_index_url`
3. `library_mode = public` 或 `mixed`
4. 建议开启 `public_cache_enabled`
5. 「看看天菜」/「同步天菜源」

他们没有你的口令与 Token，不能往公共库上传。

---

## 5. 审核与下架

审核：版权、合规、体积、去重。  
下架：从 `public_index.json` 删除条目并 push；可选删除 Release 资产。

---

## 6. 安全

- 不要把口令硬编码进开源代码；放到配置即可
- Token 泄露请立刻作废重建
- 公共 URL 人人可下，只放你愿意公开的内容
