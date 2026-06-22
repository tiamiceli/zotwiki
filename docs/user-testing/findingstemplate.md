# ZotWiki — Findings: <short title> (for the Planner)

**Date:** <YYYY-MM-DD>
**Role:** Operating zotwiki as a tool from a plain terminal via `scripts/zw`.
**Command(s):** <the exact `zw …` / `zotwiki …` you ran>
**Config:** `ZOTWIKI_VAULT=<…>`  `ZOTWIKI_COLLECTION=<…>`  → vault `<…/Library/Coll>`
**Status:** <e.g. sync succeeded; pages produced; N peculiarities below>

This is a **symptom report for the planner**, not a fix. The new session should
reproduce each item in a hermetic test (red) before deciding where the fix lives.

---

## TL;DR

<one or two sentences: what's wrong at a glance>

---

## Peculiarities (one block per issue)

### P1 — <short name>
- **Where:** <file/section, e.g. `Library/Test/From Data to Wisdom.md`, "## Claims">
- **Got:**
  ```
  <paste the offending bytes / lines>
  ```
- **Expected:** <what it should have been, and why>
- **Suspected layer:** <compiler prompt §7 | publisher/format §6 | auditor §8 | ask §9.5 | unsure>
- **`zw audit` says:** <relevant violation lines, or "clean">

### P2 — <short name>
- **Where:**
- **Got:**
- **Expected:**
- **Suspected layer:**
- **`zw audit` says:**

<add P3, P4, … as needed>

---

## Reproduction

1. <steps to reproduce against the real library, if relevant>
2. Relevant source item(s): <Zotero title / citekey / key>

## What is NOT the cause (ruled out)

- <anything you already tested and eliminated>

## Full artifacts

- Generated page(s): <paste in full, or reference paths>
- `zw audit` / `zotwiki audit` output: <paste>
- Anything else (runlog excerpt, etc.)
