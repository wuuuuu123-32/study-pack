#!/usr/bin/env python3
"""检查（并可选修复）讲义 HTML 里裸的尖括号。

用法：
    python scripts/check_html_math.py out/第5章 讲义.html          # 只检查
    python scripts/check_html_math.py out/第5章 讲义.html --apply  # 就地修复

为什么要它（根因，2026-10-17 定位）：
    数学式里写了裸的 `<`，例如
        \\[ Y_{A>B} = AB' \\qquad Y_{A<B} = A'B \\]
    浏览器与 pandoc 的 HTML 解析器都会把 `<B} = A'B ...` 当成一个标签名，
    一直吞到下一个 `>`（通常就是 `</div>` 的 `>`），于是：
      ① 公式后半段从 DOM 里消失（"HTML 看着没问题"也可能是漏的）；
      ② 那个 `</div>` 被吃掉，div 从此不闭合；
      ③ 转 LaTeX 时后面所有 longtable 都被嵌进 tcolorbox，\\ifinner 为真，
         每个 figure 报 "! LaTeX Error: Not in outer par mode." —— 报错在 LaTeX，病根在 HTML。

    修法：数学环境内所有裸 < > & 一律转义成 &lt; &gt; &amp;
    （浏览器与 pandoc 都会还原成原字符，公式内容不变）。

退出码：0 = 没有可疑处；1 = 有可疑处（便于当门禁用）。
"""
import collections
import io
import re
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_args = [a for a in sys.argv[1:] if not a.startswith("--")]
if not _args:
    print(__doc__)
    sys.exit(2)
PATH = _args[0]
APPLY = "--apply" in sys.argv

html = open(PATH, encoding="utf-8").read()

# 允许出现的标签名白名单（其余 `<xxx` 一律可疑）
KNOWN = {
    "html", "head", "body", "meta", "link", "title", "style", "script",
    "p", "div", "span", "em", "strong", "code", "pre", "br", "hr", "a", "img",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "dl", "dt", "dd", "blockquote",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "col", "colgroup",
    "figure", "figcaption", "sup", "sub", "b", "i", "u", "small", "svg", "text", "tspan",
    "main", "header", "footer", "nav", "section", "article", "aside", "template", "noscript",
}
tagpat = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9]*)([^>]*)>")

suspicious = []
for m in re.finditer(r"<", html):
    i = m.start()
    line = html.count("\n", 0, i) + 1
    ctx = html[max(0, i - 60): i + 60].replace("\n", "\\n")
    if html[i + 1: i + 2] == "!":       # <!DOCTYPE 与 <!-- 注释，合法
        continue
    mm = tagpat.match(html, i)
    if not mm or mm.group(2).lower() not in KNOWN:
        suspicious.append((line, html[i: i + 30].replace("\n", "\\n"), ctx))

print(f"疑似非标签的裸 '<' 共 {len(suspicious)} 处：")
for line, at, ctx in suspicious:
    print(f"  L{line}: <<{at}>>  …{ctx}…")

# ---- 数学区域内转义 ----
# 数学定界符：\(...\)、\[...\]、$...$、$$...$$（美元符号这两种是 2026-10-17 补的）
#   为什么补：原来只认 \( \) 与 \[ \]，用 $ 写的公式里若有裸 <，上面第 53 行的全局扫描
#   会把它报出来，但 --apply 不转义它 —— 报了却修不了，比不报更误导。
#   美元定界要防三类误判：
#     ① 价格 "$5 到 $6"：开定界符后不能是空白、收定界符后不能紧跟数字；
#     ② 转义美元 \$：前导反斜杠为奇数时不算定界符；
#     ③ 未闭合的 $$：单个 $ 前后紧邻另一个 $ 时不算定界符，避免半段错配。
#   已知取舍：$5+x$ 这种既像价格又像公式的串会被当成公式 —— 后果只是把里面的
#   < > & 转成实体（浏览器与 MathJax 都会还原成原字符），显示不变，所以可接受。
_LEN_MAX = 300   # 单条公式长度上限，超过基本可断定是错配


def _escaped(text: str, i: int) -> bool:
    """text[i] 前面的连续反斜杠是奇数个 → 这个字符被转义了。"""
    n = 0
    while i - n - 1 >= 0 and text[i - n - 1] == "\\":
        n += 1
    return n % 2 == 1


def _collect(matches) -> list:
    """收数学区域，过滤转义符、超长和与已收区间重叠的候选。"""
    spans = []
    for m in matches:
        if _escaped(html, m.start()):
            continue
        s, e = m.start(1), m.end(1)
        if e - s > _LEN_MAX:
            continue
        if any(s < b and a < e for a, b in spans):
            continue
        spans.append((s, e))
    return spans


math_spans = _collect(re.compile(r"(?<!\\)\$\$(?![\s$])((?:\\.|[^$\\])+?)(?<![\s\\])\$\$", re.S).finditer(html))
math_spans += _collect(re.compile(r"(?<![\\$])\$(?![\s$])((?:\\.|[^$\\])+?)(?<![\s\\$])\$(?!\d)", re.S).finditer(html))
math_spans += _collect(re.compile(r"\\\((.*?)\\\)", re.S).finditer(html))
math_spans += _collect(re.compile(r"\\\[(.*?)\\\]", re.S).finditer(html))
math_spans.sort()

ENTITY = re.compile(r"&(?:lt|gt|amp|quot|#\d+|#x[0-9a-fA-F]+);")


def bare(seg: str) -> str:
    """去掉已有实体后剩下的裸字符（已转义的不再报）。"""
    return ENTITY.sub("", seg)


need = [(a, b, html[a:b]) for a, b in math_spans if re.search(r"[<>&]", bare(html[a:b]))]
print(f"\n数学区域共 {len(math_spans)} 个，其中含**裸** < > & 的有 {len(need)} 个：")
for a, b, seg in need:
    print(f"  L{html.count(chr(10), 0, a) + 1}: {seg[:90]}")

if not APPLY:
    print("\n（未改动；加 --apply 才写回）")
    sys.exit(1 if (suspicious or need) else 0)

out, prev = [], 0
cnt = collections.Counter()
for a, b in sorted((a, b) for a, b, _ in need):
    if a < prev:
        continue
    seg = html[a:b]
    fixed = (seg.replace("&lt;", "\x00L\x00").replace("&gt;", "\x00G\x00")
                .replace("&amp;", "\x00A\x00"))
    cnt["<"] += fixed.count("<")
    cnt[">"] += fixed.count(">")
    cnt["&"] += fixed.count("&")
    fixed = fixed.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    fixed = (fixed.replace("\x00L\x00", "&lt;").replace("\x00G\x00", "&gt;")
                  .replace("\x00A\x00", "&amp;"))
    out.append(html[prev:a])
    out.append(fixed)
    prev = b
out.append(html[prev:])

open(PATH, "w", encoding="utf-8", newline="").write("".join(out))
print(f"\n已写回 {PATH}：转义 < {cnt['<']} 个、> {cnt['>']} 个、& {cnt['&']} 个")
sys.exit(0)
