# 泰拉瑞拉像素工坊 v5.2

图片像素化与编辑工具，支持生成 Terraria 材料画、保存 TEdit 图纸，以及直接导入 `.wld` 世界。Windows 便携版无需安装。

## 使用流程

1. 导入或拖入图片，设置尺寸、采样方式和颜色参数，生成像素画。
2. 预览或编辑像素画；可保存草稿、导出 PNG，也可确认当前画面并生成三个材料版本。
3. 三个材料版本可分别编辑，随后保存 TEdit 文件或导入世界。
4. 已保存的作品、草稿和成功导入世界的作品可从“历史记录 / 草稿”重新打开。

| 版本 | 说明 |
| --- | --- |
| 混合版 | 适合直接观看，使用物块和背景墙，搭配喷漆。 |
| 背景墙版 | 适合直接观看，只使用背景墙，搭配喷漆。 |
| 地图版 | 适合从大小地图观看，使用物块和背景墙，搭配喷漆。 |

完整操作见 [使用说明.txt](使用说明.txt)。该文件以用户确认稿为准，打包脚本会将它同步到发行目录和 ZIP。

“合并近似材料”用于减少成品的材料组合，提供关闭、轻微、适中、较强，桌面默认轻微。三版各自合并，保留真实材料并限制色差和纹理差异，不改像素画。界面显示生成时各版合并前后的组合数；调整后确认并重新生成三版。重新生成会替换三版当前编辑，程序会先询问。

## 从源码运行

需要 Python 3.10+；桌面程序面向 Windows。

```bat
python -m pip install -r requirements.txt
python main.py
```

Windows 也可以双击 `run.bat`。命令行用法：

```bat
python main.py --help
python main.py image.png --width 100 --out 输出 --schematic
```

命令行可加 `--material-merge 1.5` 开启轻微合并，`3` 为适中、`5` 为较强；命令行默认 `0` 关闭，保持原调用结果。

## 目录与开发入口

| 路径 | 用途 |
| --- | --- |
| `main.py` | 桌面与命令行入口 |
| `terraria_pixel/desktop.py` | 主界面、预览与保存 |
| `terraria_pixel/pipeline.py` | 像素画生成、确认后的三版匹配与导出 |
| `terraria_pixel/editor.py`、`editor_window.py` | 编辑数据、画布与编辑窗口 |
| `terraria_pixel/color_model.py` | 逐纹素喷漆公式 |
| `terraria_pixel/material_library.py`、`palette.py` | 贴图色、虚化色与地图色候选 |
| `terraria_pixel/map_colors.py`、`map_storage.py` | 地图匹配与压缩查找表 |
| `terraria_pixel/material_access.py`、`material_rules.py` | 物品放置关系与材料限制 |
| `terraria_pixel/drafts.py`、`history.py` | 草稿、作品快照与历史记录 |
| `terraria_pixel/schematic.py` | TEdit 图纸写入 |
| `terraria_pixel/world.py`、`world_dialog.py` | 世界读写与导入界面 |
| `assets/` | 运行所需色库、背景与中文翻译 |
| `tools/` | 色库重建与发布工具，见 [工具说明](tools/README.md) |

颜色计算、材料限制和文件兼容说明见 [算法说明.md](算法说明.md)。

当前自动化测试保留在 `tests/`，运行 `python -m unittest discover -s tests -p "test_*.py" -q`。

## 打包

Windows 下双击 `打包.bat`，会安装构建依赖、使用 `TerrariaPixelArt.spec` 构建程序，并生成 `dist-v5.2/泰拉瑞拉像素工坊-v5.2.zip`。

发行 ZIP 只包含主 EXE、必要的 `_internal` 运行库和使用说明。源码 ZIP 可用 `python tools/package_source.py` 生成。

仓库不收录发行二进制、构建缓存、个人图片、世界、草稿和历史作品。旧版专用验证脚本、生成报告与历史审查文档已清理，当前测试和旧作品读取所需的兼容逻辑保留。
