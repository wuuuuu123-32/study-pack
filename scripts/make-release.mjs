#!/usr/bin/env node
// 建 GitHub Release —— 本机没装 gh，所以直接用 git 自己存的凭据调 API。
//
//   node scripts/make-release.mjs            # 给「有 tag 但没有 Release」的版本补建
//   node scripts/make-release.mjs v0.6.0     # 只建指定版本
//   node scripts/make-release.mjs --dry-run  # 只报告，不发请求
//
// Release 正文取 CHANGELOG.md 里对应的 `## vX.Y.Z — 日期` 一节，标题用 `vX.Y.Z — 日期`。
// 凭据来源：环境变量 GITHUB_TOKEN，否则向 `git credential fill` 要（wincred 里那份）。
// 凭据只在内存里传递，不打印、不落盘。

import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

const OWNER = 'wuuuuu123-32';
const REPO = 'study-pack';
const API = `https://api.github.com/repos/${OWNER}/${REPO}`;

const argv = process.argv.slice(2);
const DRY = argv.includes('--dry-run');
const wanted = argv.filter((a) => !a.startsWith('--'));

// ── 凭据 ────────────────────────────────────────────────────
function token() {
  if (process.env.GITHUB_TOKEN) return process.env.GITHUB_TOKEN;
  const raw = execFileSync('git', ['credential', 'fill'], {
    input: 'protocol=https\nhost=github.com\n\n',
    encoding: 'utf8',
    env: { ...process.env, GIT_TERMINAL_PROMPT: '0' },
  });
  const line = raw.split('\n').find((l) => l.startsWith('password='));
  if (!line) throw new Error('git credential fill 没有返回 password（本地没存 GitHub 凭据？）');
  return line.slice('password='.length);
}

// ── CHANGELOG → { vX.Y.Z: {date, body} } ────────────────────
function sections() {
  const out = {};
  for (const chunk of readFileSync('CHANGELOG.md', 'utf8').split(/^## /m).slice(1)) {
    const m = chunk.match(/^(v[\d.]+)\s*—\s*(\S+)/);
    if (m) out[m[1]] = { date: m[2], body: chunk.slice(chunk.indexOf('\n') + 1).trim() };
  }
  return out;
}

// ── 主流程 ──────────────────────────────────────────────────
const tags = execFileSync('git', ['tag', '-l'], { encoding: 'utf8' })
  .split('\n').map((s) => s.trim()).filter(Boolean);
const rel = sections();

let todo = wanted.length ? wanted : tags;
if (!wanted.length) {
  const res = await fetch(`${API}/releases?per_page=100`, {
    headers: { accept: 'application/vnd.github+json', 'user-agent': 'dsh' },
  });
  if (!res.ok) throw new Error(`列 Release 失败：HTTP ${res.status} ${await res.text()}`);
  const have = new Set((await res.json()).map((r) => r.tag_name));
  todo = tags.filter((t) => !have.has(t));
  console.log(`远端已有 ${have.size} 个 Release；待补 ${todo.length} 个：${todo.join(' ') || '（无）'}`);
}

if (!todo.length) { console.log('没有要建的 Release。'); process.exit(0); }

for (const tag of todo.sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))) {
  if (!tags.includes(tag)) { console.log(`${tag}: ⚠️ 本地没有这个 tag，跳过`); continue; }
  const sec = rel[tag];
  if (!sec) { console.log(`${tag}: ⚠️ CHANGELOG 里没有这一节，跳过`); continue; }

  if (DRY) { console.log(`${tag}: [dry-run] 会建，正文 ${sec.body.length} 字符`); continue; }

  const res = await fetch(`${API}/releases`, {
    method: 'POST',
    headers: {
      authorization: `Bearer ${token()}`,
      accept: 'application/vnd.github+json',
      'content-type': 'application/json',
      'user-agent': 'study-pack-release',
    },
    body: JSON.stringify({
      tag_name: tag,
      name: `${tag} — ${sec.date}`,
      body: sec.body,
      draft: false,
      prerelease: false,
    }),
  });
  const json = await res.json().catch(() => ({}));
  if (res.ok) console.log(`${tag}: ✅ ${json.html_url}`);
  else if (res.status === 422) console.log(`${tag}: ⏭️  已存在`);
  else console.log(`${tag}: ❌ HTTP ${res.status} ${json.message ?? ''}`);
}
