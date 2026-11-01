# 内置工具方法

本目录把成果宣传片需要的第三方操作方法整理为可独立执行的配方。先读对应文件中的输入、调用、输出与恢复步骤；公开来源用于更新核对，不是必须另读的操作说明。第三方程序、模型和商业应用仍由本机已安装实例提供，不复制进本包。

| 阶段 | 内置方法 | 使用条件 |
|---|---|---|
| 环境与任务恢复 | [runtime.md](runtime.md) | 先检查路径与功能，再登记任务；登记不执行服务 |
| 中文旁白与ASR | [voicestudio.md](voicestudio.md) | 默认回环地址、现有模型、固定真实声音ID |
| Seedance短镜头 | [seedance.md](seedance.md) | 提示词、参考授权、预算与远端提交范围明确 |
| 真实视频本地分析 | [local-video.md](local-video.md) | 现有本地授权文件，不下载普通版权视频 |
| 剪辑与达芬奇 | [davinci.md](davinci.md) | 当前MCP schema和实际工程读回；保留工具guard |
| 电影摄影与节奏 | [cinematic-rhythm.md](cinematic-rhythm.md) | 由科学事实和镜头任务决定，不凭风格补造事实 |
| 几何、PPT/WPS、OCR | [geometry-documents.md](geometry-documents.md) | 原始文件、尺寸和页码可追溯 |

提取日期为2026-11-01。公开来源、接口、许可和方法范围见 [sources.json](sources.json)。本次封装的实际验证记录见 [validation.md](validation.md)。没有运行付费生成，也没有把源码阅读、MCP schema或历史接口说明写成当前模型/成片质量通过。

本包没有新增前台权限。涉及打开应用、切焦点、菜单、播放器或鼠标键盘时，使用当前会话已经成立的授权；特定工具要求限定前台时段的，按该工具范围执行。后台检查和本地文件操作可直接继续。缺少授权时先完成后台准备，明确具体需要的操作后再请求。
