# 从零到可审核输出

以下均在技能目录执行。在仓库之外创建自己的项目目录，复制模板时保留空值/待审字段，不填虚假的“已完成”。依赖按 integrations/runtime.md 配置；没有相关软件时不触发安装或远端生成。

## 先试完整虚构流程（可选）

```bash
python3 scripts/demo_project.py --output /path/to/new-synthetic-demo --ffmpeg /path/to/full/ffmpeg --font "Noto Sans CJK SC"
```

仅自产图形和正弦音；实际生成文稿、待审素材墙、字幕、短片、分项和归档。它不是业务成片或听感样音。已有合适FFmpeg可省略路径参数；字体参数换成实际已安装的中文字体。完成后按START_HERE.md操作。

## 1. 准备文案与资料

```bash
FILM_PROJECT="/path/to/your/project"
mkdir -p "$FILM_PROJECT/out" "$FILM_PROJECT/media"
cp assets/manuscript.example.json "$FILM_PROJECT/manuscript.json"
cp assets/shots.example.json "$FILM_PROJECT/shots.json"
python3 scripts/content_tools.py ingest "$FILM_PROJECT/report.docx" --document-id DOC01 --out "$FILM_PROJECT/out/report.json"
python3 scripts/content_tools.py manuscript "$FILM_PROJECT/manuscript.json" --out-dir "$FILM_PROJECT/out/narration-v1"
python3 scripts/content_tools.py to-project "$FILM_PROJECT/manuscript.json" --out "$FILM_PROJECT/out/project.json"
```

示例媒体/report并未预置，替换为自己有权使用的文件。文稿示例是虚构内容。事实仍应逐项核对；不要把示例当真实成果。

## 2. 盘点、理解并审核画面

```bash
python3 scripts/filmkit.py inventory "$FILM_PROJECT/media" --out "$FILM_PROJECT/out/inventory.json" --probe
python3 scripts/media_tools.py frames "$FILM_PROJECT/media/demo.mp4" --every 1 --output "$FILM_PROJECT/out/frames"
python3 scripts/content_tools.py handoff "$FILM_PROJECT/manuscript.json" "$FILM_PROJECT/shots.json" --out "$FILM_PROJECT/out/wall-input.json"
python3 scripts/material_wall.py build "$FILM_PROJECT/out/wall-input.json" --output "$FILM_PROJECT/out/wall" --thumbnails --proxies
python3 scripts/material_wall.py serve "$FILM_PROJECT/out/wall" --port 8765
```

在浏览器打开 http://127.0.0.1:8765 ，从动态首页点「进入素材墙」，播放候选、审核并导出。下次用同一条 `serve` 命令启动服务，可继续使用已有审核记录。分享素材墙副本用 `--copy-media`，只复制清单列明且有权分享的文件。

## 3. 外部生产与本地合成

配音/ASR、生成、建模和达芬奇的实际方法已内置于 integrations，各自有真实输入输出与恢复方法。软件/模型由使用者配置；不需要额外skill文本，但必须有执行引擎。

按实测声音时间编辑subtitle-timing JSON，按审核镜头编辑edit配方，路径相对该JSON。已有assets/edit-recipe.example.json可复制；所有源必须存在，out父目录先创建。

```bash
python3 scripts/media_tools.py subtitles "$FILM_PROJECT/subtitle-timing.json" --output "$FILM_PROJECT/out/subtitles-v1"
python3 scripts/media_tools.py render "$FILM_PROJECT/edit.json" --output "$FILM_PROJECT/out/film-v1"
python3 scripts/media_tools.py qc "$FILM_PROJECT/out/film-v1/film.mp4" --output "$FILM_PROJECT/out/qc-v1.json"
```

render按chapters生成各分项片；原生工程、复杂转场/稳像/调色仍按内置NLE方法执行。字幕技术合成不代表汉字无缺字，实际播放核查。

## 4. 计划检查、交付与归档

为project.json填写真实测量和镜头映射，采用filmkit check；未测模板报错是正常状态。用QC清单覆盖全片及各章边界，确认文件、播放、听感与用户审核范围，再执行 archive_tools 的审定依赖归档。归档迁移要在原目录不可用时复核重建，不只检查文件是否复制成功。

## 数据流说明

- `manuscript.json`：文案与出处。
- `shots.json`：候选镜头、源路径、句ID和用途。
- `wall-input.json`：handoff产生，交给素材墙。
- `project.json`：to-project产生的检查计划，填实际时长和冻结组件；不是编辑器时间线。
- `subtitle-timing.json`：ASR/人工核对后的媒体时间码。
- `edit.json`：实际合成配方；字段见local-media-tools.md。
- `archive-plan.json`：已审核的真实文件依赖。

转换为新快照，不覆盖已有审核。修改通过稳定ID传递，不能用旧时间点直接剪新配音。所有运行输出属于使用者项目，不放入技能仓库。
