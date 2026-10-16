"""持久化生成结果与历史目录；读取历史不执行颜色匹配。"""
from __future__ import annotations

import json
import re
from itertools import product
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from .image_io import load_image_rgb
from .formats import VERSIONS, PREVIEW_NAMES, safe_name
from .pixels import material_pixels

RECORD = "作品记录.json"
DATA = "作品数据.npz"


def save_world_import_record(result, out_dir, destination, *, source, version, x, y, coating, overwrite=False):
    """保存本次写入的作品快照及放置参数，不复制世界或重新匹配颜色。"""
    from dataclasses import replace
    from .pipeline import export_preview
    details = dict(path=str(Path(destination).resolve()), source=str(Path(source).resolve()),
                   version=version, x=int(x), y=int(y), scale=result.scale,
                   coating=bool(coating), overwrite=bool(overwrite),
                   saved_at=datetime.now().isoformat(timespec="seconds"))
    snapshot = replace(result, processing=dict(result.processing, world_import=details))
    return export_preview(snapshot, out_dir=out_dir, versions=(version,), make_schematic=False)


def world_import_summary(processing):
    details = processing.get("world_import")
    if not isinstance(details, dict):
        return ""
    names = {"fine": "混合版", "wall": "背景墙版", "map": "地图版"}
    version = names.get(details.get("version"), "材料版")
    return (f'已导入世界：{details.get("path", "")}\n'
            f'{version} · 位置 ({details.get("x", 0)}, {details.get("y", 0)}) · '
            f'夜明漆：{"开启" if details.get("coating") else "关闭"}')


def save_record(result, directory):
    palettes = {v: p for v, p in zip(VERSIONS, (result.palette, result.palette_wall, result.palette_map)) if p is not None}
    grids = dict(zip(VERSIONS, (result.grid, result.grid_wall, result.grid_map)))
    arrays = dict(processed=result.processed_rgb)
    for version, palette in palettes.items():
        arrays[version] = grids[version]
        arrays[version + "_colors"] = palette.candidate_rgb_array()
    if result.source_preview is not None:
        arrays["source_thumbnail"] = result.source_preview
    version = next(v for v in VERSIONS if v in result.versions)
    palette = palettes[version]
    preview = material_pixels(arrays[version], palette)
    thumbnail = Image.fromarray(preview)
    thumbnail.thumbnail((160, 120), Image.Resampling.NEAREST)
    arrays["history_thumbnail"] = np.asarray(thumbnail).copy()
    np.savez_compressed(directory / DATA, **arrays)
    metadata = dict(format=5, created=datetime.now().isoformat(timespec="seconds"),
        source_name=result.source_name, source_path=str(result.source_path or ""),
        name=result.name, original_size=result.original_size, width=result.width, height=result.height,
        scale=result.scale,
        processing=result.processing, versions=result.versions,
        palettes={v: dict(blocks=p.blocks, paints=p.paints) for v, p in palettes.items()})
    (directory / RECORD).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def load_record(directory):
    from .palette import Candidate, Palette
    from .pipeline import Result
    directory = Path(directory).resolve()
    if not (directory / RECORD).is_file():
        return load_legacy(directory)
    from .material_library import normalize_color_metadata
    meta = normalize_color_metadata(json.loads((directory / RECORD).read_text(encoding="utf-8")))
    if meta.get("format") not in (1, 2, 3, 4, 5):
        raise ValueError("这份记录格式暂不支持。")
    palettes, grids = {}, {}
    with np.load(directory / DATA, allow_pickle=False) as data:
        processed = data["processed"].copy()
        source_thumbnail = data["source_thumbnail"].copy() if "source_thumbnail" in data else None
        if processed.shape not in ((meta["height"], meta["width"], 3), (meta["height"], meta["width"], 4)) or processed.dtype != np.uint8:
            raise ValueError("作品预览数据不完整。")
        specs = meta["palettes"]
        if meta["format"] < 3:
            specs = {"fine": specs[0], "wall": specs[2]}
        for version in VERSIONS:
            if version not in specs:
                continue
            spec = specs[version]
            for item in spec["blocks"] + spec["paints"]:
                if "rgb" in item:
                    item["rgb"] = tuple(item["rgb"])
            # 读取已保存的颜色快照，完全不调用当前版本的颜色计算。
            palette = Palette(blocks=[], paints=[])
            palette.blocks, palette.paints = spec['blocks'], spec['paints']
            colors = data[version + "_colors"]
            if colors.shape != (len(palette.blocks) * len(palette.paints), 3) or colors.dtype != np.uint8:
                raise ValueError("作品颜色数据不完整。")
            palette._candidates = [Candidate(block, paint, tuple(map(int, rgb)))
                                   for (block, paint), rgb in zip(product(palette.blocks, palette.paints), colors)]
            grid = data[version].copy()
            if grid.shape != (meta["height"], meta["width"]) or grid.dtype.kind not in "iu" or grid.min() < -1 or grid.max() >= len(colors):
                raise ValueError("作品材料数据不完整。")
            palettes[version] = palette
            grids[version] = grid
    if not grids or any(v not in grids for v in meta['versions'] if v in VERSIONS):
        raise ValueError("作品缺少所选版本的材料数据。")
    res = Result(out_dir=directory, grid=grids.get('fine'), grid_wall=grids.get('wall'), grid_map=grids.get('map'),
        palette=palettes.get('fine'), palette_wall=palettes.get('wall'), palette_map=palettes.get('map'),
        grid_map_wall=grids.get('map_wall'), palette_map_wall=palettes.get('map_wall'),
        processed_rgb=processed, processing=meta["processing"], source_name=meta["source_name"],
        source_path=Path(meta["source_path"]) if meta["source_path"] else None,
        name=safe_name(meta["name"]), original_size=tuple(meta["original_size"]),
        width=meta["width"], height=meta["height"], scale=meta["scale"],
        versions=tuple(v for v in VERSIONS if v in meta["versions"]) or tuple(grids),
        source_preview=source_thumbnail)
    res.processing.pop("simple_k", None)
    _file_paths(res)
    return res


def _file_paths(result):
    directory = result.out_dir
    thumbnail = directory / "原图缩略图.png"
    if thumbnail.is_file():
        result.source_preview = load_image_rgb(thumbnail)


def load_legacy(directory):
    from .pipeline import Result
    images = {}
    aliases = {'wall': ('像素画预览-墙画版.png',), 'map': ('像素画预览-物块地图版.png',)}
    for version, filename in zip(VERSIONS, PREVIEW_NAMES):
        path = next((directory / n for n in (filename, *aliases.get(version, ())) if (directory / n).is_file()), None)
        if path is not None:
            images[version] = load_image_rgb(path)
    if not images:
        raise ValueError("这个文件夹没有可查看的像素画结果。")
    settings = directory / "转换设置.json"
    processing = json.loads(settings.read_text(encoding="utf-8")) if settings.is_file() else {}
    height, width = next(iter(images.values())).shape[:2]
    grid_width = processing.get("width", width)
    res = Result(out_dir=directory, source_name=directory.name, name=directory.name,
        saved_images=images, versions=tuple(images), processing=processing,
        width=grid_width, height=max(1, round(height * grid_width / width)),
        scale=processing.get("scale", 1))
    processed = directory / "像素化原色.png"
    if processed.is_file():
        res.processed_rgb = load_image_rgb(processed)
    res.processing.pop("simple_k", None)
    _file_paths(res)
    return res


class HistoryStore:
    def __init__(self, path, default_root):
        self.path = Path(path)
        self.default_root = Path(default_root)

    def _read(self):
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def entries(self, extra_root=None):
        state = self._read()
        paths = set(state.get("directories", []))
        excluded = {str(Path(p).resolve()) for p in state.get("removed", [])}
        roots = [self.default_root]
        if extra_root:
            roots.append(Path(extra_root))
        for root in roots:
            if not root.is_dir():
                continue
            paths.add(str(root.resolve()))
            try:
                paths.update(str(p.resolve()) for p in root.iterdir() if p.is_dir() and not p.name.startswith(".building-"))
            except OSError:
                continue
        entries = []
        for value in paths:
            directory = Path(value)
            if str(directory.resolve()) in excluded:
                continue
            try:
                marker = directory / RECORD
                if marker.is_file():
                    meta = json.loads(marker.read_text(encoding="utf-8"))
                    title = f'{meta["source_name"]} · {meta["width"]} × {meta["height"]} · {meta["created"].replace("T", " ")}'
                    import_summary = world_import_summary(meta.get("processing", {}))
                    if import_summary:
                        title += f' · 导入世界：{Path(meta["processing"]["world_import"]["path"]).name}'
                    modified = marker.stat().st_mtime
                else:
                    import_summary = ""
                    marker = next((directory / name for name in PREVIEW_NAMES if (directory / name).is_file()), None)
                    if marker is None and self._legacy_report(directory):
                        marker = directory / "材料清单.txt"
                    if marker is None:
                        continue
                    modified = marker.stat().st_mtime
                    title = f'{directory.name} · 旧版结果 · {datetime.fromtimestamp(modified):%Y-%m-%d %H:%M}'
                thumbnail = next((directory / name for name in PREVIEW_NAMES if (directory / name).is_file()), None)
                thumbnail_rgb = None
                if thumbnail is None and (directory / DATA).is_file():
                    try:
                        with np.load(directory / DATA, allow_pickle=False) as data:
                            if "history_thumbnail" in data:
                                thumbnail_rgb = data["history_thumbnail"].copy()
                    except (OSError, ValueError, KeyError):
                        pass
                entries.append(dict(directory=directory, title=title, modified=modified,
                                    thumbnail=thumbnail, thumbnail_rgb=thumbnail_rgb,
                                    world_import_summary=import_summary))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return sorted(entries, key=lambda item: item["modified"], reverse=True)

    def remember(self, directory):
        state = self._read()
        existing = state.get("directories", [])
        directories = list(dict.fromkeys([str(Path(directory).resolve()), *existing]))[:500]
        removed = [p for p in state.get("removed", []) if Path(p).resolve() != Path(directory).resolve()]
        self._write(dict(directories=directories, removed=removed))

    def _write(self, state):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def deletion_plan(self, directory):
        """仅列出已识别作品的生成文件；不递归删除，不跟随目录链接。"""
        directory = Path(directory).absolute()
        # Windows junction/symlink 可能指向作品目录之外，禁止沿链接删除。
        for part in (directory, *directory.parents):
            if part.is_symlink() or (part.exists() and getattr(part.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x400):
                raise ValueError("不能删除链接目录中的作品，请在实际作品目录中操作。")
        directory = directory.resolve()
        if not directory.is_dir():
            raise ValueError("作品文件夹已不存在，请刷新历史记录。")
        marker = directory / RECORD
        source = None
        schematic_names = set()
        if marker.is_file() and not marker.is_symlink():
            meta = json.loads(marker.read_text(encoding="utf-8"))
            if meta.get("format") not in (1, 2, 3, 4, 5):
                raise ValueError("作品记录格式无法识别，未删除任何文件。")
            if meta.get("source_path"):
                source = Path(meta["source_path"]).resolve()
            name = safe_name(meta.get("name", ""))
            schematic_names = {name + suffix + ".TEditSch" for suffix in ("", "-简单版", "-墙画版", "-地图版", "-背景墙版", "-物块地图版", "-背景墙地图版", "-旧版混合地图版")}
        elif not (self._legacy_report(directory) or
                  (any((directory / p).is_file() for p in PREVIEW_NAMES) and
                   (directory / "材料清单.html").is_file())):
            raise ValueError("未确认这是程序生成的作品文件夹，未删除任何文件。")
        else:
            report = directory / "材料清单.txt"
            if report.is_file() and not report.is_symlink():
                text = report.read_text(encoding="utf-8")
                match = re.search(r"图纸名\s*:\s*([^\r\n]+)", text)
                if match:
                    name = safe_name(match.group(1))
                    schematic_names = {name + suffix + ".TEditSch" for suffix in ("", "-简单版", "-墙画版")}
                original = re.search(r"图片\s*:\s*([^\r\n]+)", text)
                if original:
                    source = (directory / Path(original.group(1)).name).resolve()
        names = {*PREVIEW_NAMES, "像素画预览-墙画版.png", "像素画预览-地图版.png", "像素画预览-简单版.png", RECORD, DATA, "像素化原色.png", "原图缩略图.png",
                 "转换设置.json", "材料清单.html", "材料清单.txt"}
        files = []
        for path in directory.iterdir():
            if path.name not in names and path.name not in schematic_names:
                continue
            if path.is_file() and not path.is_symlink() and not (
                getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x400
            ) and path.resolve() not in {source, self.path.resolve()}:
                files.append(path)
        # 识别记录最后删除，某个图纸被占用时仍能从历史里找到作品并重试。
        files.sort(key=lambda path: (path.name in {RECORD, "材料清单.txt"}, path.name))
        return dict(directory=directory, files=tuple(files))

    @staticmethod
    def _legacy_report(directory):
        path = directory / "材料清单.txt"
        if not path.is_file() or path.is_symlink():
            return False
        try:
            with path.open(encoding="utf-8") as report:
                header = report.read(4096)
            return "泰拉瑞拉像素画 · 材料清单" in header and "图纸名" in header
        except (OSError, ValueError):
            return False

    def delete_records(self, directories, confirmed_plans=None):
        """用户确认后删除生成文件，再移除索引。返回成功目录和失败原因。"""
        plans, errors = [], []
        for directory in dict.fromkeys(map(str, directories)):
            try:
                plans.append(self.deletion_plan(directory))
            except (OSError, ValueError, TypeError) as exc:
                errors.append(f"{directory}：{exc}")
        deleted = []
        confirmed = {plan["directory"]: set(plan["files"]) for plan in confirmed_plans} if confirmed_plans is not None else None
        for plan in plans:
            try:
                if confirmed is not None:
                    expected = confirmed.get(plan["directory"], set())
                    if set(plan["files"]) - expected:
                        raise ValueError("确认后作品文件发生变化，请刷新并重新确认删除。")
                for path in plan["files"]:
                    path.unlink(missing_ok=True)
                directory = plan["directory"]
                # 仅尝试删除空作品目录；未知文件及子目录保留。
                if directory not in {self.default_root.resolve(), self.path.parent.resolve(), Path(directory.anchor)}:
                    try:
                        directory.rmdir()
                    except OSError:
                        pass
                deleted.append(directory)
            except (OSError, ValueError) as exc:
                errors.append(f'{plan["directory"]}：部分文件未能删除（{exc}）')
        if deleted:
            state = self._read()
            deleted_set = {str(p) for p in deleted}
            state["directories"] = [p for p in state.get("directories", []) if str(Path(p).resolve()) not in deleted_set]
            state["removed"] = list(dict.fromkeys([*state.get("removed", []), *map(str, deleted)]))
            try:
                self._write(state)
            except OSError as exc:
                errors.append(f"作品文件已删除，但历史索引写入失败：{exc}")
        return deleted, errors
