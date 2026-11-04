# 开源工作台源码

发行包已附前端构建结果，使用者可从发行包根目录运行平台启动器。首次启动需要 Python 3.10 或更新版本和网络。安装器在当前用户的专用 Python 环境安装依赖，优先使用现有 FFmpeg，需要时通过固定版本的 [static-ffmpeg](https://github.com/zackees/static_ffmpeg) 准备 FFmpeg 与 FFprobe。启动器只监听本机回环地址。工程数据保存在单独的开源工作台目录。

工作台和命令行素材审核墙共用公开封面素材。工作台素材库、剪辑工程与旧审核墙清单分别保存。已有工程交接包可通过项目页导入。

## 从源码构建

在本目录下运行：

```sh
cd frontend
npm ci
npm run build
npm test
cd ..
python3 launch.py
```

前端依赖和版本由 `frontend/package-lock.json` 锁定。已构建的前端包含 React、React DOM、Scheduler 和 Phosphor Icons，许可证随前端源码附带。演示音频为程序生成的低音量试音。提示词库只收录项目原创模板，封面素材来源见开源仓库的素材清单。

## 模型和生成

手工剪辑、按素材顺序一键成片、媒体渲染及技术检查可直接运行。AI 对话剪辑、画面抽样和智能编排需要本机 Ollama 模型，配置入口为「偏好与配置 → 模型与执行」。模型产出的编辑建议经校验，由用户确认后保存到工程。视频生成需使用者配置有权限的 Seedance 服务和密钥，并批准单次收费请求与提示词传输。
