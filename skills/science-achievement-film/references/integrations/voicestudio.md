# VoiceStudio：旁白与本地转写

接口按VoiceStudio的本地兼容API整理；运行时仍须检查实际服务、字段和模型状态。以下步骤独立包含本流程所需调用，不需要另读外部skill。

## 输入与预检

输入为审定旁白正文、术语读音表、目标时长、同一真实声音profile。先 `GET http://127.0.0.1:3900/health`，再 `GET /v1/audio/voices`。响应的 `voices[].type=profile` 与 `voice_id`才是保存声音；`alloy/ash/...`等 `openai_alias`映射到当前默认引擎声音，不保证多段一致。响应的 `engines`/健康信息用来核对实际引擎和安装状态，不按目录名猜已安装模型。

服务离线先检查现有应用与日志；在当前前台授权内打开已安装的VoiceStudio应用，不另装第二后端。缺模型记录名称/体积/用途，按既有下载授权处理。音色克隆只用用户有权使用的参考；本流程优先现成profile，无需重复创建。

## 精确文件输出

先保存JSON文件，避免把长旁白转义拼进shell。以下是本机真实REST字段：

```json
{"model":"omnivoice","input":"本次审定的十五至三十秒样片正文。","voice":"实际voice_id","language":"zh","response_format":"wav","speed":1.0}
```

`input`上限4096字符；单段仍按语义和呼吸分割。`voice`填写实际profile ID，不传示例文字。保持model/voice/language/speed一致；时长不合先压缩审定文字，不加速旁白凑时长。模型缺失时不让示例model隐式触发未经批准的下载。

```sh
curl --fail --silent --show-error --max-time 600 \
  -H 'Content-Type: application/json' --data-binary '@/项目/work/tts-request.json' \
  'http://127.0.0.1:3900/v1/audio/speech' --output '/项目/work/tts-candidate.part'
ffprobe -v error -show_entries format=duration:stream=codec_name,sample_rate,channels -of json '/项目/work/tts-candidate.part'
ffmpeg -v error -i '/项目/work/tts-candidate.part' -f null -
```

只在HTTP成功、非JSON错误体、有效音频与全长解码通过后把候选重命名为唯一新 `.wav`。对长任务先登记；超时后检查应用任务/历史和已有输出，不能直接再发同一个POST。保留错误候选供排障但不交付。

如本次MCP已暴露VoiceStudio工具，可调用其当前名字下的 `list_voices({})` / `check_health({})`，然后使用已核对的实际schema：

```json
{"text":"本次审定正文","language":"zh","profile_id":"实际ID","speed":1.0,"steps":16}
```

对应工具语义为 `generate_speech`；`steps`源端说明8草样/16均衡/32质量候选，并非质量保证。输出文件模式 `OMNIVOICE_MCP_OUTPUT_MODE=files`、已有的 `OMNIVOICE_MCP_BASE_PATH`限定范围；不要为了文件路径临时放宽安全根。不要把整段WAV Base64回灌上下文。

## ASR与时间码

先确认现有ASR模型。需要字幕时间码，优先本地REST multipart：

```sh
curl --fail --silent --show-error --max-time 600 \
  -F 'file=@/项目/outputs/narration.wav' -F 'model=whisper-1' \
  -F 'language=zh' -F 'response_format=verbose_json' \
  'http://127.0.0.1:3900/v1/audio/transcriptions' \
  --output '/项目/work/narration-transcript.json'
```

`whisper-1`是兼容模型别名，不据此声称运行的是OpenAI云服务或特定Whisper权重。`response_format`支持 `json/text/verbose_json/srt/vtt`。`timestamp_granularities[]=word`仅在当前引擎支持时使用。MCP `transcribe({audio_path,language})`要求路径在既有base内，适合只要文本；它不等于有SRT时间码。

逐句比对审定正文、数字、单位和专名；ASR回转录是辅证，必须实际试听15–30秒样片后才批量生产。每段检查截断、静音、爆破音、重音、同音误读与接点。母版WAV保留；最终混音单独处理，原音乐/环境声不随转写被替换。记录file_probe、decode、ASR、听感四类证据，未听验不得写听感通过。
