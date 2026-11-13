# -*- coding: utf-8 -*-
"""promote.py 的失败回滚验收：替换到一半失败时，整批必须回到发布前的状态。

做法：让第二个文件（PDF）在替换时失败——Windows 上把目标设成只读，
os.replace 会抛 PermissionError。此时第一个文件（HTML）已经被换掉了，
promote 必须把它换回去，且退出码非零。
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROMOTE = os.path.join(HERE, "promote.py")

tmp = tempfile.mkdtemp(prefix="promote-rollback-")
out = os.path.join(tmp, "out")
os.makedirs(out)

old_html, old_pdf = "OLD-HTML", "OLD-PDF"
new_html, new_pdf = "NEW-HTML" * 10, "NEW-PDF" * 10
open(os.path.join(out, "x.html"), "w", encoding="utf-8").write(old_html)
open(os.path.join(out, "x.pdf"), "w", encoding="utf-8").write(old_pdf)
src_html = os.path.join(tmp, "src.html")
src_pdf = os.path.join(tmp, "src.pdf")
open(src_html, "w", encoding="utf-8").write(new_html)
open(src_pdf, "w", encoding="utf-8").write(new_pdf)

# 只读：os.replace 覆盖只读文件在 Windows 上会失败
os.chmod(os.path.join(out, "x.pdf"), stat.S_IREAD)

r = subprocess.run([sys.executable, PROMOTE, "--html", src_html, "--pdf", src_pdf,
                    "--out", out, "--name", "x", "--skip-verify"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
print(r.stdout)
print(r.stderr)

os.chmod(os.path.join(out, "x.pdf"), stat.S_IWRITE)
after_html = open(os.path.join(out, "x.html"), encoding="utf-8").read()
after_pdf = open(os.path.join(out, "x.pdf"), encoding="utf-8").read()

ok = (r.returncode == 1
      and after_html == old_html
      and after_pdf == old_pdf)
print("回滚后 x.html =", after_html[:20])
print("回滚后 x.pdf  =", after_pdf[:20])
print("退出码 =", r.returncode)
print("✅ 失败时整批回滚" if ok else "❌ 回滚不完整（留下了混合状态）")

leftovers = [n for n in os.listdir(out) if n.startswith(".staging-")]
print("残留 staging 目录：", leftovers or "无")
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(0 if ok and not leftovers else 1)
