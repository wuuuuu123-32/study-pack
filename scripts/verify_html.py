# -*- coding: utf-8 -*-
"""讲义完整性回归检查 —— 防「内容丢失 / 重复插入 / 段落被吞 / 静默改写 / 打印时藏内容」。

为什么需要它：讲义是**增量改**出来的（按锚点字符串替换某一段、修一张图、补一节），
这类改法有两个反复出现的致命事故：

  · 事故 A：按锚点替换时区间错位 → 一次删掉「图 A + 图 B + 中间整两节正文」，
    事后只把 SVG 补回来，正文静默消失。用户读到「什么翻了没翻」才发现。
  · 事故 B：替换脚本重跑 → 同一段落被插了两份，两处内容几乎相同、互相矛盾。
  · 事故 C：改完直接手 copy 到 out/，HTML / PDF / 答疑册不是同一次构建。

三者的共同点：**改完之后没有任何「整篇长什么样」的量化记录可比**。
所以这里做的是「结构化快照 + 差分」，不是「再写一遍检查清单」。

用法
----
    # 第一次（或每次正式验收/交付之后）：把当前状态记成基线
    python scripts/verify_html.py --html build/lecture.html --record

    # 每次改完、发布之前：与基线比对，有问题 exit 1
    python scripts/verify_html.py --html build/lecture.html

    # 连 PDF 一起查（页数 / 可提取文字量 / 每一节是否真的出现在 PDF 里）
    python scripts/verify_html.py --html build/lecture.html --pdf out/x.pdf

    # 分几段写、最后拼接的讲义：直接给多个文件，按顺序拼起来比对
    python scripts/verify_html.py --html build/lecture-p1.html build/lecture-p2.html --record

退出码：0 = 可以发布；1 = 拒绝发布（或基线有问题）。

它检查什么（每一类都对应一次真实事故或一次真实漏检）
--------------------------------------------------
节这一层：
1. 节消失          —— 有 id 的 h2/h3 在基线里存在、现在没了
2. 节 id 重复      —— 同一 id 出现两次（整节被复制一份、id 没改）
3. 节标题重复      —— 标题文字与另一节完全相同（整节被复制、只改了 id）
4. 节顺序改变      —— 两节互换/搬走（公共节相对顺序变了）
5. 单节大幅缩水    —— 某节字符数掉到基线的 40% 以下（且基线本身 ≥400 字符）
6. 单节大幅变长    —— 涨到基线的 1.6 倍以上且多出 400 字符（改写的补充段反复堆叠）

段落这一层（关键：治「标题还在、正文被删一截」的变体）：
7. 节内段落被换掉  —— 该节**消失的段落字数占该节段落的 ≥35%**。
                       早先只按「净额（消失−补回）」判，"删掉 60%、再补回 48%"能混过去
                       （补回的那段也算新内容，净额只剩 12%）；改成只看消失比例后，
                       补多少都不影响判定，换掉三分之一以上就必须声明是重写。
8. 段落重复        —— 同一段文字（≥80 字符）出现次数比基线多（脚本重跑残段）。
                       不管这段有没有「定义 X-Y」「图 X-Y」编号，都能抓。

编号与引用：
9.  定义号重复 / 图号重复
10. 定义号消失 / 图号消失 —— 不只是数量，逐个编号必须存续（数量够但换了一个也报）
11. 锚点失效       —— href="#xxx" 指向的 id 在文中不存在（改节 id 后忘了改目录）

数量与成品：
12. 图 / SVG / 公式块数量骤减（掉到基线 80% 以下）
13. 打印样式藏内容 —— `@media print` 里出现 display:none / visibility:hidden /
                       font-size:0 / opacity:0：HTML 字数一点不少，交付的 PDF 却缺一块
14. PDF 层（`--pdf`）：打不开、0 页、可提取文字明显少于 HTML，
                       **以及逐节核对：每一节的标题必须在 PDF 文本里找得到**

有意改动怎么放行（不是靠调阈值，是靠显式声明）
-----------------------------------------------
    整节重写（旧内容全删、新内容更简练）：在那一节里放一行
        <!-- verify:rewrite s23 -->
    正常扩充（补了一大段，确实变长了很多）：放
        <!-- verify:expand s23 -->
    改了节 id：在 `data/CHANGES.md` 里写一行 `s3 → s23`
        （`--changes` 可指定别的路径；找不到就按"未声明"处理）

声明过的改动会在输出里列出来（"本次声明的重写：s23"），不是悄悄跳过——
这样"这一节为什么整个变了"在 diff 和清单里都留了痕。

「定义」只认定义块标签（默认 `<b class="dt">定义 1-2</b>`，单/双引号、class 里多几个词都认），
不认正文里对定义的引用——否则「见定义 1-4」会被算成第二次定义，误报一片。

⚠️ 基线的生命周期（重要）
------------------------
只有「内容确认正确、并且已经交付给读者」的版本才能 `--record`。
把一次还没检查过的改动随手 `--record`，等于把 bug 变成新基准——这个脚本就白写了。
manifest 里存了记录时间与内容指纹，事后能看出基线是哪一版。

输出最后一行的 `MD5 <12位>` 是本次**实际读到**的内容指纹。`promote.py` 会拿它跟自己
在跑检查之前记的指纹比：不一致说明"检查的"和"要发布的"不是同一份字节，直接拒绝。

自定义
------
默认认中文学科的写法（`定义 X-Y` / `图 X-Y`）。别的写法用参数换：
    --def-pattern '<b class="def">Theorem (\\d+-\\d+)</b>'
    --fig-pattern '<figcaption>Fig\\. (\\d+-\\d+)'

只按 h2/h3 切节（`--levels`，默认 "23"）。h4 通常是小标题（「考什么」「怎么下手」这类），
把它们也算成节边界，会把一节的正文切碎成一堆 40 字符的小片，然后误报一片"节缩水"——
2026-11-13 在真实讲义上就这么误报过 12 处。
"""
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ID = re.compile(r'id="([^"]+)"')
TAG = re.compile(r"<[^>]+>")
HREF = re.compile(r'href="#([^"]+)"')
PARA = re.compile(r"<p\b[^>]*>(.*?)</p>", re.S)

# class 里带 dt 就算定义块（单双引号、多个 class 都认）
DEF_DEFAULT = r"""<b[^>]*class=["'][^"']*\bdt\b[^"']*["'][^>]*>\s*定义\s*(\d+-\d+)"""
FIG_DEFAULT = r"<h3[^>]*>\s*图\s*(\d+-\d+[a-z]?)"

MIN_PARA = 80          # 只对 ≥80 字符的段落做指纹：短段落（「（1）」之类）天然重复，会误报

# 有意改动的声明（HTML 注释，不影响渲染）
MARK = re.compile(r"<!--\s*verify:\s*(rewrite|expand)\s+([\w.\-]+)\s*-->")
# 打印样式里藏内容
PRINT_BLOCK = re.compile(r"@media\s+print\s*\{(.*?)\}", re.S)
PRINT_HIDE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|"
                        r"font-size\s*:\s*0|opacity\s*:\s*0")
# data/CHANGES.md 里的改名声明：s3 → s23 / `s3` -> `s23`
RENAME = re.compile(r"`?([A-Za-z][\w.\-]{0,24})`?\s*(?:→|->|=>)\s*`?([A-Za-z][\w.\-]{0,24})`?")


def head_re(levels):
    """按 --levels 生成标题正则（默认 23 = 只认 h2/h3）。"""
    return re.compile(r"<h([%s])([^>]*)>(.*?)</h\1>" % levels, re.S)


def plain(s):
    return (TAG.sub("", s).replace("&lt;", "<").replace("&gt;", ">")
            .replace("&amp;", "&").strip())


def norm(s):
    """段落指纹用的归一化：去标签、去所有空白（排版换行不该影响指纹）。"""
    return re.sub(r"\s+", "", plain(s))


def split_sections(text, levels="23"):
    """按标题切段 → [{'key','title','chars','start','end'}]（保序，允许 key 重复）。"""
    marks = []
    for m in head_re(levels).finditer(text):
        attrs, inner = m.group(2), plain(m.group(3))
        mid = ID.search(attrs)
        key = mid.group(1) if mid else "T:" + inner[:16]
        marks.append((m.start(), key, inner))
    out = []
    for i, (pos, key, inner) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        out.append({"key": key, "title": inner, "chars": end - pos,
                    "start": pos, "end": end})
    return out


def para_fingerprints(text, secs):
    """段落指纹：[{'s': 内容哈希, 'p': 前24字（报错时给人看）, 'n': 长度, 'k': 所属节}]。

    为什么用整体哈希而不是前 40 字：截断一段文字时开头往往原样保留，
    用前缀当签名会认不出"这一段被砍掉了后半"（2026-11-13 十三例测试就这么漏过一例）。
    """
    bounds = [(s["start"], s["end"], s["key"]) for s in secs]

    def which(pos):
        for a, b, k in bounds:
            if a <= pos < b:
                return k
        return ""

    out = []
    for m in PARA.finditer(text):
        t = norm(m.group(1))
        if len(t) < MIN_PARA:
            continue
        out.append({"s": hashlib.md5(t.encode("utf-8")).hexdigest()[:10],
                    "p": t[:24], "n": len(t), "k": which(m.start())})
    return out


def snapshot(text, def_pat, fig_pat, levels="23"):
    secs = split_sections(text, levels)
    figs = re.findall(fig_pat, text)
    defs = re.findall(def_pat, text)
    ids = ID.findall(text)
    paras = para_fingerprints(text, secs)
    return {
        "version": 2,
        "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "md5_12": hashlib.md5(text.encode("utf-8")).hexdigest()[:12],
        "chars": len(text),
        "sections": {s["key"]: {"title": s["title"], "chars": s["chars"]} for s in secs},
        "order": [s["key"] for s in secs],
        "titles": [s["title"] for s in secs],
        "dup_sec": [k for k, v in Counter(s["key"] for s in secs).items() if v > 1],
        "figs": len(re.findall(r"<figure", text)),
        "svgs": len(re.findall(r"<svg", text)),
        "math": len(re.findall(r"\\\[", text)),
        "defs": sorted(set(defs)),
        "figcaps": sorted(set(figs)),
        "dup_def": [k for k, v in Counter(defs).items() if v > 1],
        "dup_fig": [k for k, v in Counter(figs).items() if v > 1],
        "paras": paras,
        "samples": section_samples(text, secs),
        "n_ids": len(set(ids)),
    }


def parse_marks(text):
    """读 `<!-- verify:rewrite s23 -->` / `<!-- verify:expand s23 -->` 声明。"""
    marks = {"rewrite": set(), "expand": set()}
    for kind, key in MARK.findall(text):
        marks[kind].add(key)
    return marks


def parse_renames(path):
    """从 CHANGES.md 读 `旧 → 新` 的节 id 改名声明。读不到就返回空。"""
    if not path or not os.path.exists(path):
        return {}
    try:
        txt = io.open(path, encoding="utf-8").read()
    except Exception:  # noqa: BLE001
        return {}
    return {a: b for a, b in RENAME.findall(txt)}


def default_changes_path(html_path):
    d = os.path.dirname(os.path.abspath(html_path))
    for cand in (os.path.join(d, "data", "CHANGES.md"),
                 os.path.join(os.path.dirname(d), "data", "CHANGES.md")):
        if os.path.exists(cand):
            return cand
    return None


def section_samples(text, secs, min_len=40, win=24):
    """每节取一个「一定该被打印出来」的正文样本：第一个不含公式、≥40 字符的段落。

    为什么不用节标题：标题可能被 CSS 装饰（背景条、内联标签），而且 pdftotext 是按
    **视觉位置**拼文本块的——`<h3>13-11<span>光程 · 相位差</span></h3>` 紧跟
    `<p><b>题目</b>…` 时，提取出来会是「13-13题目薄膜等倾·…」，HTML 顺序被重排。
    2026-11-13 用标题做判据时，真实讲义上就这么误报了 7 节。

    含公式的段落也要跳过：公式渲成 SVG 后取不到文字，样本里会留一个空洞。
    """
    out = []
    for s in secs:
        body = text[s["start"]:s["end"]]
        for m in PARA.finditer(body):
            raw = m.group(1)
            if "\\(" in raw or "\\[" in raw:
                continue
            n = norm(raw)
            if len(n) >= min_len:
                out.append((s["key"], n[:win]))
                break
    return out


def _sample_hit(sample, flat, win=12):
    """样本是否出现在 PDF 文本里：按 12 字滑窗找，任一命中即算在。

    不做整段子串匹配，因为块与块之间会被 pdftotext 重排（见 section_samples 的说明）；
    块**内部**的文字顺序是保住的，所以短窗口一定能在。
    """
    if len(sample) <= win:
        return sample in flat
    return any(sample[i:i + win] in flat for i in range(0, len(sample) - win + 1, 4))


def check_anchors(text):
    """href="#xxx" 指向的 id 是否都在文中。改节 id 后忘改目录，靠这条抓。"""
    ids = set(ID.findall(text))
    bad = []
    for h in sorted(set(HREF.findall(text))):
        if h not in ids:
            bad.append(h)
    return bad


def check_print_hide(text):
    """`@media print` 里藏内容：HTML 字数不变，PDF 里那一块没了。"""
    hits = []
    for m in PRINT_BLOCK.finditer(text):
        blk = m.group(1)
        if PRINT_HIDE.search(blk):
            sel = re.search(r"([#.][\w-]+|\b[a-z]+)\s*\{", blk)
            hits.append((sel.group(1) if sel else "?", re.sub(r"\s+", " ", blk)[:60]))
    return hits


def compare(old, cur, min_section=0.40, min_total=0.85, min_count=0.80,
            marks=None, renames=None):
    bad, warn, seen = [], [], []
    old_sec = old.get("sections", {})
    cur_sec = cur["sections"]
    marks = marks or {"rewrite": set(), "expand": set()}
    renames = renames or {}

    # 1 节消失（先看有没有改名声明）
    gone = [k for k in old_sec if k not in cur_sec]
    renamed, really_gone = {}, []
    for k in gone:
        tgt = renames.get(k)
        if tgt and tgt in cur_sec:
            renamed[k] = tgt
        else:
            really_gone.append(k)
    if renamed:
        warn.append("已声明的改名：%s" % "、".join("%s→%s" % kv for kv in renamed.items()))
    if really_gone:
        detail = ["%s（%s）" % (k, old_sec[k]["title"][:18]) for k in really_gone[:8]]
        more = "…共 %d 节" % len(really_gone) if len(really_gone) > 8 else ""
        bad.append("节消失（内容被整段删掉？）：%s%s" % ("、".join(detail), more))

    # 2 节 id 重复
    if cur["dup_sec"]:
        bad.append("节 id 重复（整节被复制了一份？）：%s" % cur["dup_sec"])

    # 3 节标题重复（整节复制、但把 id 改了）
    tcnt = Counter(cur.get("titles") or [])
    dup_t = [(t, c) for t, c in tcnt.items() if c > 1 and len(t) >= 4]
    if dup_t:
        bad.append("节标题重复（整节复制后只改了 id？）：%s"
                   % "；".join("「%s」×%d" % (t[:20], c) for t, c in dup_t[:4]))

    # 4 节顺序改变
    if old.get("order"):
        common_old = [k for k in old["order"] if k in cur_sec]
        common_cur = [k for k in cur["order"] if k in old_sec]
        if common_old != common_cur:
            first = next((i for i, (a, b) in enumerate(zip(common_old, common_cur)) if a != b), 0)
            bad.append("节顺序改变（第 %d 个起不同：基线「%s」→ 现在「%s」）"
                       % (first + 1, common_old[first], common_cur[first]))

    # 5 单节缩水 / 6 单节暴涨
    #   缩水只查基线 ≥400 字符的节（太小的节改一句话就是 50%，会误报一片）；
    #   暴涨不设这个下限——小节被反复追加补充段，同样是事故。
    for k, o in old_sec.items():
        n = cur_sec.get(k)
        if not n or k in marks["rewrite"]:
            continue
        if o["chars"] >= 400 and n["chars"] < o["chars"] * min_section:
            bad.append("节「%s」从 %d 字符降到 %d 字符（-%.0f%%，疑似误删）"
                       % (k, o["chars"], n["chars"], 100 * (1 - n["chars"] / o["chars"])))
        elif n["chars"] > o["chars"] * 1.6 and n["chars"] - o["chars"] > max(200, o["chars"] * 0.5):
            if k not in marks["expand"]:
                bad.append("节「%s」从 %d 字符涨到 %d 字符（+%d，1.6 倍以上）——"
                           "疑似补充段被反复插入；若确实是正常扩充，"
                           "在该节放 <!-- verify:expand %s -->"
                           % (k, o["chars"], n["chars"], n["chars"] - o["chars"], k))

    # 7 节内正文净丢失 / 8 段落重复
    old_paras = old.get("paras")
    if old_paras is not None:
        old_map = {p["s"]: p for p in old_paras}
        cur_map = {p["s"]: p for p in cur["paras"]}
        gone_chars, new_chars = defaultdict(int), defaultdict(int)
        base_chars = defaultdict(int)
        gone_cnt = Counter()
        for p in old_paras:
            base_chars[p["k"]] += p["n"]
            if p["s"] not in cur_map:
                gone_chars[p["k"]] += p["n"]
                gone_cnt[p["k"]] += 1
        for p in cur["paras"]:
            if p["s"] not in old_map:
                new_chars[p["k"]] += p["n"]
        for k, oc in old_sec.items():
            if k not in cur_sec or gone_cnt[k] == 0 or k in marks["rewrite"]:
                continue
            ratio = gone_chars[k] / max(1, base_chars[k])
            # 判据是「该节有多少比例的段落被换掉」，不是净额：
            # 净额（消失−补回）会被"删掉 60%、再补回 48%"绕过——补回的那段也算新内容，
            # 净额只剩 12%。所以只看消失比例：换掉三分之一以上就得说明是重写。
            if ratio >= 0.35:
                bad.append("节「%s」里有 %d%% 的段落被换掉了（消失 %d 字、补回 %d 字），"
                           "全节 %d→%d 字符 —— 标题还在，正文被删改了一大截"
                           % (k, round(100 * ratio), gone_chars[k], new_chars[k],
                              oc["chars"], cur_sec[k]["chars"]))
        # 8 段落重复（同一段比基线多出现）
        cur_sig = Counter(p["s"] for p in cur["paras"])
        dups = []
        for s, c in cur_sig.items():
            base_n = sum(1 for p in old_paras if p["s"] == s)
            if c > max(base_n, 1):
                preview = next(p["p"] for p in cur["paras"] if p["s"] == s)
                dups.append("「%s…」%d→%d 次" % (preview, base_n, c))
        if dups:
            bad.append("段落重复（脚本重跑残段？）。%d 段比基线多出现：%s"
                       % (len(dups), "；".join(dups[:4])))
    else:
        warn.append("基线是旧格式（没有段落指纹），跑一次 --record 才能查「标题还在、正文被删」")

    # 9 编号重复
    if cur["dup_def"]:
        bad.append("同一「定义」出现两次（脚本重跑残段？）：%s" % cur["dup_def"])
    if cur["dup_fig"]:
        bad.append("同一图号出现两次（撞号）：%s" % cur["dup_fig"])

    # 10 编号逐个存续（数量够但换了一个也要报）
    miss_def = [d for d in old.get("defs", []) if d not in set(cur["defs"])]
    if miss_def:
        bad.append("定义号消失（不只是数量，是这一号没了）：%s" % miss_def[:10])
    miss_fig = [f for f in old.get("figcaps", []) if f not in set(cur["figcaps"])]
    if miss_fig:
        bad.append("图号消失（不只是数量，是这一号没了）：%s" % miss_fig[:10])

    # 11 全篇缩水
    if old["chars"] and cur["chars"] < old["chars"] * min_total:
        bad.append("全篇从 %d 降到 %d 字符（-%.0f%%）"
                   % (old["chars"], cur["chars"],
                      100 * (1 - cur["chars"] / old["chars"])))

    # 12 数量骤减
    for key, label in (("figs", "图"), ("svgs", "SVG"), ("math", "公式块")):
        if old.get(key) and cur[key] < old[key] * min_count:
            bad.append("%s 从 %d 个降到 %d 个" % (label, old[key], cur[key]))

    for kind, keys in marks.items():
        for k in sorted(keys):
            if k not in cur_sec:
                bad.append("声明了 verify:%s %s，但文中没有这个节 id（拼错了？）" % (kind, k))
    if marks["rewrite"]:
        seen.append("本次声明的整节重写：%s" % "、".join(sorted(marks["rewrite"])))
    if marks["expand"]:
        seen.append("本次声明的正常扩充：%s" % "、".join(sorted(marks["expand"])))

    new = [k for k in cur_sec if k not in old_sec]
    if new:
        warn.append("新增 %d 节：%s" % (len(new), new[:10]))
    if old["chars"] and cur["chars"] > old["chars"] * 1.5:
        warn.append("全篇涨到基线的 %.1f 倍——确认是新增内容，不是重复插入"
                    % (cur["chars"] / old["chars"]))
    return bad, warn, seen


def check_pdf(pdf_path, text, samples=None):
    """PDF 层：打得开吗、几页、能提取多少字、**每一节的正文是否真的印出来了**。"""
    bad = []
    if not os.path.exists(pdf_path):
        return ["PDF 不存在：%s" % pdf_path], 0, 0
    try:
        info = subprocess.run(["pdfinfo", pdf_path], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=60)
        m = re.search(r"^Pages:\s+(\d+)", info.stdout, re.M)
        pages = int(m.group(1)) if m else 0
        txt = subprocess.run(["pdftotext", "-q", pdf_path, "-"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=180)
        got = len(re.sub(r"\s+", "", txt.stdout or ""))
    except FileNotFoundError:
        return [], 0, 0          # 没装 poppler：跳过，不算错
    except Exception as e:  # noqa: BLE001
        return ["PDF 检查失败：%s" % e], 0, 0
    if pages <= 0:
        bad.append("PDF 0 页（打印没出内容）")
    expect = len(re.sub(r"\s+", "", plain(text)))
    if expect and got < expect * 0.60:
        bad.append("PDF 里能提取的文字只有 %d 字，HTML 正文有 %d 字（%.0f%%）——"
                   "大概率打印时内容没排出来" % (got, expect, 100 * got / expect))
    # 逐节核对：整节被 @media print 藏掉、或分页丢了，总字数可能照样够，但这一节没了。
    if samples and txt.stdout:
        flat = re.sub(r"\s+", "", txt.stdout)
        miss = [(k, s) for k, s in samples if not _sample_hit(s, flat)]
        if miss:
            bad.append("PDF 里找不到这 %d 节的正文（整节没印出来？）：%s"
                       % (len(miss), ["%s「%s…」" % (k, s[:10]) for k, s in miss[:5]]))
    print("PDF：%d 页 / 可提取 %d 字" % (pages, got))
    return bad, pages, got


def main():
    ap = argparse.ArgumentParser(description="讲义完整性回归检查")
    ap.add_argument("--html", nargs="+", default=["build/lecture.html"],
                    help="讲义 HTML；给多个则按顺序拼接（分段写的讲义）")
    ap.add_argument("--pdf", default=None,
                    help="顺带检查成品 PDF（页数 / 可提取文字量 / 逐节标题）")
    ap.add_argument("--manifest", default=None,
                    help="基线文件，默认在第一个 HTML 同目录下 manifest-accepted.json")
    ap.add_argument("--changes", default=None,
                    help="修改清单（读 `旧 → 新` 的改名声明）；默认自动找 data/CHANGES.md")
    ap.add_argument("--record", action="store_true", help="把当前状态记为已验收基线")
    ap.add_argument("--force", action="store_true",
                    help="即使当前已有重复定义/图号/节 id，也照样记录基线")
    ap.add_argument("--def-pattern", default=DEF_DEFAULT)
    ap.add_argument("--fig-pattern", default=FIG_DEFAULT)
    ap.add_argument("--min-section", type=float, default=0.40)
    ap.add_argument("--min-total", type=float, default=0.85)
    ap.add_argument("--min-count", type=float, default=0.80)
    ap.add_argument("--levels", default="23",
                    help="把哪几级标题当作节边界，默认 23（h2/h3）。别把 h4 加进来")
    a = ap.parse_args()

    missing = [p for p in a.html if not os.path.exists(p)]
    if missing:
        sys.exit("找不到：%s" % "、".join(missing))
    text = "".join(io.open(p, encoding="utf-8").read() for p in a.html)

    base = a.manifest or os.path.join(os.path.dirname(os.path.abspath(a.html[0])),
                                      "manifest-accepted.json")
    cur = snapshot(text, a.def_pattern, a.fig_pattern, a.levels)
    anchor_bad = check_anchors(text)
    hide = check_print_hide(text)

    if a.record:
        blockers = list(cur["dup_def"]) + list(cur["dup_fig"]) + list(cur["dup_sec"])
        if blockers and not a.force:
            print("❌ 当前状态本身就有重复，拒绝记为基线：")
            if cur["dup_def"]:
                print("   定义重复：%s" % cur["dup_def"])
            if cur["dup_fig"]:
                print("   图号重复：%s" % cur["dup_fig"])
            if cur["dup_sec"]:
                print("   节 id 重复：%s" % cur["dup_sec"])
            print("   先修掉，或者加 --force 强行记录（不建议）。")
            return 1
        if anchor_bad:
            print("⚠️ 有 %d 个锚点指向不存在的 id：%s" % (len(anchor_bad), anchor_bad[:10]))
            print("   （照样记录，但发布前建议修掉）")
        if hide:
            print("⚠️ 打印样式里藏了内容：%s（照样记录，但交付的 PDF 会缺一块）" % hide[:3])
        io.open(base, "w", encoding="utf-8").write(
            json.dumps(cur, ensure_ascii=False, indent=1))
        print("已记录基线 → %s" % base)
        print("  %d 字符 / %d 节 / %d 段 / %d 图 / %d SVG / %d 公式块"
              % (cur["chars"], len(cur["sections"]), len(cur["paras"]),
                 cur["figs"], cur["svgs"], cur["math"]))
        print("  ⚠️ 只有「内容确认正确、且已交付」的版本才能当基线。")
        return 0

    if not os.path.exists(base):
        print("还没有基线。先跑一次 --record（确认当前内容是对的）：")
        print("  python scripts/verify_html.py --html %s --record" % " ".join(a.html))
        return 1
    old = json.loads(io.open(base, encoding="utf-8").read())
    marks = parse_marks(text)
    changes = a.changes if a.changes is not None else default_changes_path(a.html[0])
    renames = parse_renames(changes)
    bad, warn, seen = compare(old, cur, a.min_section, a.min_total, a.min_count,
                              marks, renames)
    bad.extend(anchor_bad and ["锚点失效（目录/正文链接指向不存在的 id）：%s" % anchor_bad[:10]] or [])
    if hide:
        bad.append("打印样式里藏了内容（HTML 字数不变，PDF 会缺这一块）：%s" % hide[:3])

    print("现状：%d 字符 / %d 节 / %d 段 / %d 图 / %d SVG / %d 公式块"
          % (cur["chars"], len(cur["sections"]), len(cur["paras"]),
             cur["figs"], cur["svgs"], cur["math"]))
    print("基线：%d 字符 / %d 节 / %d 段 / %d 图 / %d SVG / %d 公式块"
          % (old["chars"], len(old.get("sections", {})), len(old.get("paras", [])),
             old.get("figs", 0), old.get("svgs", 0), old.get("math", 0)))
    if old.get("recorded_at"):
        print("       （记录于 %s，指纹 %s）" % (old["recorded_at"], old.get("md5_12", "?")))

    if a.pdf:
        pb, _, _ = check_pdf(a.pdf, text, cur.get("samples"))
        bad.extend(pb)

    for s in seen:
        print("  · " + s)
    for w in warn:
        print("  · " + w)

    if bad:
        print("\n❌ 拒绝发布，发现 %d 处问题：" % len(bad))
        for b in bad:
            print("  - " + b)
        print("\n确认这些是**有意**改动后：整节重写放 <!-- verify:rewrite 节id -->，")
        print("正常扩充放 <!-- verify:expand 节id -->，改 id 在 data/CHANGES.md 记 `旧 → 新`，")
        print("然后才跑 --record 更新基线。")
        print("MD5 %s" % cur["md5_12"])
        return 1
    print("\n✅ 通过（无丢失、无重复插入、无编号错乱、无锚点失效）")
    print("MD5 %s" % cur["md5_12"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
