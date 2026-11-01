# 几何、资料页、OCR与WPS复核

本页为独立操作配方，依赖已安装的公开软件接口，不捆绑程序、模型或第三方skill实现。参数、文件和输出全部属于本次项目；示例数值是软件检查示例，不能当成真实科研装置尺寸。

## Blender锁几何与相机

输入需包含单位、已知尺寸、结构来源、是否只是原理示意、相机/帧率/画幅目标。原工程留存，使用唯一新 `.blend`候选。不要在普通系统Python中导入 `bpy`；从doctor返回的Blender可执行文件运行：

```sh
blender --background '/project/work/scene-v01.blend' --python '/project/work/inspect-scene.py'
blender --background '/project/work/scene-v01.blend' --render-output '/project/work/frame-#####' --render-frame 1
```

`inspect-scene.py`的最小独立内容（输出路径先改为本项目新文件）：

```python
import bpy, json
from pathlib import Path
scene = bpy.context.scene
report = {"units": scene.unit_settings.system, "scale_length": scene.unit_settings.scale_length,
          "fps": scene.render.fps / scene.render.fps_base,
          "resolution": [scene.render.resolution_x, scene.render.resolution_y],
          "camera": scene.camera.name if scene.camera else None, "samples": []}
for frame in sorted({scene.frame_start, (scene.frame_start + scene.frame_end) // 2, scene.frame_end}):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    objects = []
    for obj in scene.objects:
        if obj.type not in {"MESH", "CAMERA", "LIGHT"}: continue
        evaluated = obj.evaluated_get(depsgraph)
        objects.append({"name": obj.name, "type": obj.type, "dimensions": list(evaluated.dimensions),
                        "world_matrix": [list(row) for row in evaluated.matrix_world],
                        "hidden_render": obj.hide_render})
    report["samples"].append({"frame": frame, "objects": objects})
with Path('/project/work/geometry-state-v01.json').open('x', encoding='utf-8') as out:
    json.dump(report, out, ensure_ascii=False, indent=2)
```

结构化数据加首/中/末实际渲染一起检查：数量、比例、接触/穿插、相机安全边界、尺度漂移。复杂变形还需采样求值后的顶点，不能用包围盒证明细节正确。动画极端/接触帧需额外采样。PNG首帧不是全片动画验收；保留blend、脚本、贴图依赖和镜头参数。交给AI外观时只允许规定变化，重新核对几何未被改写。

## FreeCAD参数化与导出

本机RPC仅使用已配置的loopback服务，不开放远端连接。先 `list_documents({})`、`get_objects({doc_name})`、`get_object({doc_name,obj_name})`读现有状态。当前FreeCAD MCP的最小例子：

```json
{"name":"FilmGeometryV01"}
```

传给 `create_document`，确认唯一新文档后：

```json
{"doc_name":"FilmGeometryV01","obj_type":"Part::Cylinder","obj_name":"ReferenceCylinder","obj_properties":{"Radius":10,"Height":30}}
```

传给 `create_object`。尺寸按FreeCAD当前单位系统解释，需读回，不猜毫米/米。用 `get_view({view_name:"Isometric",width:960,height:640,focus_object:"ReferenceCylinder"})`查看真实截图。参数/形状检查和截图一致后，保存新原生文件，再导出交换格式。当前typed工具无法表达保存/STEP导出时使用作用域很小的 `execute_code`：

```python
import FreeCAD as App, Part
doc = App.getDocument('FilmGeometryV01')
obj = doc.getObject('ReferenceCylinder')
assert obj is not None
doc.recompute()
assert not obj.Shape.isNull() and obj.Shape.isValid()
# 两个路径必须预先确认不存在；不得复用生产源路径。
doc.saveAs('/project/work/geometry-v01.FCStd')
Part.export([obj], '/project/work/geometry-v01.step')
```

文档改变必须在普通工具路径执行；`execute_code_async`只用于不改文档/GUI的长计算。断连先检查已有FreeCAD和本机RPC监听，不重复修改。导出后重新导入新副本核对尺寸/实体数；制造可用性和FEM精度不在本片几何示意的默认范围。

## PPT、PDF和DOCX资料

先统计文件大小、PDF页数、PPT幻灯片数；只抽本次成果相关页面。PPTX是ZIP格式，可以读取slide XML文本和 `ppt/media/`原始媒体，页码/关系ID与原文件关联；提取图片不能仅靠文件名猜所属页。正文提取可直接使用本包内容工具；输出保留页/段定位和源SHA，`facts_verified`仍为false。图片需依据对应slide的relationships另外提取，不能把正文工具输出当作已提取媒体。大文档先按相关范围拆分候选，避免把完整输出回灌上下文。

```sh
python3 scripts/content_tools.py ingest \
  '/project/sources/deck.pptx' --document-id 'deck-v01' --out '/project/work/deck-content.json'
python3 scripts/content_tools.py manuscript \
  '/project/work/approved-narration.json' --out-dir '/project/outputs/manuscript-v01'
```

第二条输入遵循本包 [旁白稿示例结构](../../assets/manuscript.example.json)，输出可编辑稿与配套文件；不把任意提取正文直接视为审定稿。

PDF的本地只读步骤：

```sh
pdfinfo '/project/sources/report.pdf'
pdftotext -layout -f 3 -l 5 '/project/sources/report.pdf' '/project/work/report-p3-p5.txt'
pdftoppm -png -r 150 -f 3 -l 5 '/project/sources/report.pdf' '/project/work/report'
```

先看提取正文是否非空；文本缺失/乱码才对对应页OCR。Tesseract先 `--list-langs`确认中文包：

```sh
tesseract '/project/work/report-3.png' '/project/work/report-p3-ocr' -l chi_sim+eng --psm 3
```

OCR只产生待核对文字；数字、负号、上下标、单位、希腊字母和图表必须对照原页。未装语言包不宣称中文OCR成功。复杂表格保留裁图与坐标，不把乱码自动修成猜测事实。

若已安装LibreOffice，可把资料PPTX导出PDF用于页面图检查：

```sh
soffice --headless --convert-to pdf --outdir '/project/work/pdf-review' '/project/sources/deck.pptx'
```

输出目录必须新建，避免覆盖同名PDF。转换失败先查字体、文件损坏和现有office进程，不强杀用户会话。LibreOffice的PDF仅是版式候选；正式交付仍需在用户实际使用的WPS打开可编辑DOCX/PPTX，检查中文字体、表格跨页、公式、图题、图片裁切和页码。没有经过WPS真实查看只记“已导出/已渲染”，不记“WPS已验收”。WPS的前台打开和页面操作沿用当前会话有效权限，不自动切换正在编辑的用户文件。
