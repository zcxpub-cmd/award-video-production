# 真实视频：本地证据提取

本方法使用 `claude-real-video` 的本地CLI。运行前用 `crv --help`复核实际版本参数。此处仅处理用户允许本机分析的现有本地文件，不给出下载普通版权视频、复制浏览器cookie或外传片段的路径。

1. 先统计文件大小与时长，确认用途是事实核查、镜头选择、节奏或质量检查。
2. 选择唯一项目输出目录，记录源文件SHA-256和分析问题。
3. 直接调用已安装CLI（doctor返回路径）；外部 `crv_analyze.sh`缺环境时会自动安装，本流程不借此隐式下载。

```sh
crv \
  '/项目/sources/authorized.mp4' -o '/项目/work/video-review-v01' \
  --grid --max-frames 60 --no-transcribe --viewer --report \
  --why '核查装置完整形态、镜头边界和关键字幕'
```

输出先读 `MANIFEST.txt` 的数量、时间码和失败项，再查看 `grids/` 联系图；按问题精查单帧，记录可观察的事实与时间戳。`viewer.html`是离线复核入口。`--adaptive`适合缓慢变形/推移；`--text-anchors`依赖旁挂或嵌入字幕时间点，不等于自动OCR；`--scene`降低可增加变化帧，`--fps-floor N`表示至少每N秒一帧，N减小才更密；`--max-frames`限制上限。

有本地已装Whisper模型且本次需要转写，才移除 `--no-transcribe`并设置 `--lang zh --whisper-model 实际已装档位`。没有现成模型时改用本地VoiceStudio ASR或记录无音频证据，不通过分析命令隐式下载大模型。`--keep-audio`仅保留本地音轨，是否能听见/观察仍另验。

CLI缺失时的本地保底：先用已安装FFmpeg取指定窗口，避免通读全片。下例从12秒起取8秒、每秒2帧，最多16帧；先创建唯一输出目录。

```sh
ffmpeg -v error -ss 12 -t 8 -i '/项目/sources/authorized.mp4' \
  -vf 'fps=2,scale=960:-2' -frames:v 16 '/项目/work/review-window/frame-%03d.jpg'
ffmpeg -v error -ss 12 -t 8 -i '/项目/sources/authorized.mp4' \
  -vn -ac 1 -ar 16000 '/项目/work/review-window/audio.wav'
```

时间戳须加上窗口起点12秒。逐帧图不能证明两帧之间的运动正确；看到快动作/闪烁风险时缩小窗口并加密采样，再播放对应区间。最终片仍需全段解码与播放器检查，不能以联系图代替。原片不移动、不覆盖；提取失败先核对编码、输出空间、ffmpeg路径和权限，保留失败日志摘要后最多一次有针对性的本地重试。
