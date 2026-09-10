# 如何建立自己的 GitHub 天菜公共库

本教程教你：**用自己的 GitHub 仓库当公共菜单 + Release 存视频**，然后在插件里发布/读取。

---

## 你将得到什么

- 一个公开仓库，例如 `yourname/tiancai-public`
- 仓库里有 `public/public_index.json`（菜单）
- 视频放在 Release 标签 `tiancai-videos` 下
- 插件设置里填 Token + 仓库后，可在管理台勾选本地视频「发布到公共库」
- 别人只要把「公共菜单 URL」指到你的 raw 地址，就能抽取你的公共库

---

## 第一步：新建公开仓库

1. 打开 https://github.com/new
2. Repository name 建议：`tiancai-public`
3. 选 **Public**
4. 可勾选 Add a README（可选）
5. Create repository

---

## 第二步：放上菜单文件

在仓库中创建：

```text
public/public_index.json
```

内容可先用：

```json
{
  "version": 1,
  "updated_at": 0,
  "name": "我的天菜公共库",
  "license_note": "仅放有权公开分发的内容",
  "maintainer": "yourname",
  "videos": []
}
```

提交到 `main` 分支。

你的菜单地址将是：

```text
https://raw.githubusercontent.com/yourname/tiancai-public/main/public/public_index.json
```

---

## 第三步：创建 GitHub Token

1. 打开 https://github.com/settings/tokens?type=beta  
   （或 Classic：https://github.com/settings/tokens ）
2. 生成 token，至少给该仓库 **Contents: Read and write**
3. 复制 token（只显示一次）

---

## 第四步：在插件设置里填写

打开 AstrBot → 天菜管理台 → **设置**：

| 项 | 填什么 |
| --- | --- |
| 启用公共源 | 开 |
| 公共菜单 URL | 你的 raw 地址（也可先用官方示例地址看效果） |
| 抽取模式 | `mixed` 推荐 |
| 公共视频自动导入本地库 | 开（默认） |
| GitHub Token | 粘贴你的 PAT |
| 你的仓库 owner/repo | 例如 `yourname/tiancai-public` |
| 分支 | `main` |
| 菜单路径 | `public/public_index.json` |
| Release 标签 | `tiancai-videos` |
| GitHub 代理 | 留空则默认 `https://gh-proxy.com/` |

保存设置。

---

## 第五步：发布视频到你的公共库

1. 先用「收进天菜」或管理台「上传到本地」把视频放进本地库  
2. 打开「视频库」，勾选条目  
3. 点 **发布到公共库**  
4. 确认后，插件会：  
   - 上传到你仓库的 Release `tiancai-videos`  
   - 更新你仓库的 `public/public_index.json`

注意：单文件建议 < 95MB（GitHub 硬顶 100MB）。

---

## 第六步：别人如何使用你的库

让对方在设置里把「公共菜单 URL」改成你的 raw 地址，并启用公共源。  
他们**不需要**你的 Token，只能读取，不能往你仓库写。

---

## 常见问题

**发布失败 401/403**  
Token 无效或权限不够，检查 Contents 写权限、仓库名是否写对。

**国内拉取慢**  
代理留空会走 `gh-proxy.com`；也可换成你可用的代理前缀。

**不想自动进本地库**  
设置里关闭「公共视频自动导入本地库」。

**指令想改成别的词**  
在设置里改「随机发送指令」等字段，例如：`来点好吃的,看看天菜`

---

## 安全提醒

- Token 只放在你自己的 Bot 配置里，不要发到群里  
- 只发布你有权公开的内容  
- 需要下架时：从 `public_index.json` 删除对应条目并提交
