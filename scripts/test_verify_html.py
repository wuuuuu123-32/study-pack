# -*- coding: utf-8 -*-
"""verify_html.py 的回归测试 —— 它自己也要被证明"真的会拦"。

为什么测：一个"永远返回 0"的检查脚本看起来和正常的一模一样。
只有**故意制造它该拦的事故**、看它是否真的非零退出，才算证明过。

跑法：
    python scripts/test_verify_html.py

二十例（前七例是"整段消失/整篇缩水"这一层，之后是针对独立评审指出的漏检面，
最后三例验"有意改动怎么放行"——放行必须留声明，不是悄悄跳过）：
  1  记录基线成功
  2  内容不动 → 通过
  3  删掉一整节（连标题）→ 拦
  4  **保留标题、只删该节正文**（字符数只降到约 45%，不触发 40% 缩水）→ 拦
  5  重复插入一段（定义号重复）→ 拦
  6  **重复插入一段没有任何编号的正文** → 拦（段落指纹）
  7  **整节复制一份、连 id 都不改** → 拦（节 id 重复）
  8  **两节互换位置** → 拦（节顺序改变）
  9  **图号被改掉、图的数量不变** → 拦（图号逐个存续）
  10 **href 指向不存在的 id** → 拦（锚点失效）
  11 全篇截断到 60% → 拦
  12 当前状态本身有重复时，拒绝记基线
  13 --force 可以强记
  —— 下面是独立评审打回后补的（每条都是一个"当时的实现会放过去"的构造）——
  14 **删掉 60%、再补回一段**（净额刚好低于旧阈值 120，但消失比例 60%）→ 拦
  15 **反复追加"改写过的"补充段**（指纹每次都变，段落重复抓不到）→ 拦（单节暴涨）
  16 **整节复制、把 id 改了**（dup_sec 抓不到）→ 拦（节标题重复）
  17 **`@media print` 里 display:none**（HTML 字数不变、PDF 缺一块）→ 拦
  18 **改节 id 并在 CHANGES.md 记 `旧 → 新`** → 放行，且输出"已声明的改名"
  19 **整节重写 + `<!-- verify:rewrite 节id -->`** → 放行，且输出"本次声明的整节重写"
  20 通过时最后一行必须打 `MD5 xxxxxxxxxxxx`（promote.py 靠它比对）
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "verify_html.py")

# 每节的填充文本都不一样：段落指纹靠"这段文字在基线里有没有"来判，
# 所有节共用同一段填充会让指纹互相掩护，测不出问题。
def filler(tag):
    return ("这是第%s节的正文，用来撑字符数并让每一节的段落指纹各不相同。" % tag) * 8


BASE_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<h2 id="p0">第 0 章 打底</h2>
<p>这一章讲基础的东西，第一个段落要够长。</p>
<b class="dt">定义 0-1</b>
<p>{f0}</p>
<h3 id="s01">0.1 光束</h3>
<p>{f1}</p>
<figure><svg width="10" height="10"></svg></figure>
<h3>图 0-1　一张图</h3>
<h3 id="s02">0.2 成像</h3>
<p>{f2}</p>
<b class="dt">定义 0-2</b>
<p>{f2b}</p>
<h3 id="s03">0.3 符号</h3>
<p>\\[ a + b = c \\]</p>
<p>{f3}</p>
<p><a href="#s03">回到 0.3</a></p>
</body></html>
"""


def build():
    return BASE_HTML.format(f0=filler("0"), f1=filler("1"), f2=filler("2"),
                            f2b=filler("2b"), f3=filler("3"))


def write(path, text):
    io.open(path, "w", encoding="utf-8").write(text)


def run(args):
    r = subprocess.run([sys.executable, SCRIPT] + args,
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def block(text, start_id, end_id=None):
    """取出从 start_id 这一节开头到 end_id 之前的整块文本。"""
    i = text.index('id="%s"' % start_id)
    i = text.rindex("<h", 0, i)
    j = len(text) if end_id is None else text.rindex("<h", 0, text.index('id="%s"' % end_id))
    return i, j


def main():
    tmp = tempfile.mkdtemp(prefix="verify-html-test-")
    html = os.path.join(tmp, "lecture.html")
    man = os.path.join(tmp, "manifest-accepted.json")
    good = build()
    f2 = filler("2")
    fails = []

    def check(name, cond, out=""):
        print(("  ✅ " if cond else "  ❌ ") + name)
        if not cond:
            fails.append(name)
            if out:
                print("     " + out.strip().replace("\n", "\n     ")[:700])

    # 1 记录基线
    write(html, good)
    rc, out = run(["--html", html, "--manifest", man, "--record"])
    check("1 记录基线成功", rc == 0 and os.path.exists(man), out)

    # 2 不动 → 通过
    rc, out = run(["--html", html, "--manifest", man])
    check("2 内容不动时通过", rc == 0 and "✅" in out, out)

    # 3 删整节 s02（连标题）
    i, j = block(good, "s02", "s03")
    write(html, good[:i] + good[j:])
    rc, out = run(["--html", html, "--manifest", man])
    check("3 删整节被拦", rc == 1 and "节消失" in out, out)

    # 4 保留标题、只把正文截短到 45%（不触发 40% 缩水，只靠段落指纹抓）
    short = f2[:int(len(f2) * 0.45)]
    write(html, good.replace("<p>%s</p>" % f2, "<p>%s</p>" % short, 1))
    rc, out = run(["--html", html, "--manifest", man])
    check("4 保留标题删正文被拦", rc == 1 and "段落被换掉" in out, out)

    # 5 重复插入（定义 0-2 出现两次）
    dup = good.replace('<h3 id="s03">0.3 符号</h3>',
                       '<b class="dt">定义 0-2</b><p>重复的一段</p><h3 id="s03">0.3 符号</h3>')
    write(html, dup)
    rc, out = run(["--html", html, "--manifest", man])
    check("5 重复插入被拦", rc == 1 and "定义" in out, out)

    # 6 重复插入一段没有任何编号的正文（段落指纹）
    p1 = "<p>%s</p>" % filler("1")
    dup2 = good.replace('<h3 id="s03">0.3 符号</h3>',
                        "%s<h3 id=\"s03\">0.3 符号</h3>" % p1)
    write(html, dup2)
    rc, out = run(["--html", html, "--manifest", man])
    check("6 无编号段落重复被拦", rc == 1 and "段落重复" in out, out)

    # 7 整节复制、连 id 都不改
    i, j = block(good, "s02", "s03")
    sec2 = good[i:j]
    k = good.index('id="s03"')
    k = good.rindex("<h", 0, k)
    write(html, good[:k] + sec2 + good[k:])
    rc, out = run(["--html", html, "--manifest", man])
    check("7 整节复制被拦", rc == 1 and "节 id 重复" in out, out)

    # 8 两节互换位置
    i1, j1 = block(good, "s01", "s02")
    i2, j2 = block(good, "s02", "s03")
    s01, s02 = good[i1:j1], good[i2:j2]
    write(html, good[:i1] + s02 + s01 + good[j2:])
    rc, out = run(["--html", html, "--manifest", man])
    check("8 节顺序改变被拦", rc == 1 and "节顺序改变" in out, out)

    # 9 图号被改掉、图的数量不变
    write(html, good.replace("图 0-1", "图 0-9"))
    rc, out = run(["--html", html, "--manifest", man])
    check("9 图号消失被拦", rc == 1 and "图号消失" in out, out)

    # 10 锚点失效
    write(html, good.replace('href="#s03"', 'href="#s99"'))
    rc, out = run(["--html", html, "--manifest", man])
    check("10 锚点失效被拦", rc == 1 and "锚点失效" in out, out)

    # 11 全篇截断到 60%
    write(html, good[:int(len(good) * 0.6)])
    rc, out = run(["--html", html, "--manifest", man])
    check("11 全篇截断被拦", rc == 1, out)

    # 12 当前状态有重复时拒绝记基线
    write(html, dup)
    rc, out = run(["--html", html, "--manifest", man + ".2", "--record"])
    check("12 有重复时拒绝记基线", rc == 1 and not os.path.exists(man + ".2"), out)

    # 13 --force 强记
    rc, out = run(["--html", html, "--manifest", man + ".3", "--record", "--force"])
    check("13 --force 可强记", rc == 0 and os.path.exists(man + ".3"), out)

    # 14 删掉 60%、再补回一段（净额 116 < 旧阈值 120，但消失比例 60%）
    kept = f2[:int(len(f2) * 0.40)]
    patch = ("补回来的一段新文字，用来把净额压到旧阈值以下。" * 5)
    mixed = "<p>%s</p><p>%s</p>" % (kept, patch)
    write(html, good.replace("<p>%s</p>" % f2, mixed, 1))
    rc, out = run(["--html", html, "--manifest", man])
    check("14 删六成再补回被拦", rc == 1 and "段落被换掉" in out, out)

    # 15 反复追加"改写过的"补充段：每段指纹都新，只有单节暴涨能抓
    grow = ("这是后来又补的一段，措辞每次重跑都不一样，所以段落指纹认不出它是重复。" * 8)
    grown = good.replace('<p><a href="#s03">回到 0.3</a></p>',
                         "<p>%s</p><p><a href=\"#s03\">回到 0.3</a></p>" % grow)
    write(html, grown)
    rc, out = run(["--html", html, "--manifest", man])
    check("15 改写累积被拦（单节暴涨）", rc == 1 and "1.6 倍以上" in out, out)

    # 16 整节复制、把 id 改了（dup_sec 抓不到）
    i, j = block(good, "s02", "s03")
    copied = good[i:j].replace('id="s02"', 'id="s02b"', 1)
    k = good.index('id="s03"')
    k = good.rindex("<h", 0, k)
    write(html, good[:k] + copied + good[k:])
    rc, out = run(["--html", html, "--manifest", man])
    check("16 复制改 id 被拦（标题重复）", rc == 1 and "节标题重复" in out, out)

    # 17 @media print 里藏内容
    hidden = good.replace("</body>",
                          "<style>@media print{#s02{display:none}}</style></body>")
    write(html, hidden)
    rc, out = run(["--html", html, "--manifest", man])
    check("17 打印样式藏内容被拦", rc == 1 and "打印样式里藏" in out, out)

    # 18 改节 id + 在 CHANGES.md 记 `旧 → 新` → 放行
    renamed = (good.replace('id="s03"', 'id="s03x"', 1)
                   .replace('href="#s03"', 'href="#s03x"'))
    chg = os.path.join(tmp, "data")
    os.makedirs(chg, exist_ok=True)
    write(os.path.join(chg, "CHANGES.md"),
          "| 稳定 ID | 说明 |\n|---|---|\n| `s03` → `s03x` | 换了更清楚的 id |\n")
    write(html, renamed)
    rc, out = run(["--html", html, "--manifest", man])
    check("18 已声明的改名放行", rc == 0 and "已声明的改名" in out, out)

    # 19 整节重写（更短）+ 显式声明 → 放行
    shorter = ("重写后的这段话更简练，但仍然交代了成像与符号。" * 10)
    rew = good.replace("<p>%s</p>" % f2, "<p>%s</p>" % shorter, 1)
    rew = rew.replace('<h3 id="s02">0.2 成像</h3>',
                      '<h3 id="s02">0.2 成像</h3>\n<!-- verify:rewrite s02 -->', 1)
    write(html, rew)
    rc, out = run(["--html", html, "--manifest", man])
    check("19 声明的整节重写放行", rc == 0 and "本次声明的整节重写" in out, out)

    # 20 通过时打 MD5 行（promote.py 拿它比对"检查的"和"要发布的"是不是同一份）
    write(html, good)
    rc, out = run(["--html", html, "--manifest", man])
    check("20 输出 MD5 指纹", rc == 0 and "MD5 " in out, out)

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if fails:
        print("❌ %d 例未通过：%s" % (len(fails), fails))
        return 1
    print("✅ 二十例全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
