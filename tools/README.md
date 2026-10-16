# 开发工具

日常运行只需项目根目录的依赖和 `assets`，无需执行色库工具。颜色数据已随源码提供，原始游戏纹理不分发。

## 打包

- `package_portable.py`：将 `dist-v5.2/TerrariaPixelArt` 中的主 EXE、运行库与使用说明打成 ZIP；使用说明从源码根目录同步。
- `package_source.py`：打包当前源码、资源和开发说明，排除发行文件、用户数据、缓存和生成报告。
- `pyinstaller_hooks/hook-PIL.Image.py`：配合根目录 spec 精简 Pillow 打包内容。

## 色库维护

这些工具会修改色库，只在需要重建对应数据时执行。必须自行提供相应输入文件。

| 工具 | 输入与作用 |
| --- | --- |
| `extract_game_textures.js` | 游戏目录、纹理清单 JSON、输出目录、提供 `__BufferReader` / `__Presser` 的 xnb.js LZX 适配模块；输出 RGBA `.raw` 与尺寸/哈希 JSON，另需 Node.js |
| `calibrate_colors.py` | 解码纹理目录；生成兼容色表 `calibrated_colors.py`，并提供其他工具共用的密铺帧采样函数 |
| `import_material_library.py` | 原始色库目录（含 `files/all.tr`、`tile.tr`、`wall.tr` 与 `ItemID.json`）和解码纹理目录；重建基础材料、贴图色和地图表 |
| `build_actuated_colors.py` | 解码纹理目录；为已有物块补充虚化后的 RGB、Lab 与方差 |
| `extend_materials.py` | 解码纹理目录；按 `material_additions_1458.json` 添加或更新 64 种材料的贴图色、虚化色和地图基础色 |
| `update_material_access.py` | 游戏物品放置关系静态导出 JSON、中文物品名 JSON；更新物品 ID 与世界材料 ID 的关系 |
| `compress_map_tables.py` | 对 `assets` 的地图表进行无损压缩，支持已有的分文件格式 |

基础导入会重建材料库。需要完整重建时，先导入基础库，再补充虚化色、扩展材料，最后更新物品放置关系；不能只运行基础导入后直接发布。原候选顺序必须保持，否则地图查找表索引会错位。

`*_calibration.json` 和 `map_compression.json` 是工具运行时生成的报告，已由 `.gitignore` 排除，不随源码保存。
