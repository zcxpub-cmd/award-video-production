# 本机素材墙：构建、播放、审核与交接

本模块独立工作。入口是 `scripts/material_wall.py`，页面源码内置于 `assets/wall/`；不需要账号、数据库、云服务或其他插件。基础功能只需要 Python 3.10+ 和现代浏览器。视频缩略图、格式判断及可选代理使用 PATH 中已有的 `ffmpeg` / `ffprobe`，不会联网安装。

## 1. 从一个素材清单开始

在插件的 `skills/science-achievement-film/` 目录运行以下命令。`project/materials.json` 的相对素材路径，以 **materials.json 所在目录** 解析。

```json
{
  "title": "示例成果 · 颁奖视频",
  "assets": [
    {
      "asset_id": "A01",
      "chapter_id": "C01",
      "source_path": "media/apparatus.mov",
      "preview_path": "",
      "thumbnail_path": "",
      "sentence_ids": ["C01_S01", "C01_S02"],
      "semantic_reason": "展示装置整体及操作者的尺度关系",
      "origin": "单位提交",
      "local_codex_generated": false,
      "text_policy": "保留仪器上的科学标签",
      "source_in_s": 2,
      "source_out_s": 8,
      "review_status": "pending",
      "review_note": "待确认是否可用于公开成片",
      "license_evidence": "单位提供的书面授权记录"
    }
  ]
}
```

- `asset_id` 必填且唯一，使用英文、数字、点、横线、下划线；首字符为字母或数字，最多 96 字符。
- `source_path` 是本机原件。支持相对路径与明确的外部绝对路径，拒绝 URL；缺失文件保留卡片并标明问题。不会读取未下载的云占位文件或跟随文件符号链接。
- `preview_path` 可选，适合专业格式的现有兼容预览；可读取时优先复用。`thumbnail_path` 可选，接受安全的常见栅格图像格式。SVG / HTML 不作为媒体提供。
- `sentence_ids` 在 JSON 中为数组；CSV 可用 JSON 数组文本或 `S01|S02`。用途写入 `semantic_reason`，只描述有证据支持的关系。
- `source_in_s` / `source_out_s` 是源内制作建议范围。页面可以定位起点，**不会裁切原件，也不会限制只播放这一范围**。外部 `preview_path` 若已剪切，不能默认继承源内时间；本模块生成的代理保留完整时间轴。
- `review_status` 为 `pending`（待审）、`approved`（通过）、`rejected`（弃用）；兼容中文“待审/通过/弃用”。备注存入 `review_note`。
- **只有 `local_codex_generated=true` 才显示 AI 标记。** 布尔字段兼容 CSV `true/false`，`1/0`、`yes/no`。`origin` 中有“AI”或旧 `display_ai_badge=true` 均不能触发标记；旧标记会按生成事实重算。
- 既有 `source_version`、`availability`、`probe_status`、`watched_ranges`、`resolution`、`person_or_logo`、`duplicate_group`、`full_form_ending`、`license_evidence` 等列保留。它们是输入事实，不会因页面能打开而被提升为验收结论。

也可直接输入 CSV，兼容 `assets/material-wall.csv` 的已有列。自定义 CSV 列在导出时保留。仅含表头的清单会生成空墙，并显示空状态。

## 2. 构建输出与可移植包

```bash
python3 scripts/material_wall.py build project/materials.json --output project/wall-v1
```

默认媒体仍在原位置；墙只保存允许访问的文件白名单，不复制大原件。移动、替换或删除原件后需要重新构建。输出目录必须是新的目录；脚本不会覆盖旧墙、审核记录或源素材。

需要随目录搬迁的交付包时：

```bash
python3 scripts/material_wall.py build project/materials.json \
  --output project/wall-portable-v1 --copy-media --thumbnails --proxies
```

`--copy-media` 复制清单内可用的原件、现有预览与缩略图到输出 `media/`，需要相应磁盘空间。生成的缩略图和代理始终在输出 `media/` 内。整体搬迁输出目录后，使用同一脚本 `serve` 即可；应同时保留插件代码以便在另一台机器启动。

构建结果会报告输出目录、素材数量、可移植状态及缺失工具提示。每张卡片另有文件缺失、代理失败等问题说明。输出存在不表示每份素材都可用。

输出目录包含：

| 文件 | 用途 |
|---|---|
| `index.html` / `app.js` / `style.css` | 完整本机页面 |
| `manifest.json` | 页面用清单，媒体地址为白名单端点 |
| `reviews.json` | 独立审核记录，写入时原子替换 |
| `media-map.json` | 私有媒体白名单，默认可包含本机绝对路径 |
| `records.json` | 原始字段与导出字段登记 |
| `media/` | 复制的媒体及本模块生成的缩略图、代理 |
| `START_HERE.txt` | 启动说明 |

`media-map.json`、`records.json` 和 `reviews.json` 不作为静态文件通过 HTTP 开放。数据包属于实际项目资料，发布插件源码时不要把这些项目输出包混入代码仓库。

## 3. 缩略图、原件与代理

```bash
# 仅提取缩略图；ffmpeg 不在 PATH 时给出提示并继续构建
python3 scripts/material_wall.py build project/materials.json \
  --output project/wall-thumbs --thumbnails

# 明确允许按需生成代理；默认保留原音，转为 AAC
python3 scripts/material_wall.py build project/materials.json \
  --output project/wall-proxy --thumbnails --proxies --proxy-audio keep

# 只让新生成的代理静音，原件不变
python3 scripts/material_wall.py build project/materials.json \
  --output project/wall-muted --proxies --proxy-audio mute
```

代理选择规则是保守的格式候选规则：MP4 / M4V 的 H.264 8 位 4:2:0（配 AAC / MP3 音轨），或 WebM 的 VP8 / VP9（配 Opus / Vorbis），可直接尝试浏览器播放。HEVC、AVI、MOV、MKV、MXF 等会在明确指定 `--proxies` 后按需转换。可读取的 `preview_path` 始终先复用，不擅自覆盖。没有指定 `--proxies` 时不转码。

新代理使用 H.264 / yuv420p / MP4 faststart，最长宽高限制为 1280 × 720，不放大低分辨率素材、不裁切、不设置入出点、保持完整视场和时长；偶数像素约束可能带来极小的尺寸取整。保留声音时选择第一条原音轨转为 AAC；多音轨原件仍完整保留。`--proxy-audio mute` 只影响本次新生成的代理，已提供预览不会被静音改写。单份代理最多尝试 600 秒，超时显示失败状态。

页面和导出区分 `preview_status`：

| 状态 | 意义 |
|---|---|
| `provided` | 复用输入预览文件 |
| `generated` | 生成代理且通过流格式探测，仍待浏览器播放验收 |
| `original_candidate` | 尝试原件播放，未证明浏览器支持 |
| `failed` | 缺少工具、探测或转码失败，页面显示错误 |
| `unavailable` | 无可读取媒体 |

浏览器解码能力依操作系统和浏览器而异。`ffprobe` 成功、缩略图生成、代理生成，均不等于浏览器播放通过；专业格式可以下载清单内原件，用本机专业播放器复核。代理播放也不能替代原件全片观看、科学核验和声音验收。

## 4. 启动本机服务与审核

没有常驻后台服务；每次需要审核时启动：

```bash
python3 scripts/material_wall.py serve project/wall-v1 --port 8765
```

打开命令打印的本机地址，从动态首页点「进入素材墙」。端口占用时换用 `--port 8766`，或 `--port 0` 自动分配。终端保持运行，按 `Ctrl+C` 停止。双击 `index.html` 可离线查看动态首页和启动说明。素材播放和审核保存由本机服务提供。

1. 搜索编号、文件名、章节、来源、句子、用途或审核备注；可以叠加章节、来源、审核状态筛选。
2. 打开卡片，查看图片 / 视频 / 音频与元数据；视频支持拖动。媒体缺失和解码问题显示在详情。
3. 选择通过、弃用或待审，填写备注，点击“保存审核”。只有出现“已保存到本地”才视为持久化成功。
4. 当前素材墙目录的 `reviews.json` 会写入最新记录。停止服务再启动仍保留审核结果；重建是一个新墙，不自动合并旧审核。
5. 导出 JSON 或 CSV 获取最新已保存审核；下载文件由浏览器保存。JSON 可继续交给本插件的清单处理流程。CSV 保留旧列并补充预览状态等列，UTF-8 BOM 便于常见表格软件识别。

导出里的可用媒体路径改为**当前本机实际绝对路径**，保证下载到另一个目录后仍能解析。搬迁可移植墙后重新导出，会使用新的媒体位置。找不到的素材保留输入引用供人工补齐。CSV 对可能被表格软件解释为公式的单元格加前导单引号；JSON 保留原文本。

未保存的修改在关闭详情或离开页面时提醒。服务重启后令牌会变化，旧页面保存会被拒绝并提示刷新。一个墙目录同时只开一个审核服务；当前版本没有多进程编辑锁或多人合并策略。

## 5. 本机安全边界

- 只监听 `127.0.0.1`，不提供公网或局域网监听参数。HTTP `Host` 只接受当前端口的 `127.0.0.1` / `localhost`，拒绝跨站来源。
- 只开放固定页面、固定 API 与清单白名单媒体端点；没有目录浏览，也没有任意路径或 URL 读取接口。
- 外部媒体只能由构建时登记的具体文件提供；替换为另一个 inode 或符号链接后会拒绝读取。包内媒体必须留在 `media/` 内。
- 每次启动生成随机令牌。审核 POST 必须同时通过同源 `Origin`、令牌、JSON 类型、请求体长度、素材 ID 和字段检查；不提供跨域 CORS 写入。
- 页面用文本节点展示输入内容，不执行清单中的 HTML。安全响应头限制脚本、媒体和连接在本机同源。
- 审核只改写 `reviews.json`。保存失败显示错误，不把未写入状态报告成成功。保留原始输入，所有构建输出写到新目录。

此服务供本机单用户工作，不是认证服务器。能访问本机文件的进程仍由操作系统权限约束；若需要多人远程审核，应使用另一个经过认证与权限设计的系统。

## 6. 验证

```bash
python3 -m unittest discover -s tests -p 'test_material_wall.py' -v
node --check assets/wall/app.js
```

脚本测试包含 JSON / CSV 导入、AI 标记规则、可移植媒体、审核持久化与导出、Range / HEAD、来源与 CSRF、非法 ID、路径穿越、私有文件隔离、符号链接及原件替换拒绝。存在 ffmpeg / ffprobe 时，还会用临时合成的 MPEG-4 AVI + PCM 音轨验证代理转为 H.264 / AAC、完整解码、时长与视场、静音选项、预览复用及原件哈希不变；工具缺失时该项明确跳过。

最后仍须在实际浏览器检查：列表与过滤、播放器正常推进与拖动、通过 / 弃用 / 待审及备注保存、刷新恢复、JSON / CSV 下载。技术测试不能代替这一步，也不能替代项目内容验收。
