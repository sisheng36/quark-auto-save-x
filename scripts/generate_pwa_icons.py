#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PWA 图标生成脚本（开发期工具，可重复执行）。

用途
----
以仓库中的 app/static/images/apple-touch-icon.png（180x180 原始图标）为唯一素材，
生成 PWA（Progressive Web App）所需的各尺寸 PNG 图标，输出到
app/static/images/pwa/ 目录：

  - icon-192.png      192x192，普通用途（manifest 中 purpose=any）
  - icon-512.png      512x512，普通用途（manifest 中 purpose=any）
  - maskable-512.png  512x512，Android 自适应图标（manifest 中 purpose=maskable）
                      源图按 60% 缩放后居中放置在纯色背景 #0d0b1f 上，
                      以保证系统裁切成圆形/水滴形时主体不会被切掉

脚本不会修改源图 apple-touch-icon.png，仅读取它。
重复执行会直接覆盖同名产物，结果幂等。

依赖
----
Pillow（已在本机安装，版本 10.4.0）：
    python3 -m pip install "Pillow>=10"

运行方式
--------
在仓库根目录执行：
    python3 scripts/generate_pwa_icons.py

脚本会自动定位仓库根目录，因此在任意工作目录下执行均可。
"""

from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# 路径常量：脚本位于 <repo>/scripts/generate_pwa_icons.py
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)

SOURCE_IMAGE = os.path.join(REPO_ROOT, "app", "static", "images", "apple-touch-icon.png")
OUTPUT_DIR = os.path.join(REPO_ROOT, "app", "static", "images", "pwa")

# 品牌深色背景色，与 manifest / offline.html 保持一致
BRAND_BG_COLOR = (0x0D, 0x0B, 0x1F)  # #0d0b1f

# 自适应图标内容占画布的比例（Android maskable 安全区约为 60%~80%）
MASKABLE_SCALE = 0.60


def fail(message: str) -> None:
    """打印中文错误信息并以退出码 1 结束。"""
    print("[错误] " + message, file=sys.stderr)
    sys.exit(1)


def load_pillow():
    """导入 Pillow；缺失时给出明确的中文提示并退出（不静默跳过）。"""
    try:
        from PIL import Image
    except ImportError:
        fail(
            "未检测到 Pillow 库，无法生成 PWA 图标。\n"
            "        请先安装依赖： python3 -m pip install \"Pillow>=10\"\n"
            "        或使用虚拟环境执行本脚本。"
        )
        raise  # 仅为满足类型检查与流程控制，实际不会执行到这里
    return Image


def save_png(image, path: str) -> None:
    """以 optimize=True 保存 PNG（体积更小，浏览器与系统均支持）。"""
    image.save(path, format="PNG", optimize=True)
    print("  已生成: %s" % os.path.relpath(path, REPO_ROOT))


def main() -> None:
    Image = load_pillow()

    if not os.path.isfile(SOURCE_IMAGE):
        fail(
            "找不到源图标文件: %s\n"
            "        请确认仓库中已包含 app/static/images/apple-touch-icon.png。"
            % SOURCE_IMAGE
        )

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("PWA 图标生成中...")
    print("  源图: %s" % os.path.relpath(SOURCE_IMAGE, REPO_ROOT))

    with Image.open(SOURCE_IMAGE) as source:
        # 统一转成 RGB，避免源图为带透明通道的调色板/LA 模式时合成出错
        source = source.convert("RGB")
        print("  源图尺寸: %dx%d" % source.size)

        # ---- 1. 普通用途图标 192x192 ----------------------------------------
        icon_192 = source.resize((192, 192), Image.LANCZOS)
        save_png(icon_192, os.path.join(OUTPUT_DIR, "icon-192.png"))

        # ---- 2. 普通用途图标 512x512 ----------------------------------------
        icon_512 = source.resize((512, 512), Image.LANCZOS)
        save_png(icon_512, os.path.join(OUTPUT_DIR, "icon-512.png"))

        # ---- 3. 自适应图标 maskable-512x512 --------------------------------
        # 源图缩放到画布的 60%，居中贴到品牌深色背景上，避免系统裁切时切掉主体。
        canvas_size = 512
        inner_size = int(round(canvas_size * MASKABLE_SCALE))  # 307
        inner = source.resize((inner_size, inner_size), Image.LANCZOS)

        canvas = Image.new("RGB", (canvas_size, canvas_size), BRAND_BG_COLOR)
        offset = ((canvas_size - inner_size) // 2, (canvas_size - inner_size) // 2)
        canvas.paste(inner, offset)
        save_png(canvas, os.path.join(OUTPUT_DIR, "maskable-512.png"))

    print("完成。")


if __name__ == "__main__":
    main()
