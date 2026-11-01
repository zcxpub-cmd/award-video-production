# Seedance 2.0：小镜头生成与任务恢复

本方法依据Seedance提示词的公共输入概念与Ark HTTP接口独立编写，未复制上游实现。内置 [seedance_http.py](seedance_http.py) 只依赖Python标准库；本包测试只模拟HTTP，未执行付费生成。模型ID、服务区域、账号可用性、分辨率和时长支持需任务当时核对，不能用示例保证当前账号权限。

## 先定镜头合同

输入：审定事实/原图、参考媒体授权、实际开场状态、该镜头唯一动作、终止状态、镜头运动、光源、时长/画幅、禁止变化项、批准的费用范围。完整科研装置应遵守项目原始实拍要求；AI仅用于已允许的局部特写、示意或补充段，不冒充原装置实拍。

压缩提示词仍保留“参考的用途→主体固定项→动作及终点→单一运镜→实际光源→不变约束”。续镜写明上一段已完成动作和本段起止状态，避免重演或提前发生后段事件。自然光源和材质要具体；“高级/震撼/电影级”不能替代动作与构图。参考标签必须绑定到真实上传项；不同接口的 `@Image1` 等标签并不自动绑定本地文件。

## 请求文件

本包不内置凭证路径或账号。用户提供自己获准使用的模型ID及密钥文件；不要把密钥写进请求、命令参数值、聊天或发行包。内置客户端只接受 `https://ark.cn-beijing.volces.com/api/v3` 这个官方API base及任务路径，发送函数再次检查完整URL。自定义代理、其它区域、任意端口和重定向均不支持；扩展区域需先审核并修改明确白名单，不通过请求内容放宽。

```json
{
  "model": "ACCOUNT_APPROVED_MODEL_ID",
  "content": [
    {"type":"text","text":"保持参考图的几何、接口数量与标签位置，仅缓慢推进至已批准的局部细节；侧上方柔光；不生成文字，不改变结构。"},
    {"type":"image_url","image_url":{"url":"https://AUTHORIZED_REFERENCE_HOST/frame.jpg"},"role":"first_frame"}
  ],
  "ratio":"16:9","duration":5,"resolution":"720p",
  "watermark":false,"generate_audio":false
}
```

以上占位值必须替换。文本生成可删除image项。末帧用 `role=last_frame`，参考图片用 `reference_image`；视频/音频的type分别 `video_url/audio_url`、role为 `reference_video/reference_audio`。实际支持组合由当前模型决定。可使用 `data:<mime>;base64,...`传本地参考，但它会把文件内容上传；这不是本地推理。将私有文件限制为本机处理的项目不得使用该路径。

## 内置执行顺序

```sh
python3 references/integrations/seedance_http.py validate --request '/project/work/request.json'
```

验证只检查结构、打印请求指纹；不联网。达到用户既有生成/外传/费用授权后才调用：

```sh
python3 references/integrations/seedance_http.py submit \
  --request '/project/work/request.json' --journal '/project/work/seedance-task-v01.json' \
  --key-file '/private/config/seedance-api-key' --base-url 'https://ark.cn-beijing.volces.com/api/v3' \
  --allow-billable
python3 references/integrations/seedance_http.py query \
  --journal '/project/work/seedance-task-v01.json' --key-file '/private/config/seedance-api-key' \
  --base-url 'https://ark.cn-beijing.volces.com/api/v3'
```

协议为 `POST {base}/contents/generations/tasks` 和 `GET {base}/contents/generations/tasks/{id}`，Authorization只在内存构建。一次submit只POST一次；先保存未知状态，再发请求，收到真实ID立即保存。相同journal拒绝重复提交，网络超时保留unknown并要求对账。`--allow-billable`是代码开关，不能替代用户授权。客户端不在stdout/stderr打印密钥、参考Base64、完整请求、服务原始错误或签名下载URL。

单次query不长轮询；按服务建议间隔查原ID，每轮更新任务账本。`succeeded`后追加 `--download '/project/outputs/shot_v01.mp4'`下载到新文件；最多1GiB，失败保留 `.part`，不覆盖旧文件。下载只接受官方文档中的 `ark-content-generation-cn-beijing.tos-cn-beijing.volces.com` 或 `ark-acg-cn-beijing.tos-cn-beijing.volces.com` 两个精确主机，不使用通配域名、其它端口或重定向；下载请求从不携带API密钥/Authorization。返回其它主机时停止并核对官方来源，不能自动扩大白名单。下载不证明MP4有效：另做ffprobe、全段解码、首中末和运动细节检查，再记录素材墙状态。

## 故障与返工

400/参数错误先查实际模型和字段；401/403先检查凭证/权限，错误正文不要回灌；超时/断线先查journal和服务历史，禁止把不确定POST自动再发。服务明确failed时保留原ID与请求SHA，按失败原因只改一个变量，再生成唯一新任务。降低时长/分辨率或压缩提示词也算新的可能收费任务，不能假设免费重试。画面变形先检查参考约束与动作复杂度；科学几何错误退回Blender/FreeCAD锁结构或换实拍，不能只靠增加形容词继续堆次数。
