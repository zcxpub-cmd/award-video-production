# DaVinci Resolve：实际接口、剪辑与交付

本方法按 `davinci-resolve` MCP接口独立整理，执行时以实际可用工具schema为准。schema是调用约定，不代表当前机器的版本、Studio授权、模型安装或效果质量。不要把工具数当AI通过数。本包不内置第三方服务器、私有工程、原生控制脚本或历史验收记录。

## 接入与明确对象

1. 发现当前工具；调用 `mcp__davinci_resolve__status({})`，记录版本、工程、时间线和页面。
2. 写入前对照任务授权与当前工程名。需要切工程，使用 `load_project({project_name,current_project_name})`；创建新工程用 `create_project({project_name,current_project_name,frame_rate:25})`，新名不可撞已有工程。工具要求保存当前工程时，保存失败即停止切换。
3. `import_media({project_name,absolute_paths:[本次本地文件绝对路径]})`，核对请求数、导入数、实际返回素材ID/路径，再 `media_pool_info({project_name,limit:20})`。不使用历史ID或只按同名猜测。
4. `create_timeline({project_name,timeline_name,clip_ids:[本次返回ID]})`，按显式ID顺序建立唯一新时间线；空列表会建空线。`timeline_info({project_name,timeline_name,limit_per_track:30})`核对轨道、片段、起止帧、字幕、标记。素材ID与1起始的时间线片段索引不能互换。
5. 需要激活时间线，用 `timeline_select({project_name,timeline_name})`读回名称。SDK不主动切前台不等于界面绝不会改变，渲染可能切Deliver页面。

若会话没提供这些工具，先发现当前已连接的Resolve MCP并读取真实schema。不要编造同名HTTP端点，不自动安装第二套服务，不绕开工具guard。可用标准SDK制作的本地桥接由用户配置，本包没有通用任意Python执行器。

## 本流程相关的AI调用

以下只是当前schema的最小参数示例，P/T/clip_id等必须替换为本次实读值。若工具说明限制 `Codex_*`测试工程/时间线，保留限制；不能通过改名或移除guard扩展到业务工程。先在获准独立副本完成同范围验证，再按工具允许范围使用。

| 需求 | 当前工具调用形态 | 验证与恢复 |
|---|---|---|
| 转录与字幕 | `transcribe_audio({project_name:P,clip_id,use_speaker_detection:false})`；`create_subtitles({project_name:P,timeline_name:T,language:"Chinese",chars_per_line:24})`；`timeline_info` | 重新确认当前language枚举；检查真实字幕文本、条数、起止帧，逐词核对科学名词，不能把转录true当准确率 |
| 人声隔离 | `voice_isolation({project_name:P,timeline_name:T,audio_track_index:1,enabled:true,amount:100})` | 保留同源同范围关闭/开启两个新输出；读回参数后试听人声完整性和伪影，不以响度变化判效果 |
| 竖版 | `timeline_set_resolution({project_name:P,timeline_name:T,width:1080,height:1920})`；`timeline_item_scaling({project_name:P,timeline_name:T,video_track_index:1,item_index:1,mode:"Fill"})`；`smart_reframe`用相同片段定位参数 | 属于受保护测试路线时不扩大；先做Fill基线，再与AI版比较主体边界/连续抖动，不能把去黑边当AI收益 |
| SuperScale | `super_scale({project_name:P,clip_id,mode:"2x Enhanced",sharpness:0.5,noise_reduction:0.5})` | 先查当前schema枚举；同编码输出比较真实边缘/纹理/闪烁，分辨率增加不证明恢复细节 |
| 重定时质量 | `timeline_item_retime_quality({project_name:P,timeline_name:T,video_track_index:1,item_index:1,process:"OpticalFlow",motion:"SpeedWarpFaster"})` | 当前工具只改算法参数，不改变速度、帧率或时长；必须核对基础时间线已正确，再逐帧查遮挡 |

Magic Mask依赖已配置的实际提示，不能编造点选API。已有Fusion空默认合成可用 `timeline_duplicate_test_template`复制，再 `fusion_ai_create_in_existing_comp`添加schema允许效果，`fusion_ai_inputs`读取实际Number输入后才 `fusion_ai_set_number`写值。必须同片段保存/重载读回节点、连接和参数；不将旧 `fusion_ai_create`任意从零路线当可靠持久化入口。效果名和input_id实时读，不能凭界面译名猜测。

前台初始化、菜单或设置需要使用当前有效授权；不复用旧时间窗/PID/坐标。先完成脚本、素材和副本准备，再需要当前前台时说明具体操作。工具返回 `isError=false`仍要解码 `content[].text`里的JSON，检查内层error、exit_code、api_success和readback，禁止忽略内层失败。

## 原生界面操作的共同入口

下列调色、稳像和包装是**操作指导，未在本包封装时实际运行验收**。现有MCP若没有对应动作，直接采用当前获准的GUI路线；不把界面参数名拼成假SDK调用。先保存当前工程，复制本次时间线或使用唯一命名的工作副本，记录原时间线、素材区间、输入/时间线/输出色彩设置、画幅和帧率。既有调色或关键帧先留基线，不复位整个用户工程。

界面输入前确认实际版本、产品授权、当前工程/时间线、选中片段和当前页面；再读实际控件名称、启用状态、范围和当前值。版本/语言导致路径变化时，从当前菜单与Inspector重新定位；没有看到目标控件就停止该项，不猜坐标。需要新增前台权限时先完成素材/副本/比较帧准备，说明本次页面、动作和时段；当前已成立的授权可继续使用。每项改变只作用于显式片段和新增节点/轨道。

## 调色：保真、曝光与镜头衔接

1. 在Color页选择工作副本中的实拍片段，打开Scopes，选择Waveform观察明暗分布，RGB Parade辅助判断通道偏色。先读示波器当前单位和项目色彩管理，不把HDR、Log或不同数据范围硬套同一黑白阈值。科学热图、伪彩图、荧光编码、图表及颜色图例单独标记为保护画面，不施加“统一风格”调色。
2. 在节点区通过实际显示的添加串行节点操作，建立独立的 `Balance`、`Exposure`、`Match`工作节点；名称是本任务组织约定，不要求固定数量。保留原输入/输出转换、既有LUT与连接，避免重复色彩转换。没有相机/源色彩资料时先查来源，不能凭偏灰猜Log配置。
3. 在 `Balance` 的Primaries中逐小步调整实际存在的Temperature/Tint，参考场景中确实中性的物体和同组实拍。RGB通道比较只针对该中性区域；不把彩色光源或有意带色的场景强行拉成全通道重合。没有可靠参考时保留原白平衡并标记待核，而非自动匹配到科学图示。
4. 在 `Exposure` 先用Offset处理整体亮度，再按需要小幅调整Lift/Gamma/Gain与对比度。每次只改一项，观察波形是否新增高光削顶/暗部堆死，同时查看装置刻度、玻璃内部和金属反光细节。曝光不足导致的噪声不能靠大幅提亮伪称恢复；回退最后一步或换实拍候选。
5. 在 `Match` 比较前后相邻镜头的中性背景、主体亮度与颜色。饱和度从当前值小幅调整，检查肤色、标签和实验指示灯是否失真；不要复制一个镜头参数到所有素材后宣称匹配完成。必要时保留不同光源的合理差异。
6. 固定同一帧逐个启用/禁用**本次新增节点**做A/B，再正常速度看整个片段与两侧剪点。记录节点值、比较帧和原/改截图；白平衡、曝光、匹配任一项没有可观察收益就关闭该节点。导出相同范围、相同编码的基线与候选，检查变化是否真实持久化，而非监看器或代理缓存差异。

以上工作顺序为本片保真策略；控件功能依据 [Blackmagic Design Color说明](https://www.blackmagicdesign.com/products/davinciresolve/color)，不是通用“正确数值”预设。原始数据彩图需要改变配色时，应回到原图作者/数据生成环节另行审定，不能在后期偷偷替换颜色语义。

## 稳像：只处理已确认的相机抖动

先用固定背景、装置直线和原始时间戳区分相机抖动、主体运动、正常推移、滚动快门、帧率顿挫与生成形变。后五类不能因“看着不稳”直接套空间稳像。选择含抖动的代表性短段，留同范围原片，并把装置边界、比例尺和标牌列为不可牺牲的检查点。

1. 在Edit页选中副本片段，打开实际Inspector中的Stabilization；记录当前模式、Camera Lock、Zoom、Cropping Ratio、Smooth、Strength。此处没有MCP写入配方，按已读到的界面控件操作。
2. 若当前版本提供 `Translation`，优先只试平移补偿。保留有意的相机移动，Camera Lock先关闭。对于界面确认范围为0–1的Strength，可从0.2–0.4的弱候选试起；这是本任务保守起点，不是官方保证或跨版本固定默认值。Smooth先保留当前值，观察后再单独小调。不要一开始用Perspective把装置边缘扭成稳定画面。
3. 为保护完整科研几何，先关闭自动Zoom，不以降低Cropping Ratio换取更多裁切。点击实际Stabilize分析后检查真实完成状态；只改变需要重算的选项时按界面要求重新分析。Camera Lock、Crop/Zoom和强度每次只改一项，保留前值。
4. 对比首/中/末与运动极端帧，逐帧查直线弯折、比例尺、标签、画边缺失，再正常速度看抖动是否减少且有意运动是否保留。关Zoom仍可能出现黑边或平移后的边缘损失，不能把它记作“零裁切”。若项目允许，可将整体等比缩小并留边以保护内容，再复查；不允许留边或完整形态不能保住时回退原片/换镜头。
5. 没有收益、几何变化、边缘不安全、分析失败或只改善局部时，禁用/复位**该片段此次稳像**，保留原节点、剪点和声音。不可用额外裁切或拉伸掩盖失败。成功候选另导出同范围视频，与原片A/B；稳像参数已读回不等于视觉通过。

Inspector中的稳像控件见 [官方Edit说明](https://www.blackmagicdesign.com/products/davinciresolve/edit)；Translation与其它分析模式的区分见 [官方编辑指南](https://documents.blackmagicdesign.com/UserManuals/DaVinci-Resolve-17-Editors-Guide.pdf)。该指南是版本化参考，实际操作始终核对当前软件；这里不复制旧界面坐标、默认数值或按键。

## 包装：标题、单位、Logo与字幕分层

1. 在Edit页核对轨道用途：底片保留在原视频轨；在其上新增标题轨、单位/Logo轨，字幕使用独立字幕轨。不要替换原底图或把正式名称烘焙进AI生成底图。轨道编号可按现有项目调整，记录名称、顺序和每层起止帧。
2. 从实际Effects Library的Titles选Text/Text+或已获准模板，放到上层轨道；先用基本文字完成可读版，再决定是否需要Fusion动画。Inspector逐项填审定文字、字体、字号、颜色和位置，单位/标点与来源稿核对。缺中文字体、缺字或模板缺插件时改用本机可用字体/基本Text，不把方框字导出交付。
3. 以交付方安全区为准打开Viewer实际可用的安全框；未给规格时，可先让关键信息离四边至少画幅10%作为**待确认排版假设**。该数值不是所有平台的合格标准。检查最长标题、机构全称、Logo和下方字幕同时出现的帧，移动/分行/减小字号时不拆开数值单位或科学名词。不能靠裁底片给标题腾地方。
4. 时间码来自实测旁白。现有SRT可从Media Pool导入后放入字幕轨并核对起止；实际菜单不同则按当前可见导入入口操作。自动字幕必须逐句校对，标题与机构名称不要因为旁白省略而从屏显层消失。
5. 需要入出场动画时，仅在文字/Logo层的Inspector对实际有菱形开关的Position/Opacity等参数打关键帧：在起帧记状态，移动播放头至明确结束帧再设终值。先做起/止两帧最小动作；进入曲线编辑器检查速度变化，避免意外过冲或文字在停留段漂移。参数无关键帧能力时用受支持的图层淡入淡出或静态标题，不调用假API。
6. 逐帧检查动画开始、停止、剪点及章节末尾，再正常速度看足够的完整阅读停留。单独隐藏新增包装轨核对底片完全保留，重新启用后核对层级与字幕不互挡。保留可编辑文字、旁挂字幕和项目文件；只有烧录成片而无可编辑层时，不声称提供了可编辑包装工程。

Titles、Inspector和关键帧操作依据 [官方Edit功能说明](https://www.blackmagicdesign.com/products/davinciresolve/edit)；科学对象保护、安全边距初值与审核顺序是本包针对成果片的制作规则。若当前工具/版本缺少这些控件，停止对应动画，交付可审核静态候选并记录缺口，不把未实现包装记为完成。

## 原生修改后的保存、重开与Deliver

保存当前工作副本，再在既有授权范围内切出并重新载入；核对同一时间线、同一片段的节点连接/数值、稳像设置、轨道顺序、文字和关键帧。界面看到参数还在仅计持久化证据。读不到变化时保留候选和基线，检查保存结果与实际加载对象，禁止重复覆盖原工程来试错。

在Deliver核对新输出目录/唯一名称、范围是整条时间线还是明确In/Out、分辨率/帧率/编码、音轨以及字幕是烧录还是独立文件；按用户合同选择，不继承上次任务的未知预设。先渲染代表段验证色彩、稳像边缘、文字字体和同步，再输出正式全片与分项片。只提交本次新任务，不启动或删除用户其它队列项。完成状态、目标文件、全段解码、正常速度看听和用户接受分别记录；不把Render Complete当最终内容验收。

## 渲染、持久化与成品

```json
{"project_name":"ACTUAL_PROJECT","timeline_name":"ACTUAL_TIMELINE","absolute_output_dir":"/project/outputs","output_name":"film_v01","burn_in_subtitles":false}
```

当前 `render_start`固定MP4 H.264、1920×1080、25fps、AAC；只有交付合同相同才使用。竖版/其它时间线格式用 `render_start_timeline_format`，但保留其当前测试工程guard。需要4K而当前工具不支持时不能把1080p输出命名成4K；准备正确工程设置并走当次允许的其他渲染入口。

每次只启动本次新job，保留旧队列。`render_status({project_name:P,job_id:真实ID})`查询本次ID；记录完成状态和真实文件，而非仅AddRenderJob成功。超时后先查同ID，不再启动第二job。

保存用 `save_project({project_name:P})`，新DRP用 `export_project({project_name:P,absolute_drp_path:新路径,with_stills_and_luts:true})`；DRP不等于媒体归档。需要验证持久化时保存→切出→重新载入同工程→读同时间线/片段。保留原项目、源文件和旧输出。

```sh
ffprobe -v error -show_entries format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels -of json '/project/outputs/film_v01.mp4'
ffmpeg -v error -i '/project/outputs/film_v01.mp4' -map '0:v:0?' -map '0:a:0?' -f null -
```

再做文字/Logo/字幕边距、完整装置、接点、黑场、闪帧、冻结、响度和同步检查。播放器从头到尾运行是播放证据，实际看/听到的内容另记；没有观察的内容不写验收通过。若进程/渲染失败，保留原包、局部文件与错误摘要，定位输出路径、编码、空间、工程状态后再安排唯一新候选。
