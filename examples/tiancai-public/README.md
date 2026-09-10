# tiancai-public（示例）

这是「天菜公共菜单」仓库模板。

## 你要做的事

1. 新建一个 **Public** GitHub 仓库（建议就叫 `tiancai-public`）  
2. 把本目录的 `public_index.json` 拷进去  
3. 在 Cloudflare R2 上传真实 mp4，把 `url` 换成可匿名访问的 HTTPS 直链  
4. 浏览器无登录能打开该 `url` 后再 `git push`  

## 插件怎么填

```text
public_enabled = true
public_index_url = https://raw.githubusercontent.com/<你的用户名>/tiancai-public/main/public_index.json
library_mode = mixed
public_cache_enabled = true
```

## 谁能上传？

只有公共库维护者能上传到 R2。  
所有安装插件的用户只下载菜单和视频，不能往公共盘写。

完整流程见插件内：`docs/PUBLIC_LIBRARY.md`。
