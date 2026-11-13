# -*- coding: utf-8 -*-
"""原子发布：先过完整性检查，再把整批候选文件一次提升成交付物。不通过就一个字节都不动。

为什么要有这一步
----------------
手工 `copy build/x.pdf out/y.pdf` 的问题不是"会失败"，而是**失败时已经写了一半**：
磁盘满、文件被 PDF 阅读器占用、或者根本忘了先跑检查，都可能留下
「HTML 是新的、PDF 是旧的」或「PDF 只写进去一半」的交付物——而 out/ 里的东西是要给人看的，
坏掉的版本会被当成成品。

"每换一个文件都是原子的"≠"整批是原子的"。三个文件逐个替换，中途失败就停在
「新的 HTML + 旧的 PDF」——用户打开看到的正是这种混合体。所以这里做的是：

    检查（含 PDF 层） → 全部复制到 staging → 备份旧版 → 逐个替换 → 失败则整批回滚

用法
----
    python scripts/promote.py --html build/lecture.html --pdf build/lecture-test.pdf \\
        --out out --name 第13章-光学-讲义

    # 顺带发布别的文件（答疑册、修改清单）：源:目标名
    python scripts/promote.py ... --extra out/答疑册.md:第13章-光学-答疑册.md

    # 只是检查、不发布
    python scripts/promote.py ... --dry-run

退出码：0 = 已发布；1 = 检查没过或发布失败（已回滚，out/ 与发布前一致）。

它会做什么
----------
1. 调 `verify_html.py`（带上 `--pdf`，查页数与可提取字数）。**不通过就立刻退出**，
   out/ 一个字节都不碰。
2. 在跑检查**之前**先记下每个候选文件的 md5 —— 检查是一个子进程（可能几十秒），
   复制又是另一个时刻，这中间你完全可能又跑了一次修改脚本；只要 md5 变了就中止，
   避免"检查的是 A、发布的是 B"。
3. 全部复制进 `out/.staging-<时间戳>/` 并 fsync，确认每一个都完整落地。
4. 把即将被覆盖的旧文件复制到 `out/.backup/<时间戳>/`。
5. 逐个 `os.replace(staged → 目标)`；任何一个失败，就把已替换的用备份换回去。
6. 打印每个交付物的字节数与 md5，方便与发信记录对上。
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fsync_copy(src, dst):
    """复制并落盘（不 fsync 的话断电后可能留下长度正确、内容为空洞的文件）。"""
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        shutil.copyfileobj(fi, fo, 1 << 20)
        fo.flush()
        os.fsync(fo.fileno())
    shutil.copystat(src, dst)


def main():
    ap = argparse.ArgumentParser(description="讲义原子发布")
    ap.add_argument("--html", nargs="+", required=True, help="候选 HTML（多段则拼接后检查）")
    ap.add_argument("--pdf", default=None, help="候选 PDF")
    ap.add_argument("--out", default="out", help="交付目录")
    ap.add_argument("--name", required=True, help="交付文件基名（不含后缀）")
    ap.add_argument("--extra", action="append", default=[],
                    help="额外发布的文件，格式 源路径:目标名")
    ap.add_argument("--manifest", default=None, help="传给 verify_html.py 的基线路径")
    ap.add_argument("--skip-verify", action="store_true",
                    help="跳过完整性检查（只在补救历史事故时用，别当常规路径）")
    ap.add_argument("--dry-run", action="store_true", help="只检查，不发布")
    a = ap.parse_args()

    srcs = a.html + ([a.pdf] if a.pdf else []) + [e.split(":", 1)[0] for e in a.extra]
    for p in srcs:
        if not os.path.exists(p):
            sys.exit("找不到候选文件：%s" % p)

    # 先记指纹，再跑检查：检查子进程可能跑几十秒，这期间文件完全可能被再改一次。
    # 指纹记在前面，覆盖的就是「从这一刻到真正复制」的整个窗口。
    fingerprints = {p: md5(p) for p in srcs}

    # ---- 1 检查 ------------------------------------------------------------
    if not a.skip_verify:
        cmd = [sys.executable, os.path.join(HERE, "verify_html.py"), "--html"] + a.html
        if a.pdf:
            cmd += ["--pdf", a.pdf]
        if a.manifest:
            cmd += ["--manifest", a.manifest]
        r = subprocess.run(cmd)
        if r.returncode != 0:
            print("\n❌ 完整性检查未通过 → 不发布，%s 保持原样。" % a.out)
            return 1
    else:
        print("⚠️ 已跳过完整性检查（--skip-verify）")

    jobs = []
    for p in a.html:
        jobs.append((p, os.path.join(a.out, a.name + ".html")))
    if a.pdf:
        jobs.append((a.pdf, os.path.join(a.out, a.name + ".pdf")))
    for e in a.extra:
        src, dstname = e.split(":", 1)
        jobs.append((src, os.path.join(a.out, dstname)))

    stamp = time.strftime("%Y%m%d-%H%M%S")
    if a.dry_run:
        print("\n（dry-run）将发布：")
        for src, dst in jobs:
            print("  %s → %s" % (src, dst))
        print("  md5 已绑定：检查通过后若候选文件再被改动，发布会中止。")
        return 0

    os.makedirs(a.out, exist_ok=True)
    staging = os.path.join(a.out, ".staging-" + stamp)
    backup = os.path.join(a.out, ".backup", stamp)

    # ---- 3 staging：全部先落地，任何一个不完整就整体放弃 --------------------
    staged = []
    try:
        os.makedirs(staging, exist_ok=True)
        for i, (src, dst) in enumerate(jobs):
            if md5(src) != fingerprints[src]:
                raise RuntimeError("候选文件在检查之后又被改动了：%s\n"
                                   "  重新跑一次发布（先过检查），否则发布的不是检查过的那一版。" % src)
            sp = os.path.join(staging, "%d-%s" % (i, os.path.basename(dst)))
            fsync_copy(src, sp)
            if md5(sp) != fingerprints[src]:
                raise RuntimeError("复制到 staging 后校验不一致：%s" % src)
            staged.append((sp, dst))

        # ---- 4 备份 --------------------------------------------------------
        backups = {}
        for sp, dst in staged:
            if os.path.exists(dst):
                os.makedirs(backup, exist_ok=True)
                bp = os.path.join(backup, os.path.basename(dst))
                shutil.copy2(dst, bp)
                backups[dst] = bp
            else:
                backups[dst] = None
    except Exception as e:  # noqa: BLE001
        print("❌ 准备阶段失败，未改动任何交付文件：%s" % e)
        shutil.rmtree(staging, ignore_errors=True)
        return 1

    # ---- 5 逐个替换，失败则整批回滚 ----------------------------------------
    done = []
    try:
        for sp, dst in staged:
            os.replace(sp, dst)
            done.append(dst)
    except Exception as e:  # noqa: BLE001
        print("\n❌ 替换 %s 时失败：%s" % (dst, e))
        print("   正在回滚已替换的 %d 个文件…" % len(done))
        rollback_failed = False
        for d in reversed(done):
            bp = backups.get(d)
            try:
                if bp:
                    tmp = d + ".rollback"
                    shutil.copy2(bp, tmp)
                    os.replace(tmp, d)
                elif os.path.exists(d):
                    os.remove(d)
                print("   已回滚 %s" % d)
            except Exception as e2:  # noqa: BLE001
                rollback_failed = True
                print("   ⚠️ 回滚失败 %s：%s（备份在 %s）" % (d, e2, bp))
        shutil.rmtree(staging, ignore_errors=True)
        if rollback_failed:
            print("   out/ 可能处于混合状态，请人工确认后再发（备份在 %s）。" % backup)
        else:
            print("   out/ 已恢复到发布前的状态。")
        return 1

    shutil.rmtree(staging, ignore_errors=True)
    print()
    for dst in done:
        print("已发布 %s  %d 字节  md5=%s" % (dst, os.path.getsize(dst), md5(dst)))
    if os.path.isdir(backup):
        print("旧版本备份在 %s" % backup)
    print("\n✅ 整批发布完成（%d 个文件，同一版本）" % len(done))
    return 0


if __name__ == "__main__":
    sys.exit(main())
