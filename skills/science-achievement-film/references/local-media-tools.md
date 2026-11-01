# 内置本地媒体工具

`scripts/media_tools.py` 内置生产逻辑、参数校验、时间轴处理与技术检查；实际解码、编码、字体渲染由本机 `ffmpeg` / `ffprobe` 完成。使用 Python 标准库，不依赖 Pillow，不安装软件、不调用模型、不访问网络、不启动剪辑器。本文与示例仅使用通用虚构素材。

## 依赖与调用

- Python 3.9+；本次回归实际使用 Python 3.14。
- 本机 `ffmpeg`、`ffprobe`。编码需要 `libx264`、AAC、PCM；视频适配需要支持 `scale` 的 `reset_sar` 选项。已经在 FFmpeg 8.x 上实测。
- 烧录字幕需 `ass` 过滤器（libass）及可用中文字体；冻结候选需 `freezedetect`。缺少过滤器会明确失败，不生成成功输出。字体是否缺字仍须看实际画面。
- 默认从 PATH 寻找二进制。`--ffmpeg` 和 `--ffprobe` 是全局参数，放在子命令前。部分系统的精简 FFmpeg 缺少 libass；如已安装完整构建，可显式选择，例如 `--ffmpeg /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`。不自动安装或替用户切换版本。

```bash
python3 scripts/media_tools.py --help
python3 scripts/media_tools.py --ffmpeg /path/to/ffmpeg --ffprobe /path/to/ffprobe render edit.json --output out/film-v1
```

输入必须是存在的本地文件。JSON 内媒体、字幕相对路径按该 JSON 所在目录解析；CLI 的输出相对路径按当前工作目录解析。输出父目录须已存在。输出文件/目录必须不存在，绝不覆盖源文件、原有导出或符号链接。中间文件在输出父目录的临时目录生成，失败时删除；失败审计为 `<output>.failed.json`，不会冒充成片。并发同名任务由 `<output>.media-tools.lock` 拒绝。正常结束会删除锁；进程被强制终止时须确认无任务运行后再手工移除残留锁。

每次成功输出包含 `report.json`（直接输出 JSON 的命令中该文件本身就是报告），记录命令参数、返回码、耗时、有限长度诊断、输出哈希和处理边界。报告不采集环境变量、凭据、任意媒体标签或字幕正文；**运行报告包含本地路径，只留在项目中，不应随开源包提交。** JSON 根字段和嵌套字段严格检查，未知字段会报错，避免拼错参数被静默忽略。

## 参数读取、抽帧和接触表

```bash
python3 scripts/media_tools.py probe media/source.mp4 --output out/probe.json
python3 scripts/media_tools.py frames media/source.mp4 --every 2 --count 48 --width 320 --columns 4 --output out/frames
```

`probe` 输出文件 SHA-256、时长、编解码器、宽高、像素格式、帧率、像素宽高比、旋转、声道及采样率；不代表完整解码。`frames` 以 `fps=1/every` 抽取 JPG，并由 FFmpeg `tile` 生成 `contact-sheet.jpg`。参数：`every` 0.04–3600 秒、`count` 1–500、`width` 16–4096、`columns` 1–20。预估接触表超过 8000 万像素会拒绝，需降低宽度或数量。帧号表示重采样网格，不能冒充原始帧精确时间码。抽帧和接触表不是全片观看证据。

## 场景切点与重复候选

```bash
python3 scripts/media_tools.py candidates media/a.mp4 media/b.mp4 --scene-threshold 0.3 --sample-fps 1 --max-samples 600 --near-mae 3 --output out/candidates.json
```

- 全文件 SHA-256 相同：可判为字节完全相同的文件；不自动删除。
- `scene_cut_candidates_s`：整段视频按 FFmpeg `scene` 指标取得的切点候选，阈值 0–1。闪光、叠字、淡变也可能触发。
- `sampled_frame_repeats`：每文件前 `max-samples` 个抽样画面，经 **32×32 灰度归一化** 后 SHA-256 相同的候选；不等于原始高分辨率帧完全相同。
- `adjacent_near_candidates`：仅比较相邻抽样帧；记录平均绝对像素误差 MAE，范围 0–255，`0 < MAE <= near-mae` 时列入。`near-mae=0` 关闭近似候选。
- `sample_frame_hashes` 保留每个样本的哈希和网格时间，便于复核。`sample-fps` 0.01–10，`max-samples` 2–2000；达到上限会标记 `sample_limit_reached`。场景扫描不受此抽样上限限制。

以上画面指标不能判断语义重复、科研装置是否相同、完整实拍边界或两个镜头是否可互换。静态科学图、片头、字幕都可能被报为重复或冻结。

## 实测字幕及可编辑标题层

```bash
python3 scripts/media_tools.py subtitles subtitle-timing.json --output out/subtitles
```

输入结构如下；所有时间单位为秒。`start/end/text` 必填，`end > start`，`text` 为非空字符串。必须先测得时间，工具不进行语音识别、字词对齐，也不按文本长度猜时长。

```json
{
  "width": 1920,
  "height": 1080,
  "font": "PingFang SC",
  "font_size": 48,
  "subtitles": [{"start": 0.6, "end": 3, "text": "这里放已核对的旁白字幕"}],
  "titles": [{"start": 0, "end": 2, "text": "第一章", "x": 960, "y": 180, "font_size": 72}]
}
```

根字段仅上述六项；`width/height` 默认 1920×1080，`font_size` 默认 48，字体默认 PingFang SC，可显式换为本机已安装字体。每条允许 `start/end/text/x/y/font_size`，坐标在画布范围内；指定位置使用中心锚点，不指定时字幕在底部、标题居中。`font_size` 8–400。换行用 JSON `\n`。不允许文本注入 ASS 控制语法，正文中的反斜线和花括号会转成全角字形。

输出：`subtitles.srt` 只含字幕；`layers.ass` 同时含 Subtitle、Title 两个独立样式和事件，可用字幕软件编辑位置/样式。标题不被混进旁白 SRT。ASS 使用百分之一秒精度，SRT 使用毫秒精度。烧录后的视频中文字不可再分离；可编辑层是旁存 ASS，不是某个 NLE 的原生工程。

## 明确配方剪辑与章节导出

```bash
python3 scripts/media_tools.py render edit.json --output out/film-v1
```

可复制 [`assets/edit-recipe.example.json`](../assets/edit-recipe.example.json) 到自己的项目，替换占位素材路径并创建上面的 `subtitle-timing.json`。模板不会附带真实素材。

根结构仅允许：

| 字段 | 规则 |
|---|---|
| `version` | 1，可省略 |
| `canvas` | `{width,height,fps,background}`；默认 1920×1080、25 fps、black；尺寸为 16–7680 偶数，fps 1–120；background 仅 black / white / `#RRGGBB` |
| `clips` | 1–500 个镜头，依次硬切拼接 |
| `subtitles` | 可省略；上节字幕 JSON 的本地路径；画布必须匹配成片 |
| `audio` | 可省略；下节音频配方内嵌对象，路径仍以 edit.json 所在目录为准 |
| `chapters` | 可省略；`[{"id":"C01","start":0,"end":4}]`，按成片时间轴精确重编码切片 |

视频镜头：`{path,kind:"video",in,out,audio,volume,fade_in,fade_out,chapter_id}`。`path/out` 必填，`in` 默认 0，源区间不得越界；`audio` 默认 true（无音轨时补静音）；`volume` 默认 1，允许 0–8。静图镜头：`{path,kind:"image",duration,audio,volume,fade_in,fade_out,chapter_id}`，必须用 `duration`，不可混用 `in/out`。支持 PNG/JPEG/WebP/BMP/TIFF 单幅静图；不将视频伪装成无限循环静图。

静图和视频都按**显示宽高比等比缩放、补边、统一方形像素**，不裁切，不拉伸。视频旋转由 FFmpeg 正常处理。`fade_in/fade_out` 默认 0，分别对该镜头的视频和源音频做到黑/从黑及音频渐变，不得超过镜头时长；这不是重叠交叉转场。镜头时长舍入到最近的完整输出帧，报告同时列请求时长、实际起止时间和帧数；字幕与章节区间应按该实际时间轴指定。

`chapter_id` 仅用于镜头报告分组；实际章节输出由 `chapters` 显式区间决定。章节 ID 为唯一的 1–60 位 ASCII 字母/数字/下划线/连字符，避免把自然语言标题作为文件路径。章节时间区间须在成片内。

输出包含 `film.mp4`（H.264 / yuv420p / AAC）、可选 `C01.mp4` 等章节切片、可选 `layers.ass/subtitles.srt` 和报告。无字幕、无音频替换时仍输出标准化编码；不是无损封装或专业母版方案。没有多轨 NLE、动态运镜、光流补帧、AI 扩图、图像语义匹配或任意滤镜字符串入口。

## 音频间隔、BGM 起铺、压低及保时静音

```bash
python3 scripts/media_tools.py audio audio.json --output out/audio-v1
```

```json
{
  "duration": 7,
  "tracks": [
    {"path": "media/music.wav", "in": 0, "duration": 7, "at": 0, "loop": true, "role": "bgm", "volume": 0.18, "fade_in": 0.2, "fade_out": 0.6, "duck": {"volume": 0.3, "intervals": [[0.6, 6.4]]}},
    {"path": "media/voice.wav", "in": 0, "duration": 5.8, "at": 0.6, "role": "narration", "volume": 1}
  ],
  "mute": [[3.2, 3.35]]
}
```

根允许 `duration/tracks/mute/keep_clip_audio`；独立 audio 命令必须给 `duration`（0.02–86400 秒），内嵌 render 可省略并使用实际成片时长，显式提供时必须相同。`tracks` 为 1–100 项：

| 字段 | 规则 |
|---|---|
| `path` | 必填，本地带音轨媒体 |
| `in` | 源起点，默认 0；不得超出源时长 |
| `duration` | 必填，截取/循环时长，至少 0.02 秒 |
| `at` | 放到输出时间轴的位置，默认 0；`at + duration` 不得超过总时长 |
| `volume` | 线性倍率，默认 1，范围 0–8 |
| `loop` | 默认 false；显式 true 时允许循环短 BGM，循环接缝仍须听检 |
| `role` | `narration/bgm/effect`，默认 effect；仅报告标签，不自动推测处理 |
| `fade_in/fade_out` | 单条音轨首尾渐变秒数，默认 0，不得超过该轨时长 |
| `duck` | 可省略；`{volume:0.3,intervals:[[a,b]]}`，在指定输出时间段乘以 0–1 音量倍率 |

`at=0` 的 BGM 和 `at=0.6` 的旁白形成 0.6 秒先铺音乐；多句旁白分别设置 `at` 即保留明确间隔。Duck 使用给定区间逐样本计算，**不是**自动语音识别或自动侧链压缩。重叠 duck 区间会重复乘以倍率，应避免无意重叠。`mute` 在混音后将指定输出时间段逐样本置零，保留总长度，不移走杂音片段；如只想修一条原始音轨，先单独用 audio 配方处理该轨，再将导出的 `mix.wav` 加入最终配方。突变静音边界仍可能需要人工听检并调整位置。

多轨按显式增益相加、不自动按轨数缩小，最后限幅至 0.95 并补偿限幅延迟；不等于 LUFS 响度标准化。输出为 48 kHz 双声道 24-bit PCM `mix.wav`。内嵌 render 默认以这份混音替换原片音频；`keep_clip_audio:true` 则把已剪辑的源音轨和新混音相加再限幅。独立 audio 命令没有原片音轨，不能使用 `keep_clip_audio:true`。

## 完整解码与技术候选检查

```bash
python3 scripts/media_tools.py qc out/film-v1/film.mp4 --black-min 0.2 --freeze-min 1 --output out/qc.json
```

QC 对全部视频/音频流完整解码，启用错误即失败；返回 `full_decode_passed:true` 才表示本次解码完成。报告保留流参数、哈希、黑帧/冻结元数据候选。黑场像素阈值为 0.10，冻结噪声阈值为 -60 dB；两种最小时长可配置，范围 0.01–3600 秒。不存在视频流时仅做音频完整解码。

完整解码仍不包含播放器观看、字幕缺字/溢出、旁白听感、口型同步、科学标签正确性、装置完整性、甲方或用户验收；报告显式保留 `semantic_acceptance:false`、`player_acceptance:false`。静图冻结、设计黑场、淡入淡出要人工区别。成片仍须用实际播放器看、听并记录实际验收结果。

## 本地回归

```bash
python3 -m unittest discover -s tests -p 'test_media_tools.py' -v
```

测试只在临时目录生成彩色视频、静图和正弦音，执行七种命令与 2.2 秒短片端到端验证，检查实际解码像素是否保持竖图比例、字幕层、章节输出、完整解码、候选检测、旁白间隔、duck 音量、静音保时、原始输入哈希和失败不留成功包。无外部模型、无网络、无真实项目素材。可用 `MEDIA_TEST_FFMPEG` / `MEDIA_TEST_FFPROBE` 指定已安装软件；测试会优先使用已存在的 Homebrew 完整构建。测试是技术自动验收，不冒充人的观看或听感验收。
