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
KNOWN_HTML = {
    "html", "head", "body", "meta", "link", "title", "style", "script",
    "p", "div", "span", "em", "strong", "code", "pre", "br", "hr", "a", "img",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "dl", "dt", "dd", "blockquote",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "col", "colgroup",
    "figure", "figcaption", "sup", "sub", "b", "i", "u", "small", "svg", "text", "tspan",
    "main", "header", "footer", "nav", "section", "article", "aside", "template", "noscript",
}

# 绘图元素：**只有在 <svg> / <math> 子树内部**才算已知标签。
# 为什么不直接并进上面那张表（2026-10-19 独立会审的意见）：
#   `<path>` `<g>` 这类名字一旦全局放行，正文里一个真正的裸 `<path>` 就再也不会被报出来
#   —— 扩白名单在修掉误报的同时，会把「正文里的裸尖括号」这条检测面一起削掉。
#   改成按位置豁免，两边都保住：SVG 子树里放行（那本来就是标签），子树外照报。
KNOWN_GRAPHIC = {
    # ── SVG 绘图元素 ─────────────────────────────────────────────
    # 本 skill 要求「承载空间/结构/拓扑关系的内容必须配图」，讲义里手写内联 SVG
    # （电路图、卡诺图区块）很常见。不认这些名字，门禁会在**正常**讲义上误报上百处、
    # 退出码 1，反而让「退出码必须为 0」这条硬规则失效。
    # 2026-10-17 实测：一份含 8 张内联 SVG 的讲义被误报 128 处，而数学区真正的裸尖括号是 0 处。
    "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "defs", "use", "symbol", "marker", "pattern", "clippath", "mask", "image",
    "lineargradient", "radialgradient", "stop", "filter", "fegaussianblur",
    "feoffset", "femerge", "femergenode", "feblend", "fecolormatrix",
    "foreignobject", "animate", "animatetransform", "switch", "desc",
    # ── MathML（MathJax 行内输出会用）────────────────────────────
    "math", "mrow", "mi", "mo", "mn", "ms", "mtext", "msup", "msub", "msubsup",
    "mfrac", "msqrt", "mroot", "mtable", "mtr", "mtd", "mstyle", "mspace",
    "semantics", "annotation", "annotation-xml", "mpadded", "mphantom", "menclose",
    "mglyph", "mmultiscripts", "mprescripts", "none",
}
tagpat = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9]*)([^>]*)>")

# 注释与 <code>/<pre> 里是「给人看的例子」，不构成真正的标签容器
_MASKED = re.compile(r"<!--.*?-->|<(code|pre)\b[^>]*>.*?</\1\s*>", re.S | re.I)


def _subtrees(tag: str) -> list:
    """返回 `<tag ...> ... </tag>` 的区间（支持嵌套）。

    三条刻意的保守设定（2026-10-19 第二轮会审提出后补的）：
      1. **注释与 `<code>/<pre>` 里的伪标签不算**。否则 `<!-- <svg> -->` 这种没有配对的
         `</svg>`，会把后面整篇正文都划进「SVG 子树」，正文里的裸 `<path>` 就再也报不出来。
      2. **未闭合的子树不豁免**（直接丢弃，而不是延伸到文末）。宁可让一个真的忘了闭标签的
         文档被报出来（它本来就是坏的），也不能让它顺手放过后面的正文。
      3. 只按名字匹配 `<tag` 与 `</tag>`，属性里带 `>` 的情况会提前截断——代价是可能少豁免
         一小段，方向仍然是「多报」而不是「漏报」。
    """
    masked = [(m.start(), m.end()) for m in _MASKED.finditer(html)]

    def in_masked(pos):
        return any(a <= pos < b for a, b in masked)

    spans, depth, start = [], 0, None
    for m in re.finditer(r"<(/?)" + tag + r"\b[^>]*>", html, re.I):
        if in_masked(m.start()):
            continue
        if m.group(1) == "/":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    spans.append((start, m.end()))
                    start = None
        else:
            if depth == 0:
                start = m.start()
            depth += 1
    return spans        # depth != 0 → 未闭合 → 不豁免


_graphic_spans = _subtrees("svg") + _subtrees("math")


def _in_graphic(pos: int) -> bool:
    return any(a <= pos < b for a, b in _graphic_spans)


suspicious = []
for m in re.finditer(r"<", html):
    i = m.start()
    line = html.count("\n", 0, i) + 1
    ctx = html[max(0, i - 60): i + 60].replace("\n", "\\n")
    if html[i + 1: i + 2] == "!":       # <!DOCTYPE 与 <!-- 注释，合法
        continue
    mm = tagpat.match(html, i)
    if mm:
        name = mm.group(2).lower()
        if name in KNOWN_HTML:
            continue
        if name in KNOWN_GRAPHIC and _in_graphic(i):
            continue        # 只在 <svg>/<math> 子树内部放行，正文里照报
    suspicious.append((line, html[i: i + 30].replace("\n", "\\n"), ctx))

print(f"疑似非标签的裸 '<' 共 {len(suspicious)} 处：")
for line, at, ctx in suspicious:
    print(f"  L{line}: <<{at}>>  …{ctx}…")

# ---- 数学区域内转义 ----
# 数学定界符：\(...\)、\[...\]、$...$、$$...$$
#   2026-10-17 补美元定界的原因：原来只认 \( \) 与 \[ \]，用 $ 写的公式里若有裸 <，
#   上面的全局扫描会报出来，但 --apply 不转义它 —— 报了却修不了，比不报更误导。
#   规则（尽量对齐 MathJax 的实际行为）：
#     · 定界符前面紧邻另一个 $ 时不算（那是 $$ 的一半）；是否被反斜杠转义交给 _escaped
#       按**奇偶**判定，所以 \\$ 算定界符、\$ 不算 —— 正则里刻意不加反斜杠后顾，
#       否则「偶数个反斜杠」的情况会被误挡（2026-10-17 独立复审指出）。
#     · 行内 $：开头紧跟数字的不算（价格 "$5 到 $6"）；首尾带空白的写法 MathJax 本身
#       也不认，这里跟着不认；长度上限 _INLINE_MAX 只用于行内，防跨句错配。
#     · 块级 $$：**不限长度、不限制空白**（display math 里常有换行与缩进，限长会静默漏检
#       长公式，复审指出的正是这一点）。
#   已知取舍：块级 $$ 在正文里成对出现极少，误判的代价只是把中间的 < > & 转成实体
#   （浏览器与 MathJax 都会还原成原字符），显示不变。
_INLINE_MAX = 300   # 行内公式长度上限，超过基本可断定是跨句错配

_DOLLAR_BLOCK = re.compile(r"(?<!\$)\$\$((?:\\.|[^$\\])+?)\$\$(?!\$)", re.S)
_DOLLAR_INLINE = re.compile(r"(?<!\$)\$(?![\d$])((?:\\.|[^$\\\n])+?)(?<![\s\\])\$(?!\d)", re.S)
_PAREN = re.compile(r"\\\(([^\n]*?)\\\)")   # 行内公式不跨行：未闭合时不会吞掉后面一大段
_BRACK = re.compile(r"\\\[(.*?)\\\]", re.S)


def _escaped(text: str, i: int) -> bool:
    """text[i] 前面的连续反斜杠是奇数个 → 这个字符被转义了。"""
    n = 0
    while i - n - 1 >= 0 and text[i - n - 1] == "\\":
        n += 1
    return n % 2 == 1


def _collect(matches, max_len=None, existing=()) -> list:
    """收数学区域：过滤被转义的定界符、超长区间和与已收区间重叠的候选。"""
    spans = list(existing)
    for m in matches:
        if _escaped(html, m.start()):
            continue
        s, e = m.start(1), m.end(1)
        if max_len is not None and e - s > max_len:
            continue
        if any(s < b and a < e for a, b in spans):
            continue
        spans.append((s, e))
    return spans


# 顺序有讲究：先收无歧义的 \( \) 与 \[ \]，再收美元 —— 美元一旦误配，
# 重叠剔除会让它自己出局，绝不会把真的 \[ \] 公式顶掉。
math_spans = _collect(_PAREN.finditer(html))
math_spans += _collect(_BRACK.finditer(html), existing=math_spans)
math_spans += _collect(_DOLLAR_BLOCK.finditer(html), existing=math_spans)
math_spans += _collect(_DOLLAR_INLINE.finditer(html), _INLINE_MAX, existing=math_spans)
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
