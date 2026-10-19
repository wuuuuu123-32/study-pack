#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开工前的工具清点（study-pack §零 的强制前置动作）。

    python scripts/check_tooling.py                    # 清点并给建议
    python scripts/check_tooling.py --need schemdraw,matplotlib
                                                       # 额外要求：这两项必须有，缺了 exit 1
    python scripts/check_tooling.py --quiet            # 只输出缺口与结论

为什么要有它：skill 里的规则多是「遇到情况该怎么做」，但「你手上到底有什么」这件事
**靠想是想不出来的**——真正会发生的事是：明明装了工具却忘了用，或者缺了工具就默默降级交付。
所以把它做成一次真实的探测（查 PATH、查 import、查目录），输出一张表，让缺口看得见。

🕳 不负责装东西。缺失只报告 + 给安装命令，装不装由用户决定（安装属于「要先问」）。
"""
import argparse
import importlib.util
import io
import os
import shutil
import sys
import unicodedata

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# 不在 PATH 里、但常见装在这些位置的命令（找到就报真实路径）
KNOWN_DIRS = []
if os.name == "nt":
    KNOWN_DIRS = [
        r"D:\texlive\2025\bin\windows",          # TeX Live 自带 poppler + xelatex
        r"C:\Program Files\Google\Chrome\Application",
        r"C:\Program Files (x86)\Microsoft\Edge\Application",
        r"C:\Program Files\Microsoft\Edge\Application",
    ]
KNOWN_DIRS += [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]

# key, 用途, 类型, 探测目标, 缺失时的安装建议, 缺失时的降级方案
CAPS = [
    # ── PDF / 文档 ────────────────────────────────────────────────
    ("pdfinfo",   "读 PDF 页数/页面尺寸/生成器", "cmd", ["pdfinfo"],
     None, "用 pypdf 读 /Annots 与 /MediaBox"),
    ("pdftotext", "从 PDF 抽文字（核对内容是否进去了）", "cmd", ["pdftotext"],
     None, "python -c 'import fitz' 或 pypdf 抽文本"),
    ("pdftoppm",  "**把 PDF 抽页渲染成 PNG（目视核对的唯一手段）**", "cmd", ["pdftoppm", "pdftocairo"],
     "装 TeX Live，或 `pip install pymupdf` 后用 fitz 渲染",
     "pymupdf：`import fitz; page.get_pixmap()`"),
    ("pandoc",    "HTML→LaTeX 备用路线", "cmd", ["pandoc"],
     "winget install JohnMacFarlane.Pandoc", "无（只能走浏览器打印）"),
    ("xelatex",   "LaTeX 备用路线的排版引擎", "cmd", ["xelatex"],
     "装 TeX Live / MiKTeX", "无（只能走浏览器打印）"),
    # ── HTML → PDF ───────────────────────────────────────────────
    ("chromium",  "**浏览器无头打印（首选出片路线，8 秒）**", "cmd", ["msedge", "chrome", "chromium"],
     "装 Edge/Chrome", "pandoc + xelatex（版式会变，要告知用户）"),
    # ── 图 ────────────────────────────────────────────────────────
    ("PIL",       "图片裁剪/拼图（contact sheet、读手写照片）", "py", ["PIL"],
     "pip install pillow", "无（很多核对做不了）"),
    ("matplotlib", "函数图、坐标图、曲线", "py", ["matplotlib"],
     "pip install matplotlib", "SVG 手写"),
    ("schemdraw", "**电路图/门电路（声明式画，不用手算坐标）**", "py", ["schemdraw"],
     "pip install schemdraw", "手写内联 SVG —— 必须再跑 visual_check，人工看有没有压字"),
    ("graphviz",  "流程图/依赖图/状态机", "py", ["graphviz"],
     "pip install graphviz + 装 graphviz 可执行文件", "手写 SVG 或用 mermaid"),
    # ── Office / 提取 ─────────────────────────────────────────────
    ("python-pptx", "读 PPT 的文字/表格/图片/备注", "py", ["pptx"],
     "pip install python-pptx", "解 zip + xml.etree 自己抽（很啰嗦，2026-10-19 干过一次）"),
    ("python-docx", "读写 Word", "py", ["docx"],
     "pip install python-docx", "解 zip + xml"),
    ("openpyxl",  "读写 xlsx", "py", ["openpyxl"],
     "pip install openpyxl", "pandas.read_excel / csv"),
    ("pandas",    "表格数据", "py", ["pandas"],
     "pip install pandas", "csv 模块"),
    ("pypdf",     "PDF 结构操作（合并/拆页/读元数据）", "py", ["pypdf", "PyPDF2"],
     "pip install pypdf", "pymupdf"),
    ("pymupdf",   "PDF 渲染与文本（pdftoppm 的替代）", "py", ["fitz"],
     "pip install pymupdf", "pdftoppm"),
    # ── 其它常用 ──────────────────────────────────────────────────
    ("node",      "跑 .mjs 脚本（调 GitHub API、js 工具）", "cmd", ["node"],
     "装 Node.js", "python + urllib"),
    ("git",       "交付物的版本管理 / 发布", "cmd", ["git"],
     "装 Git", "无"),
    ("ffmpeg",    "音视频抽帧/转码（看视频类任务）", "cmd", ["ffmpeg"],
     "winget install Gyan.FFmpeg", "无"),
]


def find_cmd(names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
        for d in KNOWN_DIRS:
            for ext in (".exe", ".cmd", ".bat", ""):
                cand = os.path.join(d, n + ext)
                if os.path.isfile(cand):
                    return cand
    return None


def find_py(names):
    for n in names:
        try:
            if importlib.util.find_spec(n) is not None:
                return n
        except (ImportError, ValueError):
            pass
    return None


def find_mathjax():
    """讲义公式要用本地 MathJax 副本；找不到就提示。"""
    cands = [
        os.path.join("out", "mathjax", "tex-svg.js"),
        os.path.join("mathjax", "tex-svg.js"),
    ]
    for c in cands:
        if os.path.isfile(c):
            return os.path.abspath(c)
    return None


def list_skills():
    home = os.path.expanduser("~")
    roots = [os.path.join(home, ".dsh", "skills"), os.path.join(home, ".agents", "skills")]
    out = []
    for r in roots:
        if not os.path.isdir(r):
            continue
        for name in sorted(os.listdir(r)):
            p = os.path.join(r, name)
            if os.path.isdir(p) and os.path.isfile(os.path.join(p, "SKILL.md")):
                out.append(f"{name} {'→' if _is_link(p) else '（复制，会漂移）'}")
    return out


def _is_link(p):
    """Windows 的 junction 不是 symlink，`os.path.islink` 会返回 False —— 要查 reparse point。"""
    try:
        if os.path.islink(p):
            return True
        st = os.stat(p, follow_symlinks=False)
        return bool(getattr(st, "st_file_attributes", 0) & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return False


def _w(s):
    """显示宽度：CJK 算 2 列。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s, n):
    return s + " " * max(0, n - _w(s))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--need", default="", help="逗号分隔，这些能力必须存在，缺了 exit 1")
    ap.add_argument("--quiet", action="store_true", help="只输出缺口与结论")
    a = ap.parse_args()
    need = [x.strip() for x in a.need.split(",") if x.strip()]

    rows, missing = [], []
    for key, what, kind, names, install, fallback in CAPS:
        got = find_cmd(names) if kind == "cmd" else find_py(names)
        state = "✓" if got else "✗"
        if not got:
            missing.append((key, what, install, fallback))
            got = "—"
        rows.append((state, key, what, got))

    if not a.quiet:
        print("## 1. 能力清点\n")
        print(f"{'':2} {_pad('能力', 12)} {_pad('用途', 52)} 位置")
        for state, key, what, got in rows:
            print(f"{state:2} {_pad(key, 12)} {_pad(what.replace('**', ''), 52)} {got}")
        print("\n## 2. 本地资源\n")
        mj = find_mathjax()
        print(f"{'✓' if mj else '✗':2} MathJax 本地副本  {mj or '（讲义公式需要它；从任意已有讲义目录拷一份）'}")
        print("\n## 3. 已安装 skill\n")
        sk = list_skills()
        print("   " + ("、".join(sk) if sk else "（~/.dsh/skills 下没有）"))

    print("\n## 结论\n")
    if not missing:
        print("✅ 常用能力齐备，可以直接开工。")
    else:
        print(f"❗缺 {len(missing)} 项：\n")
        for key, what, install, fallback in missing:
            print(f"  · {key:<12}{what}")
            print(f"    安装：{install or '—'}")
            print(f"    不装的降级方案：{fallback}")
        print("\n**处置规则**：缺的项只要这次任务会用到，就在开工前告诉用户并附上面的安装命令，"
              "问要不要装；**不许自己装**（安装属于「要先问」），也不许瞒着缺口降级交付。")
        print(f"\n一键安装（除 TeX Live / 浏览器等系统级）：")
        pips = [k for k, *_ in missing if
                any(c[0] == k and c[2] == "py" for c in CAPS)]
        if pips:
            print(f"  pip install " + " ".join(
                {"PIL": "pillow", "python-pptx": "python-pptx", "python-docx": "python-docx",
                 "pymupdf": "pymupdf"}.get(p, p) for p in pips))

    if need:
        lack = [n for n in need if any(m[0] == n for m in missing)]
        if lack:
            print(f"\n❗--need 指定的能力缺失：{', '.join(lack)}")
            return 1
        print(f"\n✅ --need 指定的能力齐备：{', '.join(need)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
