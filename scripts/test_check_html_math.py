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
    ("块级 $$ 不限长(320 字符)", "<p>$$" + "a<b " * 80 + "$$</p>", ("&lt;", None)),
    ("块级 $$ 允许首尾空白", "<p>$$ a < b $$</p>", ("&lt;", None)),
    ("偶数反斜杠后的 $ 仍是定界符", "<p>\\\\$a<b$</p>", ("&lt;", None)),
    ("行内 $ 超长不认(320)", "<p>$" + "a<b " * 80 + "$</p>", (None, "&lt;")),
    ("跨定界符重叠只收一次", r"<p>\(a $b<c$ d\)</p>", ("&lt;", None)),
    ("未闭合 \\( 不跨行吞段", "<p>\\(a<b\n c>d\\)</p>", (None, "&lt;")),
    ("已有实体不重复转义", "<p>$a &lt; b$</p>", ("&amp;lt;", None)),  # 见下方说明
    # ── 2026-10-19：讲义里内联画电路图（SVG）曾被整张判成裸尖括号，128 处假阳性 ──
    ("内联 SVG 电路图不误报",
     '<svg viewBox="0 0 10 10"><g><rect x="0" y="0" width="4" height="4"/>'
     '<path d="M0 0 L10 10"/><polyline points="0,0 4,4"/><text x="1" y="1">A</text>'
     '<tspan x="1" y="2">1</tspan></g></svg>',
     (None, "&lt;")),
    ("MathML 不误报",
     "<math><mrow><mi>a</mi><mo>+</mo><mi>b</mi></mrow></math>",
     (None, "&lt;")),
    ("SVG 与公式共存时仍能抓裸尖括号",
     '<svg><path d="M0 0 L1 1"/></svg><p>$a<b$</p>',
     ("&lt;", None)),
    # ── 2026-10-19 会审打进来的反例：数学区里恰好出现「合法标签形状」 ──
    # 这类是扩白名单最危险的漏检面：`<path>` 现在进了 KNOWN，若判断走白名单就会被静默放过。
    # 实测它们由数学区直接扫描路径抓获，与白名单无关；这四条就是钉住这一点，防以后改坏。
    ("数学区里出现合法标签形状(path)", "<p>$a<path>b$</p>", ("&lt;", None)),
    ("数学区里出现合法标签形状(mi)", "<p>$a<mi>x</mi>$</p>", ("&lt;", None)),
    ("数学区里的标签形状带属性", '<p>$a<g class="x">y</g>$</p>', ("&lt;", None)),
    ("老路径里的标签形状带属性", '<p>\\(a<rect width="4">b\\)</p>', ("&lt;", None)),
]

# 只看退出码的用例（不走 --apply 流程）：白名单/子树边界一旦放宽过头，这里会立刻变红。
# 期望 1 = 必须报出来；0 = 必须不报。
EXIT_CASES = [
    ("正常的闭合 svg 子树", '<svg><g><path d="M0 0"/></g></svg>', 0),
    # 注释里的伪 <svg> 没有配对闭标签；若照单全收，后面整篇都会被划进「SVG 子树」
    ("注释里的伪 svg 不扩大豁免区", '<!-- <svg> --><p><path d="M0 0"></p>', 1),
    ("code 里的伪 svg 不扩大豁免区", '<code><svg></code><p><path d="M0 0"></p>', 1),
    # 未闭合的 svg 不豁免：宁可把坏文档报出来，也不顺手放过后面的正文
    ("未闭合 svg 之后正文仍被报", '<svg><path d="M0 0"/><p><mi x></p>', 1),
    ("正文里的绘图标签", '<p>正文 <path d="M0 0"> 不在 svg 里</p>', 1),
    # 属性里带 `>` 会提前截断，但方向必须是「少豁免」而不是「多豁免」
    ("属性里带 > 的 svg 仍正确豁免", '<svg data-a="x>y"><path d="M0 0"/></svg>', 0),
    ("错配嵌套后的正文标签仍被报", '<svg><g></svg><path d="M0 0">', 1),
    # 能**单独**隔离出「注释/code 伪标签不配对」这条守卫的用例（2026-10-19 第四轮会审给出的构造）：
    # 若不许 code 里的 <svg> 参与配对，它会与后面那个孤立的 </svg> 配成一个假子树，
    # 把中间真正的裸 <path> 划进豁免区 —— 实测关掉这条守卫后，本行从 exit=1 变成 exit=0（漏报）。
    ("code 里的伪 svg 不能与真实闭标签配对", '<code><svg></code><p><path d="M0 0"/></svg>', 1),
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
    for name, html_text, want_code in EXIT_CASES:
        code, out, log = run(html_text, apply=False)
        ok = code == want_code
        print(("PASS " if ok else "FAIL ") + name
              + ("" if ok else "  → exit=%d，期望 %d" % (code, want_code)))
        if not ok:
            fails += 1
            print("  log: " + log.strip().replace("\n", " | ")[:300])
    total = len(CASES) + len(EXIT_CASES)
    print("%d/%d" % (total - fails, total))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
