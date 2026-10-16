"""独立像素草稿：保存原尺寸像素、材料和当前画具状态，不重新匹配颜色。"""
from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile

import numpy as np
from PIL import Image, UnidentifiedImageError

from .editor import EditCanvas, TARGET_PIXEL, TARGETS
from .palette import Palette, Candidate

EXTENSION = '.tpdraft'
TOOLS = ('brush', 'fill', 'picker', 'select')


@dataclass
class Draft:
    canvas: EditCanvas
    color: tuple = (255, 255, 255)
    tool: str = 'brush'
    history: tuple = ()
    selection: tuple | None = None


def fingerprint(canvas):
    """保存检查点独立于“应用”，存草稿不会吞掉待应用的修改。"""
    digest = hashlib.sha256(canvas.rgb.tobytes())
    if canvas.indices is not None:
        digest.update(canvas.indices.tobytes())
    return digest.digest()


def _rgb(value):
    if not isinstance(value, (list, tuple)) or len(value) not in (3, 4) or any(type(v) is not int or not 0 <= v <= 255 for v in value):
        raise ValueError('草稿颜色数据不完整。')
    return tuple(value)


def _candidate(spec):
    block, paint = spec['block'], spec['paint']
    if not isinstance(block, dict) or not isinstance(paint, dict):
        raise ValueError('草稿材料信息不正确。')
    if any(not isinstance(block.get(key), str) for key in ('name', 'name_zh')) or not isinstance(paint.get('name_zh'), str):
        raise ValueError('草稿材料名称不完整。')
    ident = block.get('wall_id', block.get('tile_id'))
    if type(ident) is not int or not 0 <= ident <= 65535 or type(paint.get('id')) is not int or not 0 <= paint['id'] <= 31:
        raise ValueError('草稿材料编号不正确。')
    color = _rgb(spec['rgb'])
    if len(color) != 3:
        raise ValueError('材料候选颜色必须是RGB。')
    return Candidate(block, paint, color)


def _image(raw, expected_mode=None):
    with Image.open(io.BytesIO(raw)) as image:
        w, h = image.size
        if expected_mode == 'RGB' and image.mode not in ('RGB', 'RGBA'):
            raise ValueError('草稿像素格式不正确。')
        return np.asarray(image.convert('RGBA') if expected_mode is None else image).copy()


def save_draft(path, draft):
    """同目录临时文件写完后替换，保存失败不会破坏之前的草稿。"""
    path = Path(path)
    canvas = draft.canvas
    metadata = dict(format='terraria-pixel-draft', version=2, target=canvas.target,
                    color=list(_rgb(draft.color)), tool=draft.tool,
                    history=[list(_rgb(c)) for c in draft.history[:18]], selection=draft.selection)
    if canvas.is_material:
        metadata['candidates'] = [dict(block=c.block, paint=c.paint, rgb=c.rgb) for c in canvas.palette.candidates]
        metadata['blocks'] = canvas.palette.blocks
        metadata['paints'] = canvas.palette.paints
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.draft-', suffix='.tmp', delete=False) as f:
            temporary = Path(f.name)
        with ZipFile(temporary, 'w', ZIP_DEFLATED) as archive:
            archive.writestr('settings.json', json.dumps(metadata, ensure_ascii=False))
            pixels = io.BytesIO()
            Image.fromarray(canvas.rgb).save(pixels, format='PNG')
            archive.writestr('pixels.png', pixels.getvalue())
            if canvas.is_material:
                indices = io.BytesIO()
                np.save(indices, canvas.indices, allow_pickle=False)
                archive.writestr('indices.npy', indices.getvalue())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_draft(path):
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) not in (2, 3) or len({e.filename for e in entries}) != len(entries):
                raise ValueError('草稿文件结构不正确。')
            if any(e.filename not in {'settings.json', 'pixels.png', 'indices.npy'} for e in entries):
                raise ValueError('草稿文件过大或格式不正确。')
            from .material_library import normalize_color_metadata
            meta = normalize_color_metadata(json.loads(archive.read('settings.json')))
            if meta.get('format') != 'terraria-pixel-draft' or meta.get('version') not in (1, 2) or meta.get('target') not in (*TARGETS, 'simple', 'map_wall'):
                raise ValueError('不支持的草稿版本。')
            pixels = _image(archive.read('pixels.png'), 'RGB')
            target = 'fine' if meta['target'] == 'simple' else meta['target']
            # Removed wall-map drafts remain viewable/editable as their saved pixels.
            if target == 'map_wall':
                target = TARGET_PIXEL
            palette = indices = None
            if target != TARGET_PIXEL:
                specs = meta['candidates']
                if not isinstance(specs, list) or not 1 <= len(specs) <= 20_000:
                    raise ValueError('草稿材料表不正确。')
                palette = Palette(blocks=[], paints=[])
                palette.blocks, palette.paints = meta['blocks'], meta['paints']
                if not isinstance(palette.blocks, list) or not isinstance(palette.paints, list):
                    raise ValueError('草稿材料表不正确。')
                palette._candidates = [_candidate(s) for s in specs]
                raw = io.BytesIO(archive.read('indices.npy'))
                version = np.lib.format.read_magic(raw)
                if version == (1, 0):
                    shape, fortran, dtype = np.lib.format.read_array_header_1_0(raw)
                elif version == (2, 0):
                    shape, fortran, dtype = np.lib.format.read_array_header_2_0(raw)
                else:
                    raise ValueError('草稿材料网格格式不正确。')
                if shape != pixels.shape[:2] or dtype != np.dtype('int32') or fortran:
                    raise ValueError('草稿材料网格不完整。')
                raw.seek(0)
                indices = np.load(raw, allow_pickle=False)
            canvas = EditCanvas(rgb=pixels, target=target, indices=indices, palette=palette)
            from .pixels import material_pixels
            if canvas.is_material:
                expected = material_pixels(indices, palette)
                if pixels.shape[2] == 4 and expected.shape[2] == 3:
                    expected = np.dstack((expected, np.full(pixels.shape[:2], 255, np.uint8)))
                if not np.array_equal(expected, pixels):
                    raise ValueError('草稿颜色与材料网格不一致。')
            color = _rgb(meta['color'])
            tool = meta['tool']
            if tool not in TOOLS:
                raise ValueError('草稿工具不正确。')
            history = tuple(_rgb(c) for c in meta.get('history', [])[:18])
            selection = meta.get('selection')
            if selection is not None:
                if not isinstance(selection, list) or len(selection) != 4 or any(type(v) is not int for v in selection):
                    raise ValueError('草稿选区不正确。')
                x0, y0, x1, y1 = selection
                if not (0 <= x0 <= x1 < canvas.width and 0 <= y0 <= y1 < canvas.height):
                    raise ValueError('草稿选区超出画布。')
                selection = tuple(selection)
            return Draft(canvas, color, tool, history, selection)
    except (BadZipFile, KeyError, TypeError, AttributeError, EOFError, OverflowError, UnidentifiedImageError) as exc:
        raise ValueError('草稿文件损坏或格式不正确。') from exc


def import_image(path):
    """导入已有像素图片，不缩放、不调色；每个图片像素成为一个画布格。"""
    from .image_io import load_image_pixels
    return Draft(EditCanvas(load_image_pixels(path)))
