# filmkit schema 1.0

`filmkit.py` 使用 Python 3.9+ 标准库；`inventory --probe` 可选调用已安装的 `ffprobe`。不联网、不修改素材、不生成成片。输出 JSON 保留中文。返回码：`0` 命令完成或机器条件通过，`2` 检查发现错误，`1` 文件/参数执行失败。`needs_review` 也返回 `0`，**不能据此认定交付验收通过**。

## CLI

```bash
python3 scripts/filmkit.py init '/tmp/科技成果片演示' --chapters 10 --max-seconds 600 --fps 25
python3 scripts/filmkit.py inventory '/path/to/授权素材' --out '/tmp/inventory.json'
python3 scripts/filmkit.py inventory '/path/to/本地素材' --out '/tmp/probed.json' --probe --timeout 15
python3 scripts/filmkit.py check '/tmp/科技成果片演示/project.json' --out '/tmp/check-report.json'
```

`init` 可创建新目录，但不会覆盖已有 `project.json`；章 ID 为 `C01` 等，标题口播与单位口播初始 ID 分别为 `C01-S01`、`C01-S02`。后续增删不应重排已用 ID。模板中空文案、未知时长均待补齐，初次 `check` 应失败。`inventory`、`check` 的输出父目录须已存在。报告可更新，但不能覆盖项目文件或已列明的引用源文件；输出需以 `.json` 结尾。

## 时长与文案

- 顶层：`schema_version: "1.0"`、`title`、正数 `fps`、`max_seconds`、`runtime`、非空 `chapters`、`approved`、`revision_queue`。
- `runtime.definition` 固定为 `sequential_nonoverlapping_blocks`。`opening_s`、`intro_music_standalone_s`、`ending_s`、`global_wait_s` 是互不重叠的独立段，均须显式填写。确实没有该段填 `0`；未知填 `null`。
- 叠在口播下的背景音乐不另计时；独立播放的引入音乐写入 `intro_music_standalone_s`。开头、结尾的整体时长已含其内部口播或音乐，不能重复列入章节。
- 每章：`id`、完整 `title`、官方 `units` 字符串数组、`speak_title`、`speak_units`、`protect_title_as_phrase`、`protected_terms` 精确字符串数组、`narration` 句子数组、四个时长字段、`picture_plan`。三个开关必须是 JSON 布尔值。
- 新模板默认 `speak_title: true`、`speak_units: true`。前者要求恰好一条 `role: "title"`，后者要求至少一条 `role: "units"`。**兼容旧 schema 1.0**：未填写开关时，`speak_title` 缺省 `true`、`speak_units` 缺省 `false`，保持旧配置原有要求；建议旧项目显式补齐开关。`protect_title_as_phrase` 缺省 `true`。
- `speak_title: false` / `speak_units: false` 表示屏显但不要求口播：完整屏显 `title`、`units` 仍必填；相应未口播项不要放入 `narration`，不要伪造零秒或静音 TTS。正文已录语句按实际列表填写。两个开关都关闭且完全无口播时，可以明确写 `narration: []`，画面使用有具体用途的过桥条目，播放时间写入非重叠画面/等待段。若开关关闭却仍留下口播条目，会列设置冲突待审，脚本依然计入其真实测得时长，不静默跳过。
- 每句：`id`、`role`（如 `title` / `units` / `body`）、`narration_display`（该口播对应的书面/字幕文案）、`narration_tts`（实际朗读文案）、`voice_duration_s`、`voice_duration_basis`、`voice_path`、`playback_rate`、`tts_segments`、`subtitle_cues`。存在标题口播时，其 `narration_display` 必须精确等于章标题。单位名完整性仅检查非空；名称真伪和归属须对官方材料人工核对。
- 口播时长仅接受 `voice_duration_basis: "measured_audio"` 或 `"measured_timeline"`，且每条实际口播的时长必须 **大于 0**。模板 `unmeasured` 不参与已知总时长。数值必须来自实际音频或时间线测量，不能按字数估算后伪标为 measured。`voice_path` 为证据路径；未提供会列人工待审，脚本本身不重新测量音频，也不自动证明测量声明真实。
- `playback_rate` 必须为 `1`，超时应压缩文字或调整内容。脚本不加速、不生成音频、不修改计划。
- 章时长 = `sum(narration[].voice_duration_s) + transition_duration_s - transition_overlap_s + picture_extension_s + wait_s`。
- `transition_duration_s` 是本章转场整体时长；`transition_overlap_s` 是其中已与本章口播重合的部分，例如标题口播覆盖转场。重合量不能超过转场或本章口播。`picture_extension_s`、`wait_s` 只计未与前述部分重叠的延展/等待，不可重复计入。
- 片长 = 四个 `runtime` 独立段 + 各章时长。任何一项未知，总时长为 `null` 且检查失败；未知不能按零放行。此公式依赖填写者正确标定重合区间，不能代替时间线验收。

## 明确的断句边界

`tts_segments` 表示实际分开发送或生成的 TTS 段，`subtitle_cues` 表示实际字幕显示块。每项为 `{ "start": 0, "end": 6, "text": "深海观测系统" }`，从零计、左闭右开，按 **Python Unicode 字符索引**，不是 UTF-8 字节或 JavaScript UTF-16 索引；`text` 可省略，但提供后须与区间精确一致。数组须按序完整覆盖对应句子，不能缺口、重叠、越界。

需口播或实际存在口播的章标题，默认作为完整保护词。用户明确要求标题某处停顿时，可以设置 `protect_title_as_phrase: false`，再在 `tts_segments` / `subtitle_cues` 中声明实际边界；此例外仅取消隐式整标题保护，**不会取消 `protected_terms` 内任何显式术语保护**。例如 `高精度卫星观测系统` 在“卫星”后停顿，可用 `0..5`、`5..9` 两段并关闭整标题保护，同时继续保护 `高精度`、`观测系统`；若仍把完整标题列入 `protected_terms`，跨段仍会报错。例外会列 `title_phrase_protection_overridden` 待审，需按用户要求试听。

脚本仅在精确定位保护词后，检验该词是否跨越**已声明的实际句子/片段边界**；不会把空格、标点、标题排版或模型猜测当成断句证据。一个完整块可以写为 `0..len(text)`。未提供实际分段标记待审；术语在朗读稿中改为同音字、读音标记等而无法精确定位时，只标待审，不武断报告被拆词。即使区间完整，也仍须试听多音字、停顿、数字和单位。

## 画面计划与素材

`picture_plan` 每个镜头需填写：

- `sentence_ids`：引用本章句子 ID；若不绑定口播，必须使用 `kind: "bridge"` 并填写具体 `purpose`。
- `source`：本地文件路径；相对路径从 `project.json` 所在目录解析，不接受 URL。
- `in_s`、`out_s`：视频素材明确入出点，`0 <= in_s < out_s`。静态图片使用 `0..计划呈现秒数`，这里的区间不表示文件内时间轴。

每句口播至少要被一个镜头引用。同一规范化源路径上重叠的区间会列 `source_interval_reused` 待审（跨章也检查），不擅自判断合理重复是否违规。不同文件拷贝、画面内容相似度、源素材实际长度、字幕屏幕布局和音画语义均不自动证明。句子绑定只证明引用结构，每镜都列语义待审；完整装置身份、实拍边界和授权需按技能人工核查。

`inventory` 默认只读文件系统元数据：不计算素材哈希，不打开媒体内容，不调用 ffprobe。跳过符号链接且不递归；发现 macOS `UF_DATALESS`（`0x40000000`）或 `.icloud` 占位名时不打开内容，离线目录不递归。在不支持 `st_flags` 的平台记录 `flags_supported: false`。

| status / availability | 能证明什么 |
| --- | --- |
| `decode_unverified` / `metadata_only` | 仅元数据存在，不能确认媒体可用 |
| `placeholder` / `placeholder` | 检测到云端占位，未读取内容 |
| `probe_ok` / `available` | 显式 `--probe` 后 ffprobe 读到媒体流元数据 |
| `read_error` / `unverified` | 读取失败、探测失败或超时，见错误字段 |
| `symlink_skipped`（issues 中） | 未跟随该符号链接 |

`probe_ok` 仍是 `decode_verified: false`，不等于完整解码、播放器验收或素材授权。没有 ffprobe 时保留 `decode_unverified` 并记录 `ffprobe_unavailable`。显式 `--probe` 会读取本地内容；无法通过标志识别的第三方云盘占位仍可能被系统取回，因此默认不使用该选项。

## 冻结与修订

`approved` 为显式批准文件快照数组：`{ "id": "OPENING", "path": "opening-approved.mp4", "sha256": "64位小写SHA256" }`。快照必须来自确认过的版本。检查时只对这些显式列明的文件做流式 SHA-256 实比，并检测读前后大小、修改时间、inode 是否变化；不存在、占位或哈希变化均失败。路径可以指向批准的开头/结尾、文案文件、项目配置快照等。没有快照只标保存状态未验证。

`revision_queue` 为 `{ "component_id": "OPENING", "reason": "明确拟改内容" }` 数组，可引用现有章/句ID、OPENING/ENDING或已冻结组件，不要求未定稿章节先获批才能登记修改。排队本身不代表获批，也不能豁免冻结检查；应按当前用户指令及既有授权执行，不重复索要已获得的批准。此脚本不生成新哈希去覆盖旧快照，不改动任何冻结组件。

## 小样本

下面配置在提供真实本地 `voice.wav`、`shot.mp4` 后，声明片长为 **12 秒**。仍需核实测量依据、画面含义与人工验收；示例文字不代表任何真实成果。`approved` 暂空，所以保持待审。

```json
{
  "schema_version": "1.0",
  "title": "演示片",
  "fps": 25,
  "max_seconds": 600,
  "runtime": {
    "definition": "sequential_nonoverlapping_blocks",
    "opening_s": 3,
    "intro_music_standalone_s": 2,
    "ending_s": 3,
    "global_wait_s": 0
  },
  "chapters": [{
    "id": "C01",
    "title": "深海观测系统",
    "units": ["示例单位（需换为官方全称）"],
    "speak_title": true,
    "speak_units": false,
    "protect_title_as_phrase": true,
    "protected_terms": ["深海观测系统"],
    "narration": [{
      "id": "C01-S01",
      "role": "title",
      "narration_display": "深海观测系统",
      "narration_tts": "深海观测系统",
      "voice_duration_s": 2,
      "voice_duration_basis": "measured_audio",
      "voice_path": "voice.wav",
      "playback_rate": 1,
      "tts_segments": [{"start": 0, "end": 6}],
      "subtitle_cues": [{"start": 0, "end": 6}]
    }],
    "transition_duration_s": 2,
    "transition_overlap_s": 1,
    "picture_extension_s": 1,
    "wait_s": 0,
    "picture_plan": [{
      "sentence_ids": ["C01-S01"],
      "source": "shot.mp4",
      "in_s": 0,
      "out_s": 4
    }]
  }],
  "approved": [],
  "revision_queue": []
}
```

## 报告与边界

`check` 的 `runtime.total_s` 是依据声明测量数值计算出的计划时长，并非渲染成片实测。`status` 可能为 `fail` / `needs_review` / `machine_checks_pass`；`machine_checks_pass` 只表示本工具已实现条件无错误，`human_acceptance` 始终为 `not_verified`。每项 `findings` 含 `level`、`code`、`location`、`message`。

机器检查覆盖格式、必要字段、明确边界、算术、局部引用、显式文件快照。它不联网、不运行渲染、不执行项目内容、不测语义、不写正式成果，也不会把统计成功、ffprobe 成功或本报告成功升级为 WPS/QuickTime/DaVinci 实际验收。
