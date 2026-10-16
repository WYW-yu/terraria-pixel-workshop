#!/usr/bin/env python3
"""小白引导模式：双击 exe / 运行 run.bat 后按提示操作即可。

流程：输入图片路径(可拖拽) → 输入目标宽度 → 保存作品数据和可选图纸。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


BANNER = r"""
  =============================================
     泰拉瑞拉像素画生成器  v4.7.2
     图片 -> 像素画 -> 作品数据 / 可选图纸
  =============================================
"""


def ask(question: str, default: str = "") -> str:
    if default:
        print(f"{question}（直接回车用默认值 {default}）", end="")
    else:
        print(question, end="")
    try:
        val = input(" > ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(0)
    return val or default


def _pause():
    try:
        input("\n按回车键退出窗口…")
    except (EOFError, KeyboardInterrupt):
        pass


def output_dir() -> Path:
    """输出目录：打包成 exe 时固定在 exe 旁边，源码运行则在当前目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "输出"
    return Path("输出")


def parse_width(text: str, src_w: int) -> int | None:
    """解析目标宽度输入。

    支持：
      - 纯数字：如 300
      - /N 或 ÷N：按原图宽度等分，如 /2 = 原图宽的一半
    无法识别返回 None。
    """
    t = text.strip()
    m = re.fullmatch(r"[/÷]\s*(\d+(?:\.\d+)?)", t)
    if m and src_w:
        d = float(m.group(1))
        if d > 0:
            return max(1, round(src_w / d))
    try:
        v = int(t)
    except ValueError:
        return None
    return v if v >= 1 else None


def run_interactive() -> int:
    from .pipeline import run_conversion
    # 控制台编码兜底：遇到无法显示的字符用 ? 代替，避免 GBK 控制台崩溃
    try:
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except Exception:
        pass
    print(BANNER)
    print("第一步：把图片文件拖进这个窗口，或者直接输入图片路径。")

    while True:
        img = ask("图片路径")
        p = Path(img.strip('"').strip("'"))
        if p.exists() and p.is_file():
            break
        print(f"  找不到这个文件: {p}，请重新输入。\n")

    # 读取原图尺寸，据此建议目标宽度（像素画分辨率 = 宽度 x 高度）
    try:
        from .image_io import detect_grid, image_size, load_image_rgb
        iw, ih = image_size(p)
        grid_cols = detect_grid(load_image_rgb(p)) if iw else None
    except Exception:
        iw = ih = 0
        grid_cols = None
    if iw:
        print(f"  图片原始分辨率: {iw} x {ih} 像素（输出的清晰度由“目标宽度”决定）")
        if grid_cols:
            suggest = grid_cols
            print(f"  [检测] 这张图像是由 {grid_cols} 列规则方格组成的像素画，建议宽度直接用 {grid_cols}（一格=一方块）")
            hint = f"建议 {suggest}（=你的格子列数）；输入 /2、/4 等可按原图宽度等分"
        else:
            suggest = max(50, min(iw, 300))
            hint = f"建议 {suggest}；输入 /2、/4 等可按原图宽度等分"
        default_w = str(suggest)
    else:
        hint = "数字越大越清晰"
        default_w = "100"

    width_str = ask(f"目标宽度（输出分辨率=宽度×高度，{hint}）", default_w)
    width = parse_width(width_str, iw)
    if width is None:
        print(f"  无法识别“{width_str}”，使用建议值 {default_w}。")
        width = int(default_w)
    m_div = re.fullmatch(r"[/÷]\s*(\d+(?:\.\d+)?)", width_str.strip())
    if m_div and iw:
        print(f"  目标宽度 = 原图宽 {iw} ÷ {m_div.group(1)} = {width}")
    if width > 800 and iw:
        est = width * max(1, round(width * ih / iw))
        print(f"  [提示] 宽度 {width} 会生成约 {est:,} 个方块，游戏内工程量非常大，请注意尺寸是否合适。")

    print("每个像素用几乘几的方块？（决定成品在游戏里的大小）")
    print("    1 = 1 格像素 → 1 个方块（最精细、材料最少，推荐）")
    print("    2 = 1 格像素 → 2×2 个方块（图案一模一样，但成品大 2 倍、材料 ×4、图纸也大 4 倍）")
    print("    3 = 1 格像素 → 3×3 个方块（成品大 3 倍、材料 ×9）")
    scale_str = ask("输入 1 / 2 / 3", "1")
    try:
        scale = int(scale_str)
    except ValueError:
        print("  不是数字，用默认值 1。")
        scale = 1
    if scale < 1:
        scale = 1

    make_sch = ask("是否同时生成 TEdit 图纸文件？（y=是 / n=否）", "n").lower()
    make_schematic = make_sch.startswith("y")

    print("\n正在生成，请稍候…")
    rc = 0
    try:
        res = run_conversion(
            p, width=width, scale=scale,
            out_dir=output_dir(), make_schematic=make_schematic,
        )
    except Exception as exc:
        print(f"\n[出错] {exc}")
        print("如果反复出错，请把图片路径和错误信息发给开发者。")
        rc = 1
    else:
        print(f"\n[完成] 生成的文件都在“{res.out_dir}”文件夹里：")
        print(f"  像素格数    : {res.width} x {res.height}（每像素 {scale}×{scale} 方块）")
        print(f"  成品尺寸    : {res.width * scale} x {res.height * scale} 方块"
              f"（共 {res.width * res.height * scale * scale:,} 个方块，游戏里占这么大）")
        print("  作品记录：作品记录.json / 作品数据.npz，材料和预览在应用内查看。")
        if res.schematic:
            print(f"  TEdit图纸(混合版)        : {res.schematic.name}")
        if res.schematic_wall:
            print(f"  TEdit图纸(背景墙版) : {res.schematic_wall.name}")
        if res.schematic_map:
            print(f"  TEdit图纸(地图版) : {res.schematic_map.name}")


    if rc != 0:
        # 出错时停留一下，方便看错误信息；正常生成完则自动关闭窗口
        _pause()
    return rc


if __name__ == "__main__":
    sys.exit(run_interactive())
