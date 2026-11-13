# -*- coding: utf-8 -*-
"""列出讲义的节结构：ID / 标题 / 字符数 / 在第几页。

用途只有一个：**写修改清单**。用户要求「改了哪些地方、现在在第几页」，
而这两件事必须分开对待——

  · **ID**（`s23` / `p1` / `prob-13-13`）是主键：插入内容后它不变，能定位。
  · **页码**是辅助：插一段就整体后移，不能拿来当索引。

所以本脚本把两者一起输出，但顺序是「先 ID，后页码」。

用法
----
    python scripts/outline.py --html build/lecture.html
    python scripts/outline.py --html build/lecture.html --pdf build/lecture-test.pdf

`--pdf` 会给每节查页码（用 pdftotext 逐页搜标题前 10 个字符）。页数多时慢一些，
几十页的量级一两秒就够。
"""
import argparse
import io
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HEAD = re.compile(r"<h([2-4])([^>]*)>(.*?)</h\1>", re.S)
ID = re.compile(r'id="([^"]+)"')
TAG = re.compile(r"<[^>]+>")


def plain(s):
    return (TAG.sub("", s).replace("&lt;", "<").replace("&gt;", ">")
            .replace("&amp;", "&").strip())


def page_of(title, pages, cache):
    key = re.sub(r"[\s　]+", "", title)[:10]
    if not key:
        return ""
    if key in cache:
        return cache[key]
    for p in sorted(pages):
        if key in pages[p]:
            cache[key] = "p%d" % p
            return cache[key]
    return ""


def main():
    ap = argparse.ArgumentParser(description="列出讲义节结构")
    ap.add_argument("--html", nargs="+", required=True)
    ap.add_argument("--pdf", default=None, help="给了才查页码")
    ap.add_argument("--min-chars", type=int, default=0, help="只列出字符数 ≥ 该值的节")
    a = ap.parse_args()

    text = "".join(io.open(p, encoding="utf-8").read() for p in a.html)
    marks = [(m.start(), m.group(1), m.group(2), plain(m.group(3)))
             for m in HEAD.finditer(text)]

    pages, cache = {}, {}
    if a.pdf:
        n = 1
        while n < 200:
            r = subprocess.run(["pdftotext", "-f", str(n), "-l", str(n), a.pdf, "-"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace")
            if r.returncode != 0 or not (r.stdout or "").strip():
                break
            pages[n] = re.sub(r"[\s　]+", "", r.stdout)
            n += 1

    for i, (pos, level, attrs, title) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        if not title:
            continue
        n = end - pos
        if n < a.min_chars:
            continue
        mid = ID.search(attrs)
        sid = mid.group(1) if mid else "-"
        pg = page_of(title, pages, cache) if pages else ""
        print("%-4s %-12s %-6s %6d  %s"
              % ("h" + level, sid, pg, n, title[:56]))


if __name__ == "__main__":
    main()
