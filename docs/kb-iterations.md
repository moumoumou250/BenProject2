# KB 迭代账本

记录每一次「按 probe / kb check 结果回补 KB」的动作与前后对照。  
确认方案：[plans/KB-FEEDBACK-LOOP.md](plans/KB-FEEDBACK-LOOP.md)（状态：已确认）。

## 规则

1. 一条记录**只允许一个动作类**（A 判据 / B 内容 / C 别名 / D 词表），混做则拆成多条；
2. 「前」「后」必须成对；未复跑视为未完成，不得提交记录；
3. 「改动」写到条目与字段，例如 `kb002.tags += blind,boolean`，不写「更新了 KB」；
4. 与 `CHANGELOG.md` 分工：CHANGELOG 记代码，本文件记知识；
5. entries 与本账本**同 commit**；不删条目（标 deprecated），规避 id 复用；
6. agent 自动写入须 `source` 以 `agent/` 开头，迭代提交前与人工改动分开看。

## 记录

| 日期 | target | vuln | probe前 | diagnose | 动作类 | 改动 | probe后 | check后 |
|---|---|---|---|---|---|---|---|---|
| 2026-11-18 | tomcat-cve-2017-12615 | file-write | 3 NO_VALIDATION | — | A 补判据 | kb003.validation += signal/baseline/reject/min_evidence | 0 CONFIRMED | 0 HIT（`文件上传 --only kb003`）；反例 `文件上传 --only kb002` 仍 1 |

## 待办（按确认方案 §12）

- [x] S0：`source=agent/...` 写入 explore.md；search 基线在 `runs/kb-baseline/`（整仓 commit 仍待用户明示）
- [x] S1：`ben/kb/match.py` + `tests/test_kb_match.py`
- [x] S2：`check`/`diagnose` + `tests/test_kb_check.py`
- [x] S3：最小 `ben/kb/taxonomy.json`
- [x] S4：`kb003.validation` + `ben probe` file-write；Tomcat:8081 实跑 CONFIRMED；证据 `runs/probe/...`
- [x] S5：本表首条真实记录（上表）
