# OSINT Report Template

Use this template when creating a new report or doing a major structural rewrite.
For small recurring updates, preserve the existing file shape and update only the
relevant sections.

## Template

```md
# [Report Name]

> One-line description

## Overview

**Status:** `Draft` | `Final` | `Archived`
**Category:** `AI/ML` | `Infrastructure` | `Mobile` | `Web` | `Companies` | `Business` | `Research` | `Geopolitics` | `Real Estate` | `Technology`
**Started:** YYYY-MM-DD
**Last Updated:** YYYY-MM-DD

## Description

[Purpose, target users, value proposition]

## Subject Profile

[Structured data - tables, lists, key facts]

## Key Findings

[Analysis, patterns, insights]

## Critical Changes

[New entities, updates, significant developments]
[Omit this section for first-pass reports with no prior baseline]

## Knowledge Graph

- Entities added: N
- Relations added: N
  [Entity list with types and relations]

## Sources

- [Formatted links with descriptions]

Report compiled: Month DD, YYYY
```

## Notes

- Keep source descriptions short and specific.
- Include dates near claims that can change over time.
- If confidence is low or entities are ambiguous, say so explicitly in the report.
- For messaging delivery, flatten tables into bullets or label/value lines.
- When citing Sources, consider including only the major ones (limit to < 10 total sources).
