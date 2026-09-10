# 插件设置说明

可在 AstrBot 插件配置页修改，也可在「天菜管理台 → 设置」修改。  
两项会写入同一份配置。

---

## 公共源（读取）

### 启用公共源 `public_enabled`
- **作用**：是否同步并使用公共菜单。
- **默认**：开启。
- **建议**：想只用本地库时再关闭。

### 公共菜单 URL `public_index_url`
- **作用**：公共库菜单 JSON 地址。
- **留空**：自动使用官方默认  
  `https://raw.githubusercontent.com/sxd55/astrbot_plugin_tiancai/main/public/public_index.json`
- **自建库**：改成你的 raw 地址，例如  
  `https://raw.githubusercontent.com/你的用户名/tiancai-public/main/public/public_index.json`

### 抽取模式 `library_mode`
- **仅本地库 `local`**：只从本机视频抽。
- **仅公共源 `public`**：只从公共菜单抽。
- **本地 + 公共混合 `mixed`**（默认）：两边一起抽。

### 同步间隔（小时）`public_sync_hours`
- **作用**：多久重新拉取一次公共菜单。
- **默认**：12。
- **填 0**：每次抽取前都尝试同步（更及时，更费网络）。

### 公共视频自动导入本地库 `public_auto_import`
- **作用**：抽中并下载公共视频后，自动写入本地库，便于预览/编辑/再发布。
- **默认**：开启。

### 混合模式下公共权重 `public_weight`
- **作用**：仅 `mixed` 时生效。
- **1.0**：与本地同等；`<1` 更常抽本地；`>1` 更常抽公共。

### GitHub 代理前缀 `github_proxy`
- **作用**：拉取 GitHub raw / Release 时加在原 URL 前。
- **留空**：默认 `https://gh-proxy.com/`。

---

## 发布到 GitHub（写入你自己的仓库）

> 读取官方/他人菜单 **不需要** Token。  
> 只有「发布到公共库」才需要 Token + 你自己的仓库。

### GitHub Token `github_token`
- **作用**：创建/更新 Release 附件，并提交 `public_index.json`。
- **权限**：对该仓库至少 Contents 读写。
- **安全**：只保存在你的 Bot 配置里，不要发到群里或写进开源代码。
- **UI**：已配置时留空表示不修改。

### 你的仓库 owner/repo `github_repo`
- **作用**：发布与「公共库」管理的目标仓库，格式 `用户名/仓库名`。
- **重要**：**发布/修改公共库时必须手填你自己的仓库**，不会默认写到官方仓库。
- **示例**：`yourname/tiancai-public` 或 `sxd55/astrbot_plugin_tiancai`
- 管理台「公共库」栏只操作这个仓库（需同时配置 Token）
- 建库步骤见：[`SETUP_PUBLIC_REPO.md`](./SETUP_PUBLIC_REPO.md)

### 菜单所在分支 `github_branch`
- **默认**：`main`

### 仓库内菜单路径 `github_index_path`
- **默认**：`public/public_index.json`

### 视频 Release 标签 `github_release_tag`
- **默认**：`tiancai-videos`
- 视频作为该标签下的 Release 附件保存，避免把大文件塞进 git 历史。

### 单条上传大小上限（MB）`max_public_upload_mb`
- **默认**：95（GitHub 单文件硬顶约 100MB）。

---

## 本地库与抽取

### 抽取冷却（秒）`cooldown_seconds`
同一用户两次随机发送的最短间隔；管理员免冷却。`0` = 不限制。

### 本地库上限 `max_videos`
本地在库最大条数（不含回收站）。`0` = 不限制。

### 允许重复入库同一条消息 `allow_duplicate`
关闭后按原消息 ID 去重。

### 入库白名单 QQ `collect_whitelist`
除 AstrBot 管理员外，允许入库的 QQ 号，逗号分隔。

### 少重复：近期条数 / 近期权重
最近发出的 N 条会乘以较小权重，降低连抽重复。

### 置顶权重 `pinned_weight`
置顶视频更容易被抽到。

### 本地存储子目录名 `storage_subdir`
一般保持 `videos` 即可。

---

## 指令别名

每一项都可自定义触发词，多个别名用逗号分隔。  
例如把随机发送改成：`来点好吃的,看看天菜`

| 配置项 | 默认示例 |
| --- | --- |
| `cmd_collect` | 收进天菜,加入天菜,天菜入库 |
| `cmd_show` | 看看天菜,来点天菜,天菜 |
| `cmd_sync` | 同步天菜源,天菜同步,同步公共天菜 |
| `cmd_count` | 天菜数量,天菜库,天菜列表 |
| `cmd_delete` | 删除天菜,天菜删除 |
| `cmd_detail` | 天菜详情,天菜信息 |
| `cmd_help` | 天菜帮助,天菜说明,天菜指令 |
| `cmd_clear` | 清空天菜（仅管理员） |

带参数的指令用法：`删除天菜 3`、`天菜详情 3`（编号为空格后的内容）。

---

## 管理台「公共库」栏

在「视频库」旁边。需要已配置 `github_token` + `github_repo`。

| 功能 | 说明 |
| --- | --- |
| 刷新同步 | 重新读取你仓库里的 `public_index.json` |
| 预览 | 卡片右侧点击预览，与本地视频库相同交互（过大文件会提示改用下载） |
| 编辑 | 修改公共条目的标题、标签并写回 GitHub |
| 删除所选 | 从菜单移除，并尽量删除对应 Release 附件 |
| 下载到本地 | 把公共视频下载并导入本地视频库 |

只读别人的公共菜单：把「公共菜单 URL」指到对方 raw 地址即可，**不需要**对方 Token。  
改别人的库：除非你的 Token 对该仓库有写权限，否则会失败。
