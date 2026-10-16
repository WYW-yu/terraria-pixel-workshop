# 泰拉瑞拉像素工坊 v5.2

图片转像素画、编辑草稿、生成 TEdit 图纸或直接写入 Terraria 世界。Windows 便携版，无需安装。


## 使用

参见 [使用说明.txt](使用说明.txt)。发行目录 `dist-v5.2/TerrariaPixelArt` 中双击 `TerrariaPixelArt.exe`。

使用说明以用户重写的确认稿为准。源码根目录、EXE旁和发行压缩包内使用同一份原文；便携打包会自动同步源码根目录的说明。源码打包也直接收录该文件，后续维护请勿恢复此前的长版说明。

## 颜色与安全规则

| 版本 | 材料 | 参考色 |
| --- | --- | --- |
| 混合版 | 允许的物块和墙 | 物块虚化贴图色 + 墙贴图色 |
| 背景墙版 | 墙 | 喷漆贴图色 |
| 地图版 | 允许的物块和背景墙 | 地图代表色 + 地图喷漆规则 |

喷漆先在每个纹素上计算，再求平均，不与“先平均再喷漆”混用。主画面色与地图色独立。色库提供无漆及13–30号漆；校准数据包含0–30号漆。
透明材质按白底合成；动画使用首组密铺帧。存在动画、透明或特殊效果的新增材质不进入贴图色自动匹配，允许的素材仍可手动选择。真实背景、光照和帧变化会影响游戏观感，尚未做逐项游戏截图测量。
传播源、重力、易损/临时和下落特效物块在自动匹配、绘制、导出及世界写入中继续禁用。

## 源码入口

- `terraria_pixel/pipeline.py`：像素画预览、确认后的三版匹配、导出；命令行保持一次完成转换。
- `terraria_pixel/color_model.py`：逐纹素喷漆公式。
- `terraria_pixel/material_library.py`、`palette.py`：贴图/虚化/地图色库。
- `terraria_pixel/map_colors.py`：地图查表与新增候选比较。
- `terraria_pixel/map_storage.py`：候选记录与无损压缩查找表的读取、损坏检查及旧格式兼容。
- `terraria_pixel/world.py`、`world_dialog.py`：世界读写、定位界面。
- `terraria_pixel/editor.py`、`editor_window.py`：像素编辑。
- `tools/material_additions_1458.json`：新增64种材料的ID和游戏地图基础色。
- `tools/additions_calibration.json`：纹理哈希与静态参考限制。

既有色库候选保留前缀顺序，新候选追加，防止原查询表索引错位。已保存作品使用其颜色快照。

## 开发与验证

Python 3.10+，安装 `requirements.txt`。运行 `python main.py`；测试 `python -m unittest discover -s tests -p "test_*.py" -q`。
界面验证：`python tests/world_ui.py`、`python tests/release_413_ui.py`；发行验证：`python tests/verify_packaged.py <exe>`。
双击 `打包.bat`，或用 PyInstaller 的 `TerrariaPixelArt.spec` 构建目录式程序，再运行 `tools/package_portable.py`。
压缩包仅包含主EXE、`_internal` 和使用说明，用户草稿不打入发行包。

地图资产由 `library_*.tr`（候选记录）和 `library_*.lut.z`（zlib压缩查询表）配对组成，不可只复制其中一项。原始色库数据导入脚本会自动拆分压缩；`tools/compress_map_tables.py` 可重复执行并写出原始数据SHA256审计。`TerrariaPixelArt.spec` 和 `tools/pyinstaller_hooks` 包含精简打包规则，`打包.bat` 使用同一份spec，避免重新收进未使用组件。

重建新增颜色：先用 `tools/extract_game_textures.js` 解码相应游戏纹理，再运行 `python tools/extend_materials.py <raw目录>`。原始游戏贴图不随程序分发。
详细结果见 `v4.13验证记录.md`。
