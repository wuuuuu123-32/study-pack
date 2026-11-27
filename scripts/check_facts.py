#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_facts.py —— 讲义「同一实体、同一属性轴」的事实一致性检查。

为什么需要它
------------
2026-11-27 的真实事故：作业四讲义 2.5 节的表把 74LS162 写成「160/161/162 异步清零」，
同一份文档 2.6 节的表写「74LS162 同步清零」。四处错误**全部**出现在
「把几颗芯片并成一个格子」（斜杠归类）的写法里，而三张「一行一颗」的逐项表全对。
根因不是记错电气特性 —— 是换输出格式时列表被重新生成了一遍，没有从已写对的逐项表推出来。

这类错误靠「再读一遍」抓不住：句子通顺、术语正确、错误元素被正确元素包着。
只能靠文本比对，把「同一实体在不同分句里被说成相反属性」的句子并排列出来。

判据
----
先把正文切成**分句**（按「，、；：——」切；表格一行算一个分句，单元格之间不断），
再对每条属性轴（同步/异步、高有效/低有效……）检查同一个实体的出现：

- 同一个分句里两个词都出现 → 合法对照（「160/161 异步，162/163 同步」），跳过；
- 两个词分别出现在**不同分句** → 冲突，退出码 1，人工裁决；
- 否定语境（「290 没有同步清零端」）跳过；
- 轴声明了 `exclude` 词时，分句里出现该词就跳过（「161 的**置数**是同步的」不该算清零方式）。

这两条去噪规则是拿真实讲义调出来的：只做「简单共现」时，38 页讲义报 3 处**全部是假阳性**。

用法
----
    python scripts/check_facts.py <讲义.html> [更多.html ...]
    python scripts/check_facts.py <讲义.html> --axes my-axes.json
    python scripts/check_facts.py <讲义.html> --list       # 只列出实体，不判冲突

`--axes` 的 JSON：`[{"name":"氧化性","pair":["氧化","还原"],"exclude":[]}, ...]`
（也接受旧的两词数组 `[["氧化","还原"]]`）。退出码：0 = 无冲突；1 = 有冲突；2 = 用法错。
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import os
import re
import sys

# ---------------------------------------------------------------- 默认属性轴
# 只放真正互斥的两组词。凡是「在同一句话里经常成对出现」的词（置位/复位、加法/减法）
# 都不进默认表 —— 它们会把大量正常对照句误报成冲突。
DEFAULT_AXES = [
    {"name": "清零方式", "pair": ["同步", "异步"],
     "exclude": ["置数", "装载", "置入", "LOAD"]},
    {"name": "有效电平", "pair": ["高有效", "低有效"], "exclude": []},
    {"name": "有效电平（全称）", "pair": ["高电平有效", "低电平有效"], "exclude": []},
    {"name": "触发边沿", "pair": ["上升沿", "下降沿"], "exclude": []},
    {"name": "输出类型", "pair": ["Mealy", "Moore"], "exclude": []},
    {"name": "逻辑约定", "pair": ["正逻辑", "负逻辑"], "exclude": []},
]

# 完整型号：74LS162 / CC4017 / 74HC153 / AD620AN
RE_FULL = re.compile(
    r'(?<![A-Za-z0-9])'
    r'(\d{2}[A-Z]{2,4}\d{2,4}[A-Z]{0,2}|[A-Z]{2,4}\d{3,5}[A-Z]{0,2})'
    r'(?![A-Za-z0-9])'
)
# 裸编号：只用来扩展已出现过的型号，前不能是 "p." "第" 这类页码标记
RE_SHORT = re.compile(r'(?<![A-Za-z0-9.\u7b2c])(\d{3,4})(?![A-Za-z0-9])')
RE_PAGE_CTX = re.compile(r'(p\.?\s*$|\u7b2c\s*$|\u9875)')
# 元素 / 元件标号：Fe2+、R1、C2 —— 换科目（化学、电路）时靠这条兜底
RE_UNIT = re.compile(r'(?<![A-Za-z0-9])([A-Z][a-z]?\d+(?:[+-])?)(?![A-Za-z0-9])')

# 页码 / 章号这类噪声：单独成句时不参与判断
RE_NOISE = re.compile(r'^\s*(p\.?\s*\d+|\u7b2c\s*\d+\s*\u9875|\d+\s*/\s*\d+)\s*$')
# 分句：只按中文标点切；表格一行靠空格分隔，不能切
RE_CLAUSE = re.compile(r'[\uff0c\u3001\uff1b\uff1a]|\u2014\u2014')
# 否定语境：词前面这几个字出现，说明这句话在否定该属性
RE_NEG = re.compile(r'(\u6ca1\u6709|\u4e0d\u662f|\u5e76\u975e|\u4e0d\u5b58\u5728|\u4e0d\u80fd|\u4e0d\u91c7\u7528|\u672a\u91c7\u7528|\u65e0\u6cd5|\u4e0d\u5177\u5907)\s*$')


def strip_tags(s: str) -> str:
    return re.sub(r'<[^>]+>', '', s)


def html_to_lines(path: str) -> list[str]:
    """把 HTML 变成「一行一句 + @@Hn@@ 标题标记」的纯文本行。"""
    t = open(path, encoding='utf-8', errors='replace').read()
    # 图里的 <text> 是画面上写的字，不属于正文事实，整块丢掉
    t = re.sub(r'<svg\b.*?</svg>', ' ', t, flags=re.S | re.I)
    t = re.sub(r'<(script|style)\b.*?</\1>', ' ', t, flags=re.S | re.I)
    # 标题先打成标记，正文才知道自己在哪一节
    t = re.sub(
        r'<h([1-4])\b[^>]*>(.*?)</h\1>',
        lambda m: '\n@@H%s@@%s\n' % (m.group(1), strip_tags(m.group(2)).strip()),
        t, flags=re.S | re.I,
    )
    # 表格行 = 一句话：单元格之间不能断，否则「型号」与「属性」被拆成两句，
    # 属性词那半句往往只有三四个字，会在下面的短句过滤里被丢掉（2026-11-27 实测）。
    t = re.sub(r'</(td|th)\s*>\s*', '  ', t, flags=re.I)
    t = re.sub(r'</(p|li|tr|div|dd|dt|figcaption|blockquote)\s*>', '\u3002\n', t, flags=re.I)
    t = re.sub(r'<br\s*/?>', '\n', t, flags=re.I)
    t = strip_tags(t)
    t = htmllib.unescape(t)
    t = t.replace('\u3000', ' ')
    return [ln.strip() for ln in t.split('\n')]


def split_sentences(lines: list[str]):
    """产出 (所在小节标题, 句子)。"""
    section = '(\u6587\u9996)'
    for ln in lines:
        m = re.match(r'^@@H([1-4])@@(.*)$', ln)
        if m:
            section = m.group(2).strip() or section
            continue
        if not ln or RE_NOISE.match(ln):
            continue
        for s in re.split(r'[\u3002\uff1b\uff01\uff1f]', ln):
            s = s.strip()
            if len(s) < 6:
                continue
            yield section, s


def clauses(sentence: str) -> list[str]:
    parts = [p.strip() for p in RE_CLAUSE.split(sentence)]
    return [p for p in parts if len(p) >= 4]


def build_short_map(sentences) -> dict[str, str]:
    """从全文出现过的完整型号里，建「裸编号 → 完整型号」的映射（只在唯一时成立）。"""
    fulls: set[str] = set()
    for _, s in sentences:
        fulls.update(RE_FULL.findall(s))
    by_short: dict[str, set[str]] = {}
    for f in fulls:
        m = re.search(r'(\d{3,4})(?!\d)', f)
        if m:
            by_short.setdefault(m.group(1), set()).add(f)
    return {k: next(iter(v)) for k, v in by_short.items() if len(v) == 1}


def entities_in(clause: str, short_map: dict[str, str]) -> set[str]:
    ents = set(RE_FULL.findall(clause)) | set(RE_UNIT.findall(clause))
    for num in RE_SHORT.findall(clause):
        if num in short_map:
            ents.add(short_map[num])
    return ents


def negated(clause: str, word: str) -> bool:
    i = clause.find(word)
    if i < 0:
        return False
    return bool(RE_NEG.search(clause[max(0, i - 9):i]))


def check(paths: list[str], axes: list[dict], list_only: bool = False) -> int:
    hits: dict[tuple[str, str], dict[str, list[tuple[str, str, str]]]] = {}
    ent_total: dict[str, int] = {}

    for path in paths:
        if not os.path.exists(path):
            print('\u274c \u8bfb\u4e0d\u5230\u6587\u4ef6\uff1a%s' % path, file=sys.stderr)
            return 2
        sents = list(split_sentences(html_to_lines(path)))
        short_map = build_short_map(sents)
        base = os.path.basename(path)
        for section, s in sents:
            for cl in clauses(s):
                ents = entities_in(cl, short_map)
                for e in ents:
                    ent_total[e] = ent_total.get(e, 0) + 1
                if list_only or not ents:
                    continue
                for ax in axes:
                    a, b = ax['pair']
                    excl = ax.get('exclude') or []
                    if any(x in cl for x in excl):
                        continue
                    if a in b:  # 长词包含短词时，别重复计数
                        has_a = a in cl.replace(b, '')
                        has_b = b in cl
                    elif b in a:
                        has_b = b in cl.replace(a, '')
                        has_a = a in cl
                    else:
                        has_a, has_b = (a in cl), (b in cl)
                    if has_a == has_b:
                        continue  # 都不含，或同分句对照 → 合法
                    word = a if has_a else b
                    if negated(cl, word):
                        continue
                    for e in ents:
                        key = (e, '%s\uff08%s / %s\uff09' % (ax['name'], a, b))
                        hits.setdefault(key, {}).setdefault(word, []).append((base, section, cl))

    if list_only:
        print('\u5168\u6587\u51fa\u73b0\u8fc7\u7684\u5b9e\u4f53\uff08%d \u4e2a\uff09\uff1a' % len(ent_total))
        for e, n in sorted(ent_total.items(), key=lambda x: (-x[1], x[0])):
            print('  %-12s %d \u5904' % (e, n))
        return 0

    conflicts = {k: v for k, v in hits.items() if len(v) >= 2}
    if not conflicts:
        print('\u2705 \u65e0\u4e8b\u5b9e\u51b2\u7a81\uff1a%d \u4e2a\u5b9e\u4f53 \u00d7 %d \u6761\u5c5e\u6027\u8f74\uff0c'
              '\u672a\u53d1\u73b0\u540c\u4e00\u5b9e\u4f53\u88ab\u8bf4\u6210\u4e92\u65a5\u5c5e\u6027\u3002'
              % (len(ent_total), len(axes)))
        return 0

    print('\u274c \u53d1\u73b0 %d \u5904\u4e8b\u5b9e\u51b2\u7a81\uff08\u540c\u4e00\u5b9e\u4f53\u3001\u540c\u4e00\u5c5e\u6027\u8f74\uff0c'
          '\u4e0d\u540c\u5206\u53e5\u5404\u6267\u4e00\u8bcd\uff09\uff1a\n' % len(conflicts))
    for (ent, axis), by_word in sorted(conflicts.items()):
        print('\u25b6 %s\u3000\u5c5e\u6027\u8f74\u300c%s\u300d' % (ent, axis))
        for word, samples in sorted(by_word.items()):
            print('  \u300c%s\u300d%d \u5904\uff1a' % (word, len(samples)))
            for base, section, s in samples[:4]:
                body = s if len(s) <= 88 else s[:85] + '\u2026'
                print('    [%s \u00b7 %s] %s' % (base, section[:26], body))
            if len(samples) > 4:
                print('    \u2026\u53e6\u6709 %d \u5904' % (len(samples) - 4))
        print('  \u2192 \u4eba\u5de5\u88c1\u51b3\uff1a\u786e\u8ba4\u54ea\u4e00\u4e2a\u5bf9\uff0c\u6539\u6389\u53e6\u4e00\u8fb9\uff1b'
              '\u5e76\u56de\u5230\u9010\u9879\u8868\u6838\u5bf9\u6210\u5458\u5217\u8868\u3002\n')
    return 1


def normalize_axes(raw) -> list[dict]:
    out = []
    for item in raw:
        if isinstance(item, dict):
            pair = list(item.get('pair') or [])
            if len(pair) != 2:
                raise ValueError('\u6bcf\u6761\u8f74\u9700\u8981 pair \u7684\u4e24\u4e2a\u8bcd\uff1a%s' % (item,))
            out.append({'name': item.get('name') or '%s / %s' % tuple(pair),
                        'pair': pair,
                        'exclude': list(item.get('exclude') or [])})
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            out.append({'name': '%s / %s' % tuple(item), 'pair': list(item), 'exclude': []})
        else:
            raise ValueError('\u8f74\u683c\u5f0f\u9519\uff1a%s' % (item,))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description='\u68c0\u67e5\u8bb2\u4e49\u91cc\u300c\u540c\u4e00\u5b9e\u4f53 \u00d7 \u540c\u4e00\u5c5e\u6027\u8f74\u300d\u662f\u5426\u51fa\u73b0\u4e92\u65a5\u9648\u8ff0\u3002')
    ap.add_argument('html', nargs='+', help='\u8bb2\u4e49 HTML\uff08\u53ef\u4ee5\u591a\u4efd\uff0c\u5408\u5e76\u7edf\u8ba1\uff09')
    ap.add_argument('--axes', help='\u81ea\u5b9a\u4e49\u5c5e\u6027\u8f74\u7684 JSON \u6587\u4ef6')
    ap.add_argument('--list', action='store_true', dest='list_only',
                    help='\u53ea\u5217\u51fa\u5168\u6587\u51fa\u73b0\u7684\u5b9e\u4f53\u4e0e\u6b21\u6570\uff0c\u4e0d\u5224\u51b2\u7a81')
    args = ap.parse_args(argv)

    axes = DEFAULT_AXES
    if args.axes:
        try:
            axes = normalize_axes(json.load(open(args.axes, encoding='utf-8')))
        except Exception as exc:  # noqa: BLE001
            print('\u274c --axes \u89e3\u6790\u5931\u8d25\uff1a%s' % exc, file=sys.stderr)
            return 2
    return check(args.html, axes, args.list_only)


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:  # noqa: BLE001
        pass
    sys.exit(main())