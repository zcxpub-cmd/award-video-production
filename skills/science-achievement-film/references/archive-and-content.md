# 内置文稿、语义交接与归档工具

所有路径由使用者提供，输入保持不变。输出采用新文件或新目录；不会暗中覆盖审定稿。下列命令以技能目录为工作目录。

## 文档转为可引用资料

```bash
python3 scripts/content_tools.py ingest report.docx --document-id DOC01 --out out/report.json
python3 scripts/content_tools.py ingest mechanism.pptx --document-id PPT01 --out out/slides.json
```

支持DOCX正文段落/表格、按演示顺序的PPTX文本和动画存在标记、TXT/Markdown/CSV；PDF使用显式可用的pdftotext。输出文件hash、稳定定位、原文和未核验标记。图片内文字、公式、版式和PPT动画需要按 integrations/geometry-documents.md 的OCR与实际播放方法处理，不能凭抽取结果猜测。

## 完整与逐章可编辑文稿

复制 assets/manuscript.example.json。chapters[].chapter_id 与 sentences[].id 为稳定ID；title、units为正式名称。每句text是审定口播，tts_text是发音控制，subtitle_text是屏显，source_refs引用资料定位。opening/ending单独保存，调整正文时保持已批准边界。

```bash
python3 scripts/content_tools.py manuscript manuscript.json --out-dir out/manuscript-v1
```

输出完整narration.docx/narration.md、每章独立DOCX、text-layers.json与输入快照。只保留文字，不复制原手册版式、人员元数据或原图；正式文档用WPS/Word等打开复核。工具不改写事实、不自动审核文案。

## 稳定语义映射与素材墙

复制 assets/shots.example.json，逐镜写明source_path、可选preview_path/thumbnail_path、asset_id、sentence_ids、semantic_reason、来源与文字政策。相对路径按shots文件所在目录解释。只有明确local_codex_generated:true才显示本机AI徽标。

```bash
python3 scripts/content_tools.py handoff manuscript.json shots.json --out out/wall-input.json
python3 scripts/material_wall.py build out/wall-input.json --output out/wall --thumbnails --proxies
python3 scripts/material_wall.py serve out/wall --port 8765
```

handoff检查ID、文件、区间和覆盖，转换三类媒体路径以便跨目录交接；结构通过不表示语义或科学成立。生成的墙记录审核意见。生产时只选当前批准的素材，明确展示完整成果形态的末镜。

## 与filmkit检查计划连接

manuscript JSON负责文案；filmkit project.json负责已测时长、镜头计划、冻结状态，字段不同。不要把同一JSON直接传给两种工具。

```bash
python3 scripts/content_tools.py to-project manuscript.json --out out/project.json --fps 25 --max-seconds 600
python3 scripts/filmkit.py check out/project.json --out out/plan-check.json
```

转换为单向新快照，复制标题/单位/正文并保留句ID。未知时长为null，等待实际配音后填写；转换后的空镜头/未测时长会被检查拒绝，这是正确行为。后续文稿变化按ID合并，不能重新转换覆盖已批准和已测数据。标题/单位口播开关只改变是否生成相应口播条目，不删除正式屏显信息。

## 依赖发现与独立副本归档

复制 assets/archive-plan.example.json；files是明确采用的保留文件，references用于发现候选。支持JSON路径字段、Python静态文件输入线索、ZIP型DRP内XML路径候选。动态路径、工程数据、模板和相对工作目录需实际审查。

```bash
python3 scripts/archive_tools.py discover archive-plan.json --out dependency-candidates.json
```

审查所有真实制作输入，把采用的候选加入files，处理unresolved，再明确dependency_review_complete:true。清单不自动批准自身。

```bash
python3 scripts/archive_tools.py create reviewed-plan.json --out archive-final
python3 scripts/archive_tools.py verify archive-final
python3 scripts/archive_tools.py rewrite-json archive-final archived-or-original-edit.json --out archive-final/restored-edit.json
```

归档用独立复制和双端hash校验，保存original_path到archive_path映射；运行时记录为恢复所需，属于使用者私有项目资料，不随开源源码提交。rewrite-json可直接读取归档成员，使用原始配置的基准解析相对引用；未映射路径会明确返回。它只改指定JSON路径，不篡改DRP/任意程序。迁移后重连原生工程、重开、运行重建脚本、播放成片再确认恢复。verify只证明清单内文件完整，不能证明动态依赖已全部列出。

## 明确授权后的清理

默认不删除。复制 assets/cleanup.example.json，明确已验证归档、保护路径和可清理目标；不扫描任意主目录。生成计划：

```bash
python3 scripts/archive_tools.py cleanup-plan cleanup.json --out reviewed-cleanup.json
```

核对清单和授权范围，使用输出的计划SHA执行可恢复隔离（同一文件系统）：

```bash
python3 scripts/archive_tools.py quarantine reviewed-cleanup.json --out quarantine --confirm-plan-sha256 EXACT_PLAN_SHA256
python3 scripts/archive_tools.py restore quarantine
```

隔离移动不释放空间。确认不再需要隔离文件且用户已明确授权永久清理后，使用quarantine-manifest.json准确SHA：

```bash
python3 scripts/archive_tools.py purge quarantine --confirm-manifest-sha256 EXACT_MANIFEST_SHA256
```

脚本再次核验归档、名单与hash，仅删除已审定隔离成员；不按旧版名称推测。保护路径与硬链接别名需保留。实际释放空间另行测量，不把路径数/逻辑大小当真实回收量。命令中的确认hash防止错用计划，不能取代用户授权。半途失败依据quarantine-manifest.json的operation_status恢复；restore可以在中断后续跑，purge-progress.json记录已完成删除并只续处理审定清单余项。不伪称清理完成。
