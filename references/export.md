# 导出与核对：讲义 HTML → PDF

**这一节是硬流程，不是建议。** 讲义以 HTML 为源、PDF 为交付：**没导出 PDF 就是没交付；导出后没亲眼看过就是没核对。**

---

## 0. 先看权限模式 —— 它决定走哪条路

运行时上下文里有一行 `Current DSH file policy: …`：

| 模式 | 走哪条路 |
|---|---|
| `danger-full-access` | **A 路（浏览器打印）** —— 首选。8 秒出片，版式与 HTML 逐像素一致 |
| `workspace-write` / `read-only` | 只能走 **B 路（pandoc + LaTeX）**；A 路必然崩 |

### ❗ 什么时候问：**开工前就问，别等到导出那一步**

权限模式是**整场会话的固定值**，中途不会变。所以「建索引、写讲义」那一两个小时里它是什么，
导出时还是什么。**别等讲义写完才发现出不了片** —— 那时用户已经白等了很久。

接到任务、确认材料形态之后，第一件事就是看那行 `Current DSH file policy`；如果是受限模式，
**当场**告诉用户，照下面这句说（可直接复制，别自己现编）：

> 导出 PDF 需要把 DSH 权限切到「完全权限（danger-full-access）」。浏览器无头打印要靠多进程 IPC
> 和 crashpad，受限模式下浏览器**启动即崩**，跟传什么参数无关。切一下我 10 秒就能出片。
> 如果不想切，我可以走 LaTeX 备用路线 —— 但那是另一套排版引擎，**观感跟 HTML 版不一样，不是复刻**。

用户说「不切」就**别再劝**，直接走 B 路，并在交付时说明「这份 PDF 是 LaTeX 排版的，
与 HTML 版观感不同」。劝第二遍、或者偷偷换成别的工具去绕沙箱，都是错的。

### 为什么 A 路依赖权限模式

Chromium 要多进程 IPC（建命名管道）与 crashpad（`OpenProcess`），这两个系统调用在受限模式下被拒，
浏览器**启动即崩**，与传什么参数无关：

```
crashpad_client_win.cc:456] OpenProcess: 拒绝访问。 (0x5)
mojo platform_channel.cc:187] Check failed: . : 拒绝访问。 (0x5)
crash server failed to launch                       → exit=3
```

`--headless=old` / `--headless=new` / `--no-sandbox` / `--single-process` / `--no-zygote` /
`--disable-crash-reporter` / `--disable-breakpad` / 覆盖 `TEMP`/`TMP` —— **全都救不了**。
（DSH profile 的 `cordis.yml` 里 `@deepseek-ai/dsh-sandbox-policy` 的 `mode` 默认就是 `workspace-write`。）

❗**模型不能自己换权限模式。** `dsh-ops/lib/permissions.js` 写死了
「Model inputs never select an authority mode」，沙箱拒绝时它给的 nextAction 是
*「Ask the user to change the DSH permission selector to `<mode>`. Do not retry, change directories, or bypass the sandbox.」*
受限时**就照做**：请用户在 GUI 的权限选择器里切到 `danger-full-access`。
不要反复重试、不要绕沙箱、不要换工具穷举 —— 那次穷举烧掉了几个小时。

---

## A 路：浏览器无头打印（首选）

```bash
# 1) 把讲义连同 mathjax/ 与 img/ 整目录复制成一个 ASCII 路径的临时副本
#    （相对路径引用，三个东西必须在一起）
# 2) 打印
"/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
  --headless=new --disable-gpu \
  --user-data-dir="<tmp>/prof" \
  --print-to-pdf="<out>/讲义.pdf" \
  --no-pdf-header-footer \
  --virtual-time-budget=25000 \
  "file:///<tmp>/lec.html"
```

要点：

- **`--virtual-time-budget` 必须给**（实测 25000 够用）。MathJax 是 JS，不给它时间就打印出一堆 `\(…\)` 原文。
- **不需要 base64 内联**：`<script src="mathjax/tex-svg.js">` 和 `<img src="img/pNNN.png">` 用相对路径，
  把这两个目录跟 HTML 放在一起就行。（B 路才必须内联图片。）
- `@page{size:A4; margin:…}` **Chromium 认**（实测出 A4 `594.96 × 841.92 pt`）。
- 路径含中文不稳妥，先复制成 ASCII 名（A 路用的是 ASCII 副本，中文名未单独验证）。
- 实测规模：50 页 / 31 表 / 22 图 / 257 公式 → **8 秒、6.58 MB**。
- 打印出来 50 页（LaTeX 版 29 页）—— 页数不同是正常的，A 路保留浏览器分页与更松的行距。

---

## B 路：pandoc + TeX Live（受限模式下的备用）

❗**B 路产出的是另一台排版引擎的结果，不是 HTML 的复刻。** 同一份讲义 A 路出 **50 页**、
B 路出 **29 页**：行距更紧、分页规则不同，字体、带边框的盒子、表格的观感都变了。
内容与公式两边都正确，但**交付时必须说明「这份是 LaTeX 排版的」**——
用户先看过 HTML、再拿到一份观感完全不同的 PDF，很容易以为 PDF 坏了（本次翻车的原因之一）。

本机可用工具：`D:\anaconda3\Library\bin\pandoc.exe`（pandoc 3.8）、
`D:\texlive\2025\bin\windows\{xelatex,xdvipdfmx}.exe`。

四步（**必须分步，pandoc 不能自己 spawn xelatex**）：

1. **预处理 HTML**：删 `<script>`；`′`(U+2032) → ASCII `'`；数学区裸 `< > &` 转义；每个表注入
   `<colgroup><col style="width:N%">`；删掉与 `\maketitle` 重复的第一个 `<h1>`。
2. **pandoc**：
   ```
   pandoc lec-math.html -o lec.tex \
     -f html+tex_math_single_backslash \
     --lua-filter=box.lua -H head.tex \
     -V documentclass=ctexart -V classoption=fontset=windows \
     -V geometry=a4paper -V geometry=margin=17mm -V fontsize=11pt \
     --toc --toc-depth=2 --top-level-division=section
   ```
   `-f html+tex_math_single_backslash` **是必需的**（`-f html` 不认 `\(…\)`）。
3. `xelatex -no-pdf lec.tex` **循环跑到 `lec.toc` 不再变化**（实测 3 遍；只跑 2 遍目录页码是错的）。
4. `xdvipdfmx -q -E lec.xdv`。

沙箱坑（都踩过，别重试）：pandoc **不能**用 `--pdf-engine`（`createProcess: invalid argument (Bad file descriptor)`）；
xelatex **不能**自己 spawn 输出驱动 xdvipdfmx（`! I can't write on file 'lec.pdf'` + Emergency stop）——
所以第 3、4 步必须手工拆开。

参考实现：`D:\dsh\config\diglogic-ch05\build\{mkpdf.sh, wrap_math.py, box.lua, head.tex}`。
⚠️ 它**耦合了那份讲义的 CSS 类名**（`tip/warn/note/defbox/toc/fml/key` → tcolorbox），换一份文档要自己写映射。

### LaTeX 侧的坑（都是实测踩出来的）

- pandoc 的 xelatex 模板会加载 **`unicode-math`** → `′`(U+2032) 变成**数学活动字符**，
  `\texttt{A′}` 会报 `Missing $ inserted` → `Bad math environment delimiter` →
  `TeX capacity exceeded, sorry [input stack size=10000]`。**预处理把 `′` 换成 ASCII `'`。**
- `⚠ ✔ ✘ ⁿ ① ② ③ ④ ⋮` 在 Latin Modern 里缺字 → `\newfontfamily\symfont{Segoe UI Symbol}` + 一批 `\newunicodechar`。
- pandoc **不改写** `img/xxx.png` 相对路径 → 要么 `\graphicspath{{../out/}{../out/img/}}`，
  要么内联 base64；并加 `\setkeys{Gin}{width=0.93\linewidth,keepaspectratio}`
  （课件截图 1560×878，原尺寸会冲出 A4）。
- 表格没有列宽信息时 pandoc 生成**不换行的 `l` 列**，长单元格直接冲出页面 → **必须注入 `<colgroup>`**。
- `\xeCJKsetup{CJKspace=true}`：xeCJK 默认丢掉两个汉字之间的空格，标题会印成「第 5 章组合逻辑元件」。
- `\AtBeginDocument{\tolerance=3000 \emergencystretch=2.5em}` 压掉大部分 Overfull。

---

## 目视核对（两条路都必须做，不许省）

```bash
D:/texlive/2025/bin/windows/pdftoppm.exe -png -r 100 -f <起页> -l <止页> 讲义.pdf look/p
```

然后把图 **用 `read_image` 打开看**。必须看的页：
① 第 1 页（标题 / 目录框） ② 有 display 公式的页 ③ 列数最多的表 ④ 有插图的页 ⑤ 最后一页。

❗**数值自检不算核对。** `pdfinfo` 的页数、`pdftotext` 能抽出文字、`/Subtype /Image` 计数 ——
这些只能证明「东西进去了」，不能证明版式没坏。**本 skill 历史上就是把 LibreOffice 导出的坏 PDF
当成成功交出去的**：正文冲出页面右边缘被截断、带边框的框塌成怪异小块，而所有数值检查全部通过。
教训一句话：**版式类产出必须看图，数值自检不能代替看图。**

❌ **不要用 LibreOfficeKit 的 PDFium 去核对**：`render_pages.run_worker(..., pdf_path=…)` 画不了
LibreOffice 或 xdvipdfmx 生成的 PDF，一律 `{"ok":false,"code":"failed","error":"PDFium tile paint failed"}`。
用 TeX Live 自带的 poppler —— `pdftoppm` / `pdftocairo` / `pdfinfo` / `pdftotext` / `dvisvgm` / `dvipng`，
都在 `D:\texlive\2025\bin\windows\`。

---

## 写 HTML 时就要守的约束（能省下最贵的那几个小时）

1. ❗**数学环境里绝不能出现裸的 `<` `>` `&`。**
   写了 `Y_{A<B}` 这种，浏览器和 pandoc 都会把 `<B} …` 当成标签名，一直吞到下一个 `>`（通常就是 `</div>` 的 `>`）：

   - ① 公式后半段在浏览器里**直接消失**（所以"HTML 看着没问题"也可能是漏的）；
   - ② 那个 `</div>` 被吃掉 → div 永不闭合 → 转 LaTeX 时后面**所有**表格被嵌进 tcolorbox →
     `\ifinner` 为真 → 每个 figure 报 `! LaTeX Error: Not in outer par mode.`
     （报错在 LaTeX，病根在 HTML）。

   **一律写 `&lt;` `&gt;` `&amp;`。写完跑**：`python scripts/check_html_math.py out/xxx.html`（加 `--apply` 修）。
2. 表格一律给列宽（`<colgroup>`）；`colspan` 分组表头 pandoc 会算错宽度，拆成普通表头 + `<br>`。
3. 每个 `<div class="…">` 必须闭合。
4. pandoc 的 HTML reader **不认** `<span class="math inline">`；裸 `\(…\)` / `\[…\]` 才认（只有 B 路相关）。
5. ❗**屏幕版式用居中窄栏**：`body{max-width:900px;margin:26px auto}` + `html{background:#eef0f3}`，
   并在 `@media print` 里把宽度和内边距撤掉（`max-width:none;margin:0;padding:0`）。
   写 `max-width:100%` 等于没限制，正文会铺满整个显示器 —— 2026-10-18 就是这么错的。
   可复制片段见 [conventions.md](conventions.md) §1.4。

---

## 交付前的 30 秒自查

- [ ] 运行时上下文里那行 `Current DSH file policy` 是什么？受限就别去试浏览器，直接请用户切权限或走 B 路。
- [ ] `python scripts/check_html_math.py out/讲义.html` 报 0 处可疑。
- [ ] PDF 已导出，`ls -l` 看得到非零字节。
- [ ] 抽了 3–5 页渲染成 PNG，**并且真的打开看了**（公式、表格、图、分页）。
- [ ] 与 HTML 对照过第 1 页 —— 版式一致才收工。
- [ ] HTML 在浏览器里是**居中窄栏**（两侧有灰底），不是铺满整个窗口。
