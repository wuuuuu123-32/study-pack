#!/usr/bin/env python3
r"""check_html_math.py 的回归测试（不依赖 pytest，直接 python 跑）。

    python scripts/test_check_html_math.py

重点覆盖 2026-10-17 新增的美元符号定界符：$...$ 与 $$...$$ 必须被识别并转义，
而价格 "$5 到 $6"、转义美元 \$、未闭合的 $$ 不能被当成公式。
"""
import io
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "check_html_math.py")
PY = sys.executable

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CASES = [
    # (名字, 输入片段, 期望：转义后包含 / 不含)
    ("块级 $$: 裸 <", "<p>$$a<b$$</p>", ("&lt;", None)),
    ("行内 $: 裸 >", "<p>$A>B$</p>", ("&gt;", None)),
    ("行内 $: 裸 &", "<p>$x&y$</p>", ("&amp;", None)),
    ("表达式里有反斜杠", r"<p>$\alpha<\beta$</p>", ("&lt;", None)),
    ("老路径 \\[..\\]", r"<p>\[y=a<b\]</p>", ("&lt;", None)),
    ("老路径 \\(..\\)", r"<p>\(y=a<b\)</p>", ("&lt;", None)),
    ("价格不当公式", "<p>价格 $5 到 $6</p>", (None, "&lt;")),
    ("转义美元不当定界符", r"<p>\$x<y\$</p>", (None, "&lt;")),
    ("未闭合 $$ 不半段错配", "<p>$$a<b</p>", (None, "&lt;")),
    ("已有实体不重复转义", "<p>$a &lt; b$</p>", ("&amp;lt;", None)),  # 见下方说明
]


def run(html_text, apply=False):
    fd, path = tempfile.mkstemp(suffix=".html")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(html_text)
        args = [PY, SCRIPT, path] + (["--apply"] if apply else [])
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
        with open(path, encoding="utf-8") as f:
            return r.returncode, f.read(), r.stdout + r.stderr
    finally:
        os.unlink(path)


def main():
    fails = 0
    for name, html_text, (want_in, want_out) in CASES:
        code, out, log = run(html_text, apply=True)
        ok = True
        if name == "已有实体不重复转义":
            # &lt; 应原样保留，不能被二次转义成 &amp;lt;
            ok = "&amp;lt;" not in out and "&lt;" in out
        elif want_in:
            ok = want_in in out
        elif want_out:
            ok = want_out not in out
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  → " + repr(out)))
        if not ok:
            fails += 1
            print("  log: " + log.strip().replace("\n", " | ")[:300])
    print("%d/%d" % (len(CASES) - fails, len(CASES)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
