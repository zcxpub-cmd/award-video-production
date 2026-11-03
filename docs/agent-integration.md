# 接入智能体

能启动本地进程的宿主可以通过命令行调用本项目。Codex 可以继续使用原有插件或 Skill。其他宿主可将以下 JSON 入口注册为工具。宿主负责管理进程权限，并决定智能体可以读取哪些项目路径。

在解压后的仓库根目录运行：

```sh
python3 skills/science-achievement-film/scripts/agent_tools.py list
printf '%s\n' '{"source":"./media"}' | python3 skills/science-achievement-film/scripts/agent_tools.py invoke inventory
```

| 工具 | 参数 | 功能 |
| --- | --- | --- |
| `inventory` | `source` | 按文件元数据盘点本地素材目录 |
| `check` | `project` | 检查工程 JSON，并返回校验发现 |
| `probe` | `input` | 用 FFprobe 读取本地媒体的流和格式参数，需要 PATH 中的 FFmpeg 和 FFprobe |

调用时把一个 JSON 对象写入标准输入并关闭输入流。标准输出返回一个 JSON 对象。用 `ok` 判断成功，用 `exit_code` 查看底层工具的退出状态，用 `report` 获取报告。工程校验发现错误时仍可能返回报告。参数、执行或超时错误可在 `error` 中查看。相对路径以宿主为进程指定的工作目录为准。该入口对原工程及原素材只读，报告经临时目录返回给宿主。

命令行接入只定义工具发现、输入和结果。可在支持本地进程的框架中用参数数组和标准输入调用它。渲染、字幕、混音和归档仍可使用现有命令，使用前由宿主确认所需依赖与文件访问范围。[完整命令与工作流](../skills/science-achievement-film/references/quickstart.md)
