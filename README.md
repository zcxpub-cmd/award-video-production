# 影序

**让故事，连接脉动。**

面向智能体的视频制作工具集。用于颁奖、成果发布和科学传播视频，从权威资料与文案、素材审核到剪辑、后期交接和交付归档。

影序原名「颁奖视频制作」。仓库地址和插件安装命令继续沿用原有标识。

[开源版使用说明书](docs/使用说明书.md) · [逐项功能说明](docs/features.md) · [快速上手](skills/science-achievement-film/references/quickstart.md) · [能力与边界](skills/science-achievement-film/references/capabilities.md) · [验证范围](skills/science-achievement-film/references/verification.md)

[下载 v1.4.0 开源工作台 ZIP](https://github.com/zcxpub-cmd/award-video-production/releases/download/v1.4.0/award-video-production-v1.4.0.zip) · [下载 v1.4.0 图文使用手册（PDF）](https://github.com/zcxpub-cmd/award-video-production/releases/download/v1.4.0/yingxu-v1.4.0-user-guide-zh-CN.pdf) · [安装与使用说明](docs/使用说明书.md)

[下载最新中英文工作台源码 ZIP / Download the bilingual source](https://github.com/zcxpub-cmd/award-video-production/archive/refs/heads/main.zip)。主分支附带已构建的中英文界面。v1.4.0 发行附件与 PDF 手册对应此前发布的中文版本。

1. 安装 Python 3.10 或更新版本，然后解压上方最新源码 ZIP，或下载 Release 附件中的发行 ZIP。
2. macOS 双击 `启动影序.command`，Windows 双击 `start-yingxu.bat`，Linux 运行 `sh start-yingxu.sh`。首次联网准备本机依赖，随后自动打开动态首页。
3. 点「开始创作」，填写项目名，选择「人工设置」或「一键成片」。从素材库导入文件，再在「时间线剪辑」编辑。成片和工程包在「导出与检查」下载。

工作台提供 12 份可填变量的原创提示词模板、四个内置制作角色及手动多轨编辑。需要 AI 剪辑、画面观察或导演编排时，在「偏好与配置」连接自己的本机 Ollama。技术审核与手动制作可独立运行。

首页与工作台顶部提供 **EN / 中文** 切换，浏览器记住语言。七个工作页、12 份原创提示词模板和智能体说明支持英文；在「内置智能体」查看各角色的调用条件。已有工程名称、字幕和用户素材按原语言保留。

Download the bilingual source ZIP above, then select **EN** at the top of the home page or workbench to switch to English. The browser remembers your language. Use **Production Agents** to see when each role runs. To launch, use `启动影序.command` on macOS, `start-yingxu.bat` on Windows, or `sh start-yingxu.sh` on Linux.

已有命令行素材审核墙可继续用 `agent_tools.py launch` 打开。能启动本地进程的智能体可以用 `agent_tools.py studio` 启动完整工作台。双击 `打开影序.html` 可离线查看 18 景动态封面与安装说明。[画面来源](docs/home-cover-assets.md)

## 功能实拍

以下是开源工作台用公开演示媒体的实测截图。[完整截图索引](docs/screenshots/README.md)

![开源工作台动态首页](docs/screenshots/29-community-home.jpg)

![新建工程，可选人工设置和一键成片](docs/screenshots/30-community-new-project.jpg)

![五轨时间线及红框标出的 AI 剪辑建议](docs/screenshots/32-community-timeline-agent.jpg)

![可填写变量的原创提示词模板](docs/screenshots/31-community-prompt-template.jpg)

![实际成片导出和技术检查](docs/screenshots/33-community-export.jpg)

以下为兼容的命令行工具与独立素材审核墙。

### 素材墙与审核

在一屏看素材来源、对应句子、用途和审核进度。打开卡片可播放视频并查看源内范围。

![新版素材库，展示暗黑主题和统一导航](docs/screenshots/26-workbench-assets-dark.jpg)

![新版素材库，展示暖白主题](docs/screenshots/27-workbench-assets-light.jpg)

<details>
<summary>查看素材审核流程图示</summary>

以下流程图来自上一版素材墙，审核、筛选和导出操作继续可用。

![播放视频候选，查看源内范围、分辨率和叙事用途](docs/screenshots/09-wall-playback-dark.jpg)

![使用关键词、章节、来源和审核状态定位候选](docs/screenshots/08-wall-filter-dark.jpg)

![修改审核结论和备注并保存](docs/screenshots/10-wall-review-saved-dark.jpg)

![从同一次审核导出的 JSON 与 CSV 记录](docs/screenshots/11-wall-export.jpg)

</details>

### 智能体接入

能启动本地进程的宿主可以发现工具，传入 JSON 参数，再读取素材盘点、工程检查和媒体参数。红框标出实际调用入口与返回字段。[智能体接入说明](docs/agent-integration.md)

![红框标出智能体工作台的启动入口](docs/screenshots/28-workbench-agent-launch.jpg)

![红框标出工具发现命令、工具名称和参数结构](docs/screenshots/12-agent-discovery.jpg)

<details>
<summary>查看三个智能体工具的调用和返回</summary>

![红框标出素材盘点的目录参数和报告](docs/screenshots/13-agent-inventory.jpg)

![红框标出工程检查的输入和待补项](docs/screenshots/14-agent-check.jpg)

![红框标出媒体探测的输入和视频流参数](docs/screenshots/15-agent-probe.jpg)

</details>

### 文稿、镜头交接和媒体分析

文稿可导出可编辑 DOCX。将镜头与句子编号对应后，再用抽帧和候选检测辅助审核。

![从导出的 DOCX 读取正文，并展示镜头和句子的对应记录](docs/screenshots/16-manuscript-handoff.jpg)

![从实际视频生成的抽帧接触表与检测统计](docs/screenshots/17-media-frames.jpg)

### 剪辑、字幕和交付

按剪辑配方渲染带字幕的完整影片和分项片。成片可完整解码检查，归档可重新核验依赖的文件哈希。

![实际成片画面、分项片与可编辑字幕](docs/screenshots/18-render-subtitles.jpg)

![两条合成音轨混音，按区间压低音量和保时静音](docs/screenshots/21-audio-mix.jpg)

![完整解码结果和归档哈希核验](docs/screenshots/19-qc-archive.jpg)

### 视频生成配置

用内置 Seedance 客户端离线校验模型和提示词组成的请求结构。用户配置 API、使用 ComfyUI 后导入和规划中的托管生成见手册。[生成配置说明](docs/使用说明书.md#3-三种新镜头生成方式)

![Seedance 本地校验命令和实际返回值](docs/screenshots/20-seedance-validate.jpg)

## 包含什么

- 可播放的本地素材墙：缩略图、兼容代理、章节/来源筛选、句子对应、审核备注、本地持久化、JSON/CSV导出。
- 文档提取与文稿：DOCX/PPTX/PDF/文本导入、来源定位、四层文本、完整/逐章DOCX、语义交接。
- 本地媒体生产：抽帧/接触表、重复与切点候选、SRT/ASS字幕和独立标题、等比剪辑、混音、保时静音、分项片和完整解码。
- 项目检查与归档：时长/术语边界/冻结文件检查、依赖候选、独立复制、路径迁移、哈希核验、可恢复隔离与审定清理。
- 内置外部工具方法：语音、Seedance、真实视频分析、摄影节奏、几何建模、PPT/WPS/OCR、达芬奇的输入、调用、操作、失败恢复和验证。

本包内置制作逻辑和方法；Python、FFmpeg、OCR/语音工具、生成服务与原生编辑器是运行依赖。语义理解、科学核验、正常速度观看和听审由操作者/智能体实际完成，不能用文件存在或自动指标冒充。

## 功能怎么用

| 功能 | 典型输入 | 可得到的结果 |
|---|---|---|
| 项目策划与版本控制 | 最新需求、已确认组件、实际时长 | 制作计划、保护范围、可复核状态 |
| 文档与旁白稿 | DOCX/PPTX/PDF、结构化文稿 | 来源定位、全篇/逐章DOCX、四层文本 |
| 素材分析 | 本机视频与图片 | 参数、抽帧、接触表、切点和重复候选 |
| 语义交接与素材墙 | 句子编号、镜头、用途、源内范围 | 可播放审核页、记录、JSON/CSV导出 |
| 配音与生成集成 | 审定文本/提示词、已配置外部引擎 | 内置调用与恢复方法、任务账本、结果核对 |
| 字幕标题与剪辑 | 实测时间码、显式剪辑配方 | SRT/ASS、完整片、独立成果片 |
| 声音编排 | 旁白、BGM、明确时间与增益 | 混音、淡入淡出、压低音乐、保时静音 |
| 达芬奇后期 | 时间线、源文件、原生软件 | 调色/稳像/包装/渲染的完整操作方法 |
| 技术QC与归档 | 输出片、审定依赖 | 全解码报告、归档哈希、迁移与恢复工具 |
| 环境与开源发布 | 本机配置、独立公开源 | 依赖诊断、隐私扫描、白名单ZIP |

每项的**输入、命令、输出、依赖及验收边界**均在[详细功能说明](docs/features.md)中展开。通用工具完整公开，不附作者环境配置、私人媒体或账号。

## 安装与调用

支持本地进程的智能体宿主可以使用 JSON 工具入口，见[智能体接入说明](docs/agent-integration.md)。
[v1.4.0 发布说明](docs/release-v1.4.0.md)记录可安装的开源工作台与内置智能体。相比 v1.0.0 的上一版变更见 [v1.1.0 发布说明](docs/release-v1.1.0.md)。

### Codex 插件

在支持本地插件市场的 Codex 中，于解压后的仓库根目录运行：

```bash
codex plugin marketplace add .
codex plugin add science-achievement-film@award-video-production
codex plugin list --marketplace award-video-production
```

从主分支安装时，插件显示名称为「影序」。已有发行包可能仍显示「颁奖视频制作」。新对话中可以选择该插件，或输入「使用影序插件，根据这些资料先做脚本和素材方案」。调用标识为 `science-achievement-film`。

### 仅安装 skill

将 `skills/science-achievement-film` 整个目录复制到自己的 Codex skills 目录。调用 `$science-achievement-film`。所有模板、脚本、参考方法均使用技能内相对路径，不依赖原作者目录。

## 快速开始

在 `skills/science-achievement-film` 目录执行；新项目输出目录应选在仓库外：

```bash
python3 scripts/runtime_tools.py --help
python3 scripts/filmkit.py init /path/to/new-project --chapters 3 --max-seconds 300 --fps 25
python3 scripts/content_tools.py --help
python3 scripts/material_wall.py --help
python3 scripts/media_tools.py --help
python3 scripts/archive_tools.py --help
```

完整可执行顺序和命令见 [QUICKSTART](skills/science-achievement-film/references/quickstart.md)，能力与验收边界见 [CAPABILITIES](skills/science-achievement-film/references/capabilities.md)。从 [SKILL.md](skills/science-achievement-film/SKILL.md) 按任务读取，不必一次加载所有参考。

Python工具以标准库为基础。媒体命令需要相应能力的 FFmpeg/ffprobe；中文烧录字幕需要 libass 和中文字体。PDF/OCR/ASR及原生编辑器按对应集成方法配置。不会自动安装模型、启动付费生成或上传素材。

## 一次跑通虚构演示

```bash
cd skills/science-achievement-film
python3 scripts/demo_project.py --output /path/to/new-demo --ffmpeg /path/to/full/ffmpeg --font "Noto Sans CJK SC"
```

演示生成测试图形和正弦音，跑通文稿、素材墙、字幕标题、成片和分项片、技术质检与归档。输出目录必须是仓库外的新目录。按输出的 `START_HERE.md` 启动服务，在动态首页点「进入素材墙」。如果 `PATH` 中的 FFmpeg 已具备所需过滤器，可省略 `--ffmpeg`。

## 测试与发布

```bash
python3 -m unittest discover -s skills/science-achievement-film/tests -v
python3 skills/science-achievement-film/tests/regression_filmkit.py
python3 skills/science-achievement-film/scripts/public_release.py scan .
python3 skills/science-achievement-film/scripts/public_release.py build . --out ../award-video-production-v1.4.0.zip
```

媒体回归需要支持相关过滤器的 FFmpeg；可通过 `MEDIA_TEST_FFMPEG` / `MEDIA_TEST_FFPROBE` 指定。测试使用临时合成素材，外部服务使用离线模拟；未运行付费模型或用户工程。发布工具只打包公开白名单，排除git历史、私有配置、制作输出和报告。隐私扫描是辅助，发布前仍应人工检查内容与许可证。

[验证范围](skills/science-achievement-film/references/verification.md)记录实际运行与尚未执行部分。

MIT，见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE.md)。
