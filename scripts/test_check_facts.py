#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_check_facts.py —— check_facts.py 的回归测试。

全部用例都来自真实事故（2026-11-27 作业四讲义把 74LS162 的清零方式写错），
不是为了凑数编的：如果哪天改了匹配逻辑，这些句子必须还能被抓到。

    python scripts/test_check_facts.py      # 期望输出「✅ 八例全部通过」
"""
from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import check_facts as CF  # noqa: E402

HTML_HEAD = '<!doctype html><html><head><title>t</title></head><body>'
HTML_TAIL = '</body></html>'


def make(html: str) -> str:
    fd, path = tempfile.mkstemp(suffix='.html')
    os.close(fd)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(HTML_HEAD + html + HTML_TAIL)
    return path


def run(html: str, axes=None):
    """返回 (退出码, 输出文本)。"""
    path = make(html)
    try:
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = CF.check([path], axes or CF.DEFAULT_AXES)
        return code, buf.getvalue()
    finally:
        os.unlink(path)


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


# 1. 真实事故：2.5 表斜杠归类写「160/161/162 异步」，2.6 表写「162 同步」
@case
def t01_real_incident():
    html = """
    <section id="s-2-5"><h3>2.5 清零端同步还是异步</h3>
    <table><tr><td>74LS160 / 161 / 162</td><td>异步清零</td>
    <td>CLRN 一变成 0，立刻清零，不等 CP</td></tr></table></section>
    <section id="s-2-6"><h3>2.6 四颗计数器芯片逐脚讲</h3>
    <table><tr><td>74LS162</td><td>十进制（模 10）</td><td>8421BCD 码</td>
    <td>同步</td><td>同步</td></tr></table></section>
    """
    code, out = run(html)
    assert code == 1, '应该报冲突，实际退出码 %d' % code
    assert '74LS162' in out, out
    assert '同步' in out and '异步' in out, out
    return '2.5「160/161/162 异步」vs 2.6「162 同步」→ 报冲突'


# 2. 同上，改成正确写法后必须通过
@case
def t02_after_fix():
    html = """
    <section id="s-2-5"><h3>2.5 清零端同步还是异步</h3>
    <table><tr><td>74LS160 / 161</td><td>异步清零</td></tr>
    <tr><td>74LS162 / 163</td><td>同步清零</td></tr></table></section>
    <section id="s-2-6"><h3>2.6 四颗计数器芯片逐脚讲</h3>
    <table><tr><td>74LS162</td><td>同步</td></tr>
    <tr><td>74LS163</td><td>同步</td></tr></table></section>
    """
    code, out = run(html)
    assert code == 0, '修好后不该再报，实际：\n' + out
    return '改为「160/161 异步」「162/163 同步」→ 不报'


# 3. 同一句里两词都出现 = 合法对照（最常见的一行写法）
@case
def t03_same_sentence_contrast():
    html = """
    <h3>2.6</h3>
    <p>74LS160/161 是异步清零，74LS162/163 是同步清零，这是它们唯一的区别。</p>
    """
    code, out = run(html)
    assert code == 0, '同句对照是合法的，不该报：\n' + out
    return '同句里「异步…同步…」对照 → 不报'


# 4. 页码不能当成型号：p.162 / 第 162 页 / 页 162
@case
def t04_page_number_noise():
    # 全文只出现 160 与 162 两个完整型号；句里的 "p.162" 不能被当成 74LS162，
    # 否则「74LS160 异步」会被误判成「162 也异步」，与第二句的「162 同步」冲突。
    html = """
    <h3>2.5</h3>
    <p>74LS160 采用异步清零，引脚与时序详见 课件13 p.162。</p>
    <h3>2.6</h3>
    <p>74LS162 采用同步清零，等下一个 CP 才动。</p>
    """
    code, out = run(html)
    assert code == 0, 'p.162 是页码，不该被当成型号：\n' + out
    return 'p.162 / 第 162 页 不被当成型号 → 不误报'


# 5. 图里的 <text> 不算正文事实（矢量图上的字常是简写、会制造假冲突）
@case
def t05_svg_ignored():
    html = """
    <h3>2.6</h3>
    <figure><svg width="100" height="50">
      <text x="1" y="9">74LS162 异步清零</text>
    </svg></figure>
    <p>74LS162 采用同步清零。</p>
    """
    code, out = run(html)
    assert code == 0, 'SVG 里的文字不该参与判断：\n' + out
    return '<svg> 内的字被整块丢弃 → 不报'


# 6. 不同实体各执一词不算冲突（160 异步、162 同步各自正确）
@case
def t06_different_entities():
    html = """
    <h3>2.5</h3>
    <p>74LS160 采用异步清零，这是它的特点。</p>
    <h3>2.6</h3>
    <p>74LS162 采用同步清零，等下一个 CP 才动。</p>
    """
    code, out = run(html)
    assert code == 0, '不同实体不该判成冲突：\n' + out
    return '160 异步 / 162 同步分属不同实体 → 不报'


# 7. 只提裸编号（162）也要能归到 74LS162 上
@case
def t07_short_number_expands():
    html = """
    <h3>2.6</h3><p>74LS162 十进制，输出 8421BCD 码。</p>
    <h3>2.5</h3><p>160/161/162 三个型号的清零方式都是异步。</p>
    <h3>9.3</h3><p>162/163 用同步清零（课件13 p.3 总表）。</p>
    """
    code, out = run(html)
    assert code == 1, '裸编号 162 应被扩展成 74LS162 并报冲突：\n' + out
    return '裸编号 162 归到 74LS162 → 报冲突'


# 8. 自定义属性轴（换科目：化学的氧化/还原）
@case
def t08_custom_axes():
    html = """
    <h3>A</h3><p>Fe2+ 在该反应中被氧化成 Fe3+。</p>
    <h3>B</h3><p>Fe2+ 在该反应中被还原成 Fe。</p>
    """
    axes = CF.normalize_axes([['氧化', '还原']])
    code, out = run(html, axes)
    assert code == 1, '自定义轴也应生效：\n' + out
    assert 'Fe2+' in out, out
    return '--axes 自定义「氧化/还原」→ 报冲突'


def main() -> int:
    ok = 0
    for fn in CASES:
        name = fn.__name__
        try:
            desc = fn()
            print('  \u2713 %-28s %s' % (name, desc))
            ok += 1
        except AssertionError as exc:
            print('  \u2717 %-28s %s' % (name, exc))
    total = len(CASES)
    if ok == total:
        print('\n\u2705 \u516b\u4f8b\u5168\u90e8\u901a\u8fc7\uff08%d/%d\uff09' % (ok, total))
        return 0
    print('\n\u274c %d \u4f8b\u4e2d %d \u4f8b\u5931\u8d25' % (total, total - ok))
    return 1


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:  # noqa: BLE001
        pass
    sys.exit(main())