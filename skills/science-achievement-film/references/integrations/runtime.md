# 环境诊断与任务恢复

`scripts/runtime_tools.py` 是本包原创的标准库辅助程序。它不安装软件、不下载模型、不打开应用、不运行用户给出的任意命令、不生成语音或视频。配置只接受本包列出的工具名；可修改本机执行路径，不填写密钥值。

```sh
python3 scripts/runtime_tools.py doctor --config assets/runtime-config.example.json
python3 scripts/runtime_tools.py doctor --check-local-services
```

第二条只GET本地VoiceStudio `/health`，不接受远端URL、登录信息或重定向。环境报告不包含健康响应正文。密钥只检查文件存在且非空，不打开文件、不回显路径和值。`available`仅表示可执行文件存在；必须另查模型和实际任务效果。

FFmpeg默认从PATH发现，也可通过 `SCIENCE_FILM_FFMPEG` 或显式配置指定完整构建。报告 `ass/subtitles/freezedetect/blackdetect/silencedetect/loudnorm/ebur128/xfade/acrossfade` 各过滤器；烧字幕需要 `ass` 或 `subtitles`。不要用另一可执行文件的检测结果为当前命令背书。Tesseract另报已安装语言，`chi_sim`/`chi_tra`缺失不代表不能用其它本地OCR，但不能声称中文OCR已就绪。Python模块报告只针对实际运行doctor的解释器。

配置中的 `crv` 指向已经安装的CLI；doctor不会调用会自动安装环境的外部wrapper。Seedance使用本包的最小HTTP客户端，凭证文件位置只接受用户显式配置。软件版本和模型能力需要执行任务时再读回，不能由文件存在推断。

登记一项尚未执行的任务（从skill根目录运行；示例路径应替换为本次项目）：

```sh
python3 scripts/runtime_tools.py register --project-root '/项目绝对路径' \
  --ledger '/项目绝对路径/work/runtime-jobs.json' --id shot_detail_v01 \
  --kind seedance --request-file '/项目绝对路径/work/request.json' \
  --output '/项目绝对路径/outputs/shot_detail_v01.mp4' --max-attempts 1
```

账本只存请求文件SHA-256，不存正文、Authorization、参考媒体Base64或完整服务响应。ID、输出文件名不要含凭证或个人隐私。输出必须位于本次项目下且是新路径。账本加锁并原子替换；异常退出若留下 `.lock`，先确认无任务持锁再移走，不自动破锁；相同ID重复登记拒绝。登记后按实际观察推进：

```sh
python3 scripts/runtime_tools.py transition --project-root '/项目绝对路径' \
  --ledger '/项目绝对路径/work/runtime-jobs.json' --id shot_detail_v01 \
  --to submitted --external-id '实际服务返回任务ID'
python3 scripts/runtime_tools.py status --project-root '/项目绝对路径' \
  --ledger '/项目绝对路径/work/runtime-jobs.json' --id shot_detail_v01
python3 scripts/runtime_tools.py retry-plan --project-root '/项目绝对路径' \
  --ledger '/项目绝对路径/work/runtime-jobs.json' --id shot_detail_v01
```

状态含 `prepared/submitted/running/succeeded/failed/unknown/cancelled`。提交响应丢失：先记 `running` 再 `unknown`，按服务历史对账；有外部ID则查原任务，禁止盲目再POST。`succeeded`要求登记输出和 `--evidence` 文件存在且非空；这是文件证据门槛，不会自动判断听感、语义或科学准确性。

只有 `local-analysis/local-render` 的明确失败可 `retry` 回到prepared；次数默认2、硬上限3，已有局部输出先检查和保留，不能覆盖。`retry-plan`给出2–30秒退避建议但不睡眠、不执行。TTS、Seedance和达芬奇渲染失败先分析原任务和输出；需要新提交时创建新的明确任务，不把重试能力当作收费/外传授权。

所有命令错误对外只给固定摘要，避免异常把请求、URL或密钥意外带进聊天。因此排障先检查参数、目录权限、状态、预算；不要为获得详细报错而打印凭证。
