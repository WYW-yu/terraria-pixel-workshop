#!/usr/bin/env python3
"""泰拉瑞拉像素画生成器 - 入口。

- 无参数运行（双击 exe）：打开桌面界面。
- 带参数运行：命令行模式。
  用法示例:
    python main.py 图片.png --width 100 --scale 2 --schematic --out 输出
"""
from __future__ import annotations

import argparse
import sys



def cli_main(argv: list[str]) -> int:
    from terraria_pixel.interactive import run_interactive
    from terraria_pixel.pipeline import run_conversion, prepare_preview
    # 控制台编码兜底：避免 GBK 控制台下打印特殊字符崩溃
    try:
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(
        prog="泰拉瑞拉像素画生成器",
        description="把图片转成泰拉瑞拉像素画，保存作品数据及可选TEdit图纸；在桌面历史记录中查看图片和材料。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("image", nargs="?", help="输入图片路径（png/jpg 等）")
    parser.add_argument("--width", type=int, default=100,
                        help="目标宽度（像素，即图纸的方块列数）")
    parser.add_argument("--scale", type=int, default=1,
                        help="每个像素在游戏里占 scale×scale 个方块，越大越显眼")
    parser.add_argument("--out", default="输出", help="输出目录")
    parser.add_argument("--name", default=None, help="作品/图纸名称（默认用图片名）")
    parser.add_argument("--schematic", action="store_true",
                        help="额外生成 TEdit 可导入图纸（混合版、背景墙版、地图版各一份）")
    parser.add_argument("--sampling", choices=["auto", "nearest", "area", "edge"], default="auto",
                        help="缩小算法：自动 / 保留像素 / 面积平均 / 轮廓增强")
    parser.add_argument("--color-limit", type=int, default=0, help="原图颜色上限：0 不限，或 2–256")
    parser.add_argument("--dither", choices=["none", "bayer", "floyd"], default="none", help="材料颜色抖动")
    parser.add_argument("--dither-strength", type=float, default=0.75, help="抖动强度 0–1")
    parser.add_argument("--detail", type=float, default=0.4, help="轮廓增强程度 0–1")
    parser.add_argument("--contrast", type=float, default=1, help="对比度 0–2")
    parser.add_argument("--saturation", type=float, default=1, help="饱和度 0–2")
    parser.add_argument("--gamma", type=float, default=1, help="Gamma 0.2–3；大于 1 提亮")
    parser.add_argument("--world", help="将像素画放入此 .wld 世界，必须配合 --world-out；不覆盖原世界")
    parser.add_argument("--world-out", help="另存的新 .wld 路径，不能为已有文件")
    parser.add_argument("--world-version", choices=["fine", "wall", "map"], default="fine", help="写入世界的材料版本")
    parser.add_argument("--world-x", type=int, default=0, help="像素画左上角的世界 X 坐标（从0开始）")
    parser.add_argument("--world-y", type=int, default=0, help="像素画左上角的世界 Y 坐标（从0开始）")
    parser.add_argument("--no-open", action="store_true",
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if bool(args.world) != bool(args.world_out):
        parser.error("--world 和 --world-out 必须同时填写。")
    if args.world and (not args.image or args.schematic):
        parser.error("导入世界需要图片路径，且不能同时指定 --schematic。")

    if not args.image:
        # 没有图片参数：进入引导模式（对小白友好）
        return run_interactive()

    try:
        operation = prepare_preview if args.world else run_conversion
        res = operation(
            args.image,
            width=args.width,
            scale=args.scale,
            out_dir=args.out,
            name=args.name,
            make_schematic=args.schematic,
            sampling=args.sampling, color_limit=args.color_limit, dither=args.dither,
            dither_strength=args.dither_strength, detail=args.detail, contrast=args.contrast,
            saturation=args.saturation, gamma=args.gamma,
        )
        if args.world:
            from terraria_pixel.world import load_world, import_into_world
            from terraria_pixel.history import HistoryStore, save_world_import_record
            from pathlib import Path
            document = load_world(args.world, overview=False)
            path = import_into_world(res, document, args.world_out, version=args.world_version,
                                     x=args.world_x, y=args.world_y)
            print(f"\n新世界已保存：{path}（原世界未修改）")
            try:
                record = save_world_import_record(res, args.out, path, source=document.path,
                    version=args.world_version, x=args.world_x, y=args.world_y,
                    coating=False if args.world_version == 'map' else res.processing.get('coating', True))
                base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
                HistoryStore(base / '历史记录.json', base / '输出').remember(record.out_dir)
                print(f"作品历史记录已保存：{record.out_dir}")
            except Exception as exc:
                print(f"[提示] 世界已成功保存；作品历史记录保存未完成：{exc}。无需再次导入世界。", file=sys.stderr)
            return 0
    except Exception as exc:  # 给小白友好报错
        print(f"\n[出错] {exc}", file=sys.stderr)
        return 1

    print(f"\n完成！输出目录: {res.out_dir}")
    print(f"  像素尺寸 : {res.width} × {res.height}")
    print("  作品记录 : 作品记录.json / 作品数据.npz（在应用的历史记录中打开）")
    if res.schematic:
        print(f"  TEdit图纸: {res.schematic} / {res.schematic_wall} / {res.schematic_map}")
    return 0


if __name__ == "__main__":
    if not sys.argv[1:] or sys.argv[1:] == ["--gui"]:
        from terraria_pixel.desktop import run_gui
        sys.exit(run_gui())
    elif sys.argv[1:] == ["--console"]:
        from terraria_pixel.interactive import run_interactive
        sys.exit(run_interactive())
    else:
        sys.exit(cli_main(sys.argv[1:]))
