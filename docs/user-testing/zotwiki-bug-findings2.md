# ZotWiki — Findings: Wiki Formatting (for the Planner)

**Date:** 2026-06-20
**Role:** Operating zotwiki as a tool from a plain terminal via `scripts/zw`.
**Command(s):** `zw sync` , `zw audit` . 
**Config:** `ZOTWIKI_VAULT="/Users/miceli/Library/Mobile Documents/iCloud~md~obsidian/Documents/reserach_obsidian_vault/Library"`  `ZOTWIKI_COLLECTION="Test"`  → vault `<…/Library/Coll>`
**Status:** sync succeeded; pages produced; 2 peculiarities below

This is a **symptom report for the planner**, not a fix. The new session should
reproduce each item in a hermetic test (red) before deciding where the fix lives.

---

## TL;DR

The wiki heirarchy needs to be revised, and there is a bug in the Claims sections.

---

## Peculiarities (one block per issue)

### P1 — Wiki Heirarchy Index & Concepts
- **Where:** in the obsidian vault

- **Got:**
  This file hierarchy `zotwiki/docs/user-testing/20260619_navigation.png`
  
  ```
  ⌄ Library
  	⌄ Test
  		A Typology of ....
  		From Data to Wisdom ...
  		Index
    Anomaly detection
  ```
  
  This Index content `zotwiki/docs/user-testing/20260619_Index.md`
  
  ```
  # Index
  
  - [[A Typology of Data Anomalies]]
  - [[From Data to Wisdom]]
  ```
  
  This Links section in `zotwiki/docs/user-testing/20260619_A_Typology_of_Data_Anomalies.md`
  
  ```
  ## Links
  
  - [[Anomaly detection]]
  - [[Data mining]]
  - [[Data quality]]
  - [[Fraud detection]]
  - [[Machine learning]]
  - [[Outliers]]
  - [[Pattern recognition]]
  - [[Time series analysis]]
  ```
  
  
  
- **Expected:** 
  a. Index is maintained per collection, and stored at the collection level, and name reflects to collection name. This allows users to clearly see which collections have which papers.
  b. Concepts linked in the collections' summaries appear in a separate section at the same level as Library, called "Concepts". This allows users to draw concepts and connect them from multiple collections.

  ```
  ⌄ Library
  	⌄ Test
  		Test Index
  		A Typology of ....
  		From Data to Wisdom ...
  ⌄ Concepts
    Anomaly detection
  ```

  This Index content instead

  ```
  # Test Index
  
  - [[Library/Test/A Typology of Data Anomalies|A Typology of Data Anomalies]]
  - [[Library/Test/From Data to Wisdom|From Data to Wisdom]]
  ```

  This Links section instead for example

  ```
  ## Links
  
  - [[Concepts/Anomaly detection|Anomaly detection]]
  - [[Concepts/Data mining|Data mining]]
  - [[Concepts/Data quality|Data quality]]
  - [[Concepts/Fraud detection|Fraud detection]]
  - [[Concepts/Machine learning|Machine learning]]
  - [[Concepts/Outliers|Outliers]]
  - [[Concepts/Pattern recognition|Pattern recognition]]
  - [[Concepts/Time series analysis|Time series analysis]]
  ```

- **Suspected layer:** formatting?

### P2 — zw audit BROKEN_LINKs
- **Where:** in the stdout response of `zw audit`

- **Got:**

  ```
  BROKEN_LINK	A Typology of Data Anomalies.md	Anomaly detection
  BROKEN_LINK	A Typology of Data Anomalies.md	Data mining
  BROKEN_LINK	A Typology of Data Anomalies.md	Data quality
  BROKEN_LINK	A Typology of Data Anomalies.md	Fraud detection
  BROKEN_LINK	A Typology of Data Anomalies.md	Machine learning
  BROKEN_LINK	A Typology of Data Anomalies.md	Outliers
  BROKEN_LINK	A Typology of Data Anomalies.md	Pattern recognition
  BROKEN_LINK	A Typology of Data Anomalies.md	Time series analysis
  BROKEN_LINK	From Data to Wisdom.md	DIKW Hierarchy
  BROKEN_LINK	From Data to Wisdom.md	Knowledge Management
  BROKEN_LINK	From Data to Wisdom.md	Management Information Systems
  BROKEN_LINK	From Data to Wisdom.md	Organizational Learning
  BROKEN_LINK	From Data to Wisdom.md	Russell Ackoff
  BROKEN_LINK	From Data to Wisdom.md	Stakeholder Theory
  BROKEN_LINK	From Data to Wisdom.md	Systems Thinking
  audit: 15 violation(s)
  ```

- **Expected:** audit to give "notifications" that these are possible "Concepts" that can be populated. (not "violations")

- **Suspected layer:** audit
