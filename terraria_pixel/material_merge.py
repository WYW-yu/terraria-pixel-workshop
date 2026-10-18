"""在单幅材料画中合并近色组合，保留真实候选及其原始索引。"""
import math

import numpy as np

from .material_library import ACTUATED_MODEL, PLACED_MODEL
from .material_rules import candidate_flags
from .quantize import CHROMA_WEIGHT, rgb_to_lab


def validate_merge_tolerance(value):
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 5:
        raise ValueError('近似材料合并程度必须为 0–5；0 表示关闭。')
    return value


def merge_similar_materials(grid, palette, tolerance=0, *, map_colors=False,
                            cancel=None, progress=None):
    """按原用量选固定代表；每次替换同时限制预览色、纹素均值及纹理差异。

    距离采用本项目加权 Lab 欧氏距离，不是 CIEDE2000。
    地图版只比较地图色。贴图版还要求目标纹理方差不增加，且各通道
    标准差的加权距离不超过阈值；缺少统计的自定义纯色候选视为零方差。
    禁用或不稳定候选不参与替换，透明格保持 -1；不修改输入数组/色库。
    """
    tolerance = validate_merge_tolerance(tolerance)
    source = np.asarray(grid)
    if source.ndim != 2 or not np.issubdtype(source.dtype, np.integer):
        raise ValueError('材料画必须为二维整数网格。')
    if source.size and (source.min() < -1 or source.max() >= len(palette.candidates)):
        raise ValueError('材料画含有无效材料编号。')
    used, counts = np.unique(source[source >= 0], return_counts=True)
    report = dict(before=len(used), after=len(used), changed_cells=0, max_distance=0.0)
    if cancel:
        cancel()
    if not tolerance or len(used) < 2:
        if progress:
            progress(1.0)
        return source.astype(np.int32, copy=True), report

    weights = np.array((1.0, CHROMA_WEIGHT, CHROMA_WEIGHT))
    preview = rgb_to_lab(palette.candidate_rgb_array()[used]) * np.sqrt(weights)
    means = preview.copy()
    deviations = np.zeros_like(means)
    costs = np.zeros(len(used))
    eligible = candidate_flags(palette)[0][used].copy()
    if not map_colors:
        for pos, index in enumerate(used):
            candidate = palette.candidates[index]
            block, paint = candidate.block, candidate.paint['id']
            if block.get('color_model') in (PLACED_MODEL, ACTUATED_MODEL):
                if not block.get('auto_eligible', False) or not all(
                        key in block for key in ('placed_lab', 'placed_variance')):
                    eligible[pos] = False
                    continue
                means[pos] = np.asarray(block['placed_lab'][paint]) * np.sqrt(weights)
                variance = np.maximum(block['placed_variance'][paint], 0)
                deviations[pos] = np.sqrt(variance * weights)
                costs[pos] = np.dot(variance, weights)

    # 用量优先，同用量优先平整材料，再以原索引保证确定性。
    order = np.lexsort((used, costs, -counts))
    representatives = []
    remap = np.arange(len(palette.candidates), dtype=np.int32)
    limit = tolerance * tolerance
    for step, pos in enumerate(order):
        if cancel:
            cancel()
        if eligible[pos]:
            prior = np.asarray(representatives, dtype=np.intp)
            color_distance = np.sum((preview[prior] - preview[pos]) ** 2, axis=1)
            mean_distance = np.sum((means[prior] - means[pos]) ** 2, axis=1)
            texture_distance = np.sum((deviations[prior] - deviations[pos]) ** 2, axis=1)
            close = (color_distance <= limit) & (mean_distance <= limit)
            if not map_colors:
                close &= (texture_distance <= limit) & (costs[prior] <= costs[pos] + 1e-9)
            matches = np.flatnonzero(close)
            if len(matches):
                choice = matches[0]
                target = prior[choice]
                remap[used[pos]] = used[target]
                report['changed_cells'] += int(counts[pos])
                report['max_distance'] = max(report['max_distance'],
                    float(np.sqrt(max(color_distance[choice], mean_distance[choice]))))
            else:
                representatives.append(pos)
        if progress:
            progress((step + 1) / len(order))
    if cancel:
        cancel()
    result = source.astype(np.int32, copy=True)
    present = result >= 0
    result[present] = remap[result[present]]
    report['after'] = len(np.unique(result[present]))
    return result, report
