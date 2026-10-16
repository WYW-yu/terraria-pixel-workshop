"""图片像素化、物块/墙画颜色匹配及作品保存。"""
from __future__ import annotations

from .calibrated_colors import GAME_VERSION

from dataclasses import dataclass, field, replace
from pathlib import Path
import tempfile
from typing import Callable

import numpy as np
from PIL import Image

from .image_io import image_size, load_image_pixels, pixelate, resolve_sampling
from .pixels import validate_schematic_size
from .palette import Palette, mixed_palette, wall_palette, map_palette
from .material_rules import repair_grid
from .map_colors import match_map
from .material_library import PLACED_MODEL, ACTUATED_MODEL, MAP_MODEL
from .quantize import match_to_palette
from .formats import ConversionCancelled, safe_name, VERSIONS, PREVIEW_NAMES


def make_run_dir(out_dir: Path, image_path: Path) -> Path:
    """为本次生成创建独立子文件夹：以"原始图片尺寸"命名（如 2985x5334）。

    重名时自动加序号：(2)、(3)… 保证每次的结果互不覆盖。
    """
    try:
        w, h = image_size(image_path)
        base = f"{w}x{h}"
    except Exception:
        base = image_path.stem
    run_dir = out_dir / base
    n = 2
    while run_dir.exists():
        run_dir = out_dir / f"{base}({n})"
        n += 1
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def match_materials(rgb, palette, **options):
    labs, costs, allowed = palette.matching_data()
    indices = np.flatnonzero(allowed)
    matched = match_to_palette(rgb, palette.candidate_rgb_array()[indices],
                               candidate_lab=labs[indices], candidate_penalty=costs[indices], **options)
    return indices[matched].astype(np.int32)


@dataclass
class Result:
    out_dir: Path | None = None
    schematic: Path | None = None
    schematic_wall: Path | None = None
    schematic_map: Path | None = None
    schematic_map_wall: Path | None = None
    grid: object = field(default=None, repr=False)
    grid_wall: object = field(default=None, repr=False)
    grid_map: object = field(default=None, repr=False)
    grid_map_wall: object = field(default=None, repr=False)
    palette: Palette | None = None
    palette_wall: Palette | None = None
    palette_map: Palette | None = None
    palette_map_wall: Palette | None = None
    width: int = 0
    height: int = 0
    scale: int = 1
    processed_rgb: object = field(default=None, repr=False)
    processing: dict = field(default_factory=dict)
    source_path: Path | None = None
    source_name: str = ""
    name: str = ""
    original_size: tuple = (0, 0)
    versions: tuple = VERSIONS
    saved_images: dict = field(default_factory=dict, repr=False)
    source_preview: object = field(default=None, repr=False)


def prepare_pixel_preview(
    image_path: str | Path,
    *,
    width: int = 100,
    scale: int = 1,
    out_dir: str | Path = "输出",
    name: str | None = None,
    make_schematic: bool = False,
    palette: Palette | None = None,
    coating: bool = True,
    sampling: str = "auto",
    detail: float = 0.4,
    contrast: float = 1.0,
    saturation: float = 1.0,
    gamma: float = 1.0,
    color_limit: int = 0,
    dither: str = "none",
    dither_strength: float = 0.75,
    progress: Callable[[int, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Result:
    """只缩小和调色，不进行材料匹配，也不写文件。"""
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"图片不存在: {image_path}")
    if width < 1:
        raise ValueError("width 必须 >= 1")
    if scale < 1:
        raise ValueError("scale 必须 >= 1")
    if dither not in {"none", "bayer", "floyd"} or not 0 <= dither_strength <= 1:
        raise ValueError("抖动模式需为 none / bayer / floyd，强度需为 0–1")

    def check_cancel():
        if cancelled and cancelled():
            raise ConversionCancelled()

    last_progress = None

    def notify(value, text):
        nonlocal last_progress
        check_cancel()
        current = (int(value), text)
        if progress and current != last_progress:
            progress(*current)
        last_progress = current

    notify(0, "读取图片")
    rgb = load_image_pixels(image_path)
    notify(2, "降采样与颜色整理")
    sampling_used = resolve_sampling(rgb, width, max(1, round(rgb.shape[0] * width / rgb.shape[1])), sampling)
    grid_rgb = pixelate(rgb, width, sampling=sampling_used, detail=detail, contrast=contrast,
                        saturation=saturation, gamma=gamma, color_limit=color_limit)
    processing = dict(sampling=sampling, sampling_used=sampling_used, detail=detail,
                      contrast=contrast, saturation=saturation, gamma=gamma,
                      color_limit=color_limit, dither=dither, dither_strength=dither_strength,
                      width=width, scale=scale, coating=coating,
                      color_model=ACTUATED_MODEL if palette is None else "custom-rgb",
                      map_color_model=MAP_MODEL, map_matching="rgb-squared-last-tie",
                      map_dither="none", material_library="Terraria-1.4.5.8-337-tiles-366-walls",
                      placed_matching='expected-texel-lab-v2',
                      game_version=GAME_VERSION, color_reference="原版贴图；物块虚化、墙满亮度；逐纹素色差；稳定不透明素材")
    thumbnail = Image.fromarray(rgb)
    thumbnail.thumbnail((1600, 1600))
    notify(100, "像素画已生成，请确认后生成三版本")
    return Result(width=grid_rgb.shape[1], height=grid_rgb.shape[0],
        scale=scale, processed_rgb=grid_rgb, processing=processing, versions=(),
        source_path=image_path.resolve(), source_name=image_path.name,
        name=safe_name(name or image_path.stem), original_size=(rgb.shape[1], rgb.shape[0]),
        source_preview=np.asarray(thumbnail).copy())


def generate_material_versions(result: Result, *, palette=None, scale=None, coating=None,
                               dither=None, dither_strength=None, progress=None, cancelled=None) -> Result:
    """只匹配已确认的像素，不重新采样、调色或读取原图；成功后返回新结果。"""
    grid_rgb = np.array(result.processed_rgb, dtype=np.uint8, copy=True)
    if grid_rgb.ndim != 3 or grid_rgb.shape[2] not in (3, 4) or not all(grid_rgb.shape[:2]):
        raise ValueError('请先生成或打开一张像素画。')
    processing = dict(result.processing)
    scale = result.scale if scale is None else scale
    coating = processing.get('coating', True) if coating is None else coating
    dither = processing.get('dither', 'none') if dither is None else dither
    dither_strength = processing.get('dither_strength', .75) if dither_strength is None else dither_strength
    if scale < 1:
        raise ValueError('每格大小至少为1。')
    if dither not in {'none', 'bayer', 'floyd'} or not 0 <= dither_strength <= 1:
        raise ValueError('交错混色设置不正确。')

    def check_cancel():
        if cancelled and cancelled():
            raise ConversionCancelled()

    last_progress = None

    def notify(value, text):
        nonlocal last_progress
        check_cancel()
        current = (int(value), text)
        if progress and current != last_progress:
            progress(*current)
        last_progress = current

    notify(0, '准备材料颜色库')
    pal = palette or mixed_palette()
    notify(5, "匹配混合版颜色")
    match_rgb = grid_rgb[..., :3]
    if grid_rgb.shape[2] == 4:
        alpha = grid_rgb[..., 3:4].astype(np.float32) / 255
        match_rgb = np.rint(match_rgb * alpha + 255 * (1-alpha)).astype(np.uint8)

    # 混合版：每格匹配允许的物块或背景墙（各自贴图色 + 喷漆）。
    grid = match_materials(match_rgb, pal, cancel=check_cancel,
                            dither=dither, strength=dither_strength,
                            progress=lambda p: notify(5 + p * 40, "匹配混合版颜色"))

    # 背景墙版只使用墙的贴图色，与地图代表色分离。
    pal_wall = wall_palette()
    grid_wall = match_materials(match_rgb, pal_wall, cancel=check_cancel,
                                 dither=dither, strength=dither_strength,
                                 progress=lambda p: notify(45 + p * 40, "匹配背景墙版颜色"))
    pal_map = map_palette()
    # 地图版用 RGB 查表、无抖动；alpha>0 直接按 RGB 匹配。
    grid_map = match_map(grid_rgb[..., :3], cancel=check_cancel,
                         progress=lambda p: notify(85 + p * 5, "匹配地图版颜色"))
    processing['map_material_scope'] = 'mixed-tile-wall'
    if grid_rgb.shape[2] == 4:
        grid[grid_rgb[..., 3] == 0] = -1
        grid_wall[grid_rgb[..., 3] == 0] = -1
        grid_map[grid_rgb[..., 3] == 0] = -1

    grid = repair_grid(grid, pal, match_rgb, cancel=check_cancel)
    grid_map = repair_grid(grid_map, pal_map, grid_rgb, map_colors=True, cancel=check_cancel)
    processing['material_safety'] = 'buildable-items-no-specials-v3'
    processing['material_access'] = 'item-placement-1.4.5.8-v1'
    processing['actuated_tiles'] = True
    processing['placed_material_scope'] = 'mixed-tile-wall' if palette is None else 'custom'
    processing.update(scale=scale, coating=coating, dither=dither, dither_strength=dither_strength,
                      materials_stale=False, pixels_confirmed=True,
                      color_model=ACTUATED_MODEL if palette is None else 'custom-rgb',
                      map_color_model=MAP_MODEL, map_matching='rgb-squared-last-tie', map_dither='none',
                      material_library='Terraria-1.4.5.8-337-tiles-366-walls',
                      placed_matching='expected-texel-lab-v2', game_version=GAME_VERSION,
                      color_reference='原版贴图；物块虚化、墙满亮度；逐纹素色差；稳定不透明素材')
    notify(100, "三版本已生成，可以分别编辑或保存")
    return replace(result, grid=grid, grid_wall=grid_wall, grid_map=grid_map,
        palette=pal, palette_wall=pal_wall, palette_map=pal_map,
        width=grid.shape[1], height=grid.shape[0],
        scale=scale, processed_rgb=grid_rgb, processing=processing,
        versions=VERSIONS, out_dir=None, saved_images={}, grid_map_wall=None, palette_map_wall=None,
        schematic=None, schematic_wall=None, schematic_map=None, schematic_map_wall=None)


def prepare_preview(image_path, *, palette=None, progress=None, cancelled=None, **options) -> Result:
    """兼容命令行与旧调用：依次完成像素画与材料生成。桌面分别调用两步。"""
    pixel_progress = (lambda value, text: progress(int(value * .05), text)) if progress else None
    result = prepare_pixel_preview(image_path, palette=palette, progress=pixel_progress,
                                   cancelled=cancelled, **options)
    material_progress = (lambda value, text: progress(5 + int(value * .95), text)) if progress else None
    return generate_material_versions(result, palette=palette, progress=material_progress, cancelled=cancelled)




def export_preview(result: Result, *, out_dir, versions=VERSIONS, make_schematic=False,
                   progress=None, cancelled=None) -> Result:
    """直接保存已计算的预览；不重新读取原图或匹配颜色。"""
    versions = tuple(v for v in VERSIONS if v in versions)
    if not versions:
        raise ValueError("请至少选择一个要保存的版本。")
    if result.processing.get('materials_stale'):
        raise ValueError('像素画或材料设置已修改，请确认当前像素画并重新生成三版本。')
    if result.grid is None:
        raise ValueError("旧版记录只能查看；没有可再次导出的材料数据。")
    for version in versions:
        suffix = {"fine": "", "wall": "_wall", "map": "_map"}[version]
        if getattr(result, "grid" + suffix) is None or getattr(result, "palette" + suffix) is None:
            raise ValueError("这份旧作品没有所选版本的数据，请取消勾选该版本或重新预览原图。")
    if make_schematic:
        validate_schematic_size(result.width, result.height, result.scale)

    def check_cancel():
        if cancelled and cancelled():
            raise ConversionCancelled()

    def notify(value, text):
        check_cancel()
        if progress:
            progress(int(value), text)

    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    res = replace(result, versions=versions, schematic=None,
                  schematic_wall=None, schematic_map=None, schematic_map_wall=None)
    grids = (res.grid, res.grid_wall, res.grid_map)
    palettes = (res.palette, res.palette_wall, res.palette_map)
    notify(0, "准备保存作品")
    with tempfile.TemporaryDirectory(prefix=".building-", dir=out_dir) as temporary:
        stage = Path(temporary)
        res.out_dir = stage
        if make_schematic:
            from .schematic import write_tedsch
            for i, version in enumerate(VERSIONS):
                if version not in versions:
                    continue
                suffix = ("", "-背景墙版", "-地图版")[i]
                path = stage / f"{res.name}{suffix}.TEditSch"
                write_tedsch(grids[i], palettes[i], path, name=res.name + suffix,
                    scale=res.scale, walls_only=version == "wall",
                    coating=False if version == "map" else res.processing.get("coating", True),
                    cancel=check_cancel, progress=lambda p, i=i: notify(10 + i * 18 + p * 17, "保存游戏建筑图纸"))
                setattr(res, ("schematic", "schematic_wall", "schematic_map")[i], path)
        notify(86, "保存历史记录数据")
        from .history import save_record
        save_record(res, stage)
        check_cancel()
        iw, ih = res.original_size
        base = f"{iw}x{ih}"
        n = 1
        while True:
            final = out_dir / (base if n == 1 else f"{base}({n})")
            if final.exists():
                n += 1
                continue
            try:
                stage.rename(final)
                break
            except FileExistsError:
                n += 1
        res.out_dir = final
        for attr in ("schematic", "schematic_wall", "schematic_map", "schematic_map_wall"):
            path = getattr(res, attr)
            if path is not None:
                setattr(res, attr, final / path.name)
    if progress:
        progress(100, "保存完成")
    return res


def run_conversion(image_path, *, out_dir="输出", make_schematic=False, progress=None, cancelled=None, **options):
    """兼容命令行：计算并导出三版。桌面流程分别调用两步预览与保存。"""
    notify = (lambda value, text: progress(int(value * .68), text)) if progress else None
    result = prepare_preview(image_path, progress=notify, cancelled=cancelled, **options)
    notify_export = (lambda value, text: progress(68 + int(value * .32), text)) if progress else None
    return export_preview(result, out_dir=out_dir, make_schematic=make_schematic,
                          progress=notify_export, cancelled=cancelled)
