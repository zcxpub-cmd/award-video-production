# 功能截图

这些图片来自开源版运行的虚构工程。素材墙图片直接截取当前主分支的暗黑界面，其他配图展示实际命令结果、导出文档内容或成片画面。红框标出智能体的命令、参数和返回字段。

| 截图 | 展示内容 |
|---|---|
| [全屏动态首页](25-fullscreen-home.jpg) | 全幅背景视频和进入素材墙入口 |
| [暗黑素材库](26-workbench-assets-dark.jpg) | 新版工作台导航、审核统计和素材卡片 |
| [暖白素材库](27-workbench-assets-light.jpg) | 切换到暖白后的同一工作台 |
| [智能体启动入口](28-workbench-agent-launch.jpg) | 红框标出打开动态首页的命令 |
| [v1.2.0 动态首页](23-open-source-scenes.jpg) | 本机服务启动后的首屏，展示随机抽中的一景和进入素材墙按钮 |
| [v1.2.0 智能体启动首页](24-agent-home-launch.jpg) | 红框标出实测启动命令、返回的首页 URL 和「进入素材墙」按钮 |
| [素材墙总览](07-wall-overview-dark.jpg) | 六份视频、图片和音频候选，显示来源、用途、对应句子和审核进度 |
| [组合筛选](08-wall-filter-dark.jpg) | 同时用关键词、章节、来源和审核状态定位一个候选 |
| [视频播放与信息](09-wall-playback-dark.jpg) | 视频预览、建议使用的源内范围、分辨率和叙事用途 |
| [审核保存](10-wall-review-saved-dark.jpg) | 修改审核决定和备注，显示本地保存结果 |
| [导出审核](11-wall-export.jpg) | 同一次审核实际导出的 JSON 和 CSV 节选 |
| [智能体工具发现](12-agent-discovery.jpg) | `list` 返回三个工具的名称和素材盘点的参数结构 |
| [智能体素材盘点](13-agent-inventory.jpg) | `inventory` 的目录输入与实际盘点结果 |
| [智能体工程检查](14-agent-check.jpg) | `check` 检查新建工程并返回待补项 |
| [智能体媒体探测](15-agent-probe.jpg) | `probe` 返回 H.264、分辨率、帧率和时长 |
| [旁白稿与镜头交接](16-manuscript-handoff.jpg) | 从实际 DOCX 读取的正文及镜头与句子编号的对应 |
| [抽帧与重复候选](17-media-frames.jpg) | 视频抽帧接触表及相同文件识别 |
| [成片与字幕导出](18-render-subtitles.jpg) | 实际成片画面、完整片、分项片、SRT 和 ASS |
| [混音与保时静音](21-audio-mix.jpg) | 指定区间压低和静音，输出实际探测仍为 3 秒 |
| [质检与归档](19-qc-archive.jpg) | 完整解码结果与独立归档的哈希核验 |
| [Seedance 请求校验](20-seedance-validate.jpg) | 本地校验的真实输出和请求指纹 |

素材墙视频实际播到结尾。保存审核后刷新页面复核，两个导出格式均返回更新后的审核结果。技术质检和归档使用内置演示脚本。Seedance 图记录离线校验，返回的 `network_called` 为 `false`。

安装和复现方法见 [开源版使用说明书](../使用说明书.md)。历史截图可在 [v1.0.0 标签](https://github.com/zcxpub-cmd/award-video-production/tree/v1.0.0/docs/screenshots) 和 [v1.1.0 发布说明](../release-v1.1.0.md) 查看。
