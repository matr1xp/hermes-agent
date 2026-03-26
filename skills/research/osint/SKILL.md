---
name: osint
description: OSINT research workflow for collecting information on people, companies, topics, or events and turning it into structured reports without assuming a hardcoded output directory.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [OSINT, Research, Intelligence, Report-Generation, Entity-Tracking]
    related_skills: [arxiv, domain-intel, blogwatcher]
---

# OSINT Skill

## Purpose

This skill transforms Hermes into a researcher/collector agent that:

1. Gathers intelligence on specified subjects (people, companies, topics, events)
2. Tracks entities across collection cycles
3. Outputs structured reports using the template below
4. Optionally maintains an index in the chosen report root

## When to Use

- User requests OSINT research on a person, company, or topic
- User wants periodic collection cycles on a subject
- User needs structured findings saved as files
- Building knowledge graphs from collected data

## Output Location Policy

Do not assume a machine-specific path.

- If the user names an output directory or filename, use that.
- Otherwise, default to a workspace-relative directory such as `research/osint/`.
- Treat relative paths as relative to the active working directory / backend workspace.
- If the user only wants a one-off answer, return the findings in-chat instead of creating files.

Recommended conventions:

- Report root: `research/osint/`
- Report index: `research/osint/REPORTS.md`
- Subject report: `research/osint/<subject_slug>_osint.md`
- Optional knowledge base snapshot: `research/osint/<subject_slug>_kb.json`

## References

- Use `references/report-template.md` when writing or updating the actual report structure.
- Keep `SKILL.md` focused on workflow and decision rules; load the reference only when you need the template details.

## Workflow

### Phase 1: Setup

1. **Define the research target**
   - Subject name(s), aliases, known identifiers
   - Focus area: person, company, event, technology, etc.
   - Collection scope: web, social media, academic, news, etc.

2. **Resolve the output location**
   - Use a user-provided directory if one exists
   - Otherwise default to `research/osint/`
   - Only create the directory when the user wants files persisted

3. **Check existing reports**
   ```
   read_file research/osint/REPORTS.md
   search_files "subject-name" path=research/osint/
   ```

   - Avoid duplicates
   - Build on prior cycles if they exist

### Phase 2: Data Collection

4. **Gather sources** using available tools:
   - `web_search` - Find relevant pages, news, profiles
   - `web_extract` - Extract content from URLs
   - `browser_navigate` + `browser_snapshot` - Interactive pages
   - `session_search` - Check past conversations for prior research

5. **Extract entities**:
   - People: name, role, location, affiliations, identifiers (LinkedIn, GitHub, etc.)
   - Organizations: name, type, location, key facts
   - Events: dates, locations, participants, outcomes
   - Digital assets: URLs, repos, profiles, publications

6. **Track changes** (for recurring collections):
   - New entities discovered
   - Updated information (role changes, transfers, etc.)
   - Critical developments (high significance)

### Phase 3: Report Generation

7. **Create or update the report file**
   - Load `references/report-template.md`
   - Keep sections that are still useful; do not rewrite a mature report from scratch unless the user asked for a reset
   - Prefer additive updates for recurring collection cycles

8. **Save report** to the chosen report root, for example `research/osint/[report_name].md`

9. **Update `REPORTS.md` index** when the user wants a persistent report set:
   - Add entry to Reports Overview table
   - Add Report Details section
   - Update "Last updated" date

### Phase 4: Knowledge Base (Optional)

10. **Create JSON knowledge base** (for complex multi-entity tracking):
   ```json
   {
     "collection_date": "YYYY-MM-DD",
     "cycle": N,
     "target_subject": "...",
     "focus_area": "...",
     "total_entities": N,
     "total_relations": N,
     "sources_processed": N,
     "persons_tracked": [...],
     "critical_changes": [...],
     "knowledge_base_snapshot": {...}
   }
   ```
   Save to the same report root as `[report_name]_kb.json`

## Output Conventions

- **Filenames**: snake_case WITHOUT date, e.g., `marlon_santos_osint.md` - stable filename for recurring collections
- **Paths**: prefer workspace-relative paths unless the user explicitly requests an absolute path
- **Template loading**: read `references/report-template.md` only when drafting or restructuring the file
- **Status**: Draft (active collection), Final (complete), Archived (historical)
- **Category**: Match subject type (Research, Companies, Technology, etc.)
- **Dates**: ISO format (YYYY-MM-DD) in metadata, human-readable in footer
- **Telegram delivery**: NO Markdown tables or formatting - use plain text with dashes/colons for alignment

## Report Update Strategy (Critical)

**Always check for existing reports BEFORE creating new files:**

1. **Search for existing report:**

   ```
   search_files "subject-name_osint" path=research/osint/ target="files"
   ```

2. **If found:** UPDATE the existing file (do NOT create a new dated file)
   - Merge new data into existing sections
   - Update "Last Updated" date in Overview
   - Add new entities to Knowledge Graph
   - Append new findings to Critical Changes section
   - Preserve historical data — do not overwrite

3. **If NOT found:** CREATE new baseline report
   - Use stable filename: subject_name_osint.md (no date)
   - Follow REPORT_TEMPLATE.md structure

**Why:** Recurring collections on the same subject should accumulate in ONE file, not spawn dated copies. This prevents report fragmentation and makes REPORTS.md maintenance simpler.

## Pitfalls

- **Duplicate reports**: Always check REPORTS.md and search existing files first
- **Hardcoded paths**: Never assume `~/...` or another user-specific directory unless the user explicitly requested it
- **Stale data**: Web searches can return outdated info - verify dates
- **Entity disambiguation**: Same name may refer to multiple people - track separately
- **Index drift**: Remember to update REPORTS.md after creating new reports
- **Over-collection**: Focus on high-signal sources; don't dump everything
- **Social media speculation**: Do NOT rely on social bios/posts for critical facts (family, legal status, relationships). Verify through official sources (league sites, news outlets, court records, press releases) before stating as fact

## Verification

After completing a report:

1. Confirm the chosen output file exists
2. If using an index, verify `REPORTS.md` was updated with the new or revised entry
3. Check the report has all required sections from the template
4. Validate sources are properly formatted with working URLs

## Example Usage

```
User: Research Marlon Santos - find all people with this name, track their professional profiles

1. web_search("Marlon Santos LinkedIn GitHub")
2. web_search("Marlon Santos footballer transfermarkt")
3. web_search("Marlon Santos researcher scholar")
4. Extract profiles from top results
5. Disambiguate: separate by location, profession, identifiers
6. Build entity list with confidence levels
7. Generate report using template
8. Save to research/osint/marlon_santos_osint.md
9. Update REPORTS.md index if maintaining a persistent report set
```

## Related Skills

- `arxiv`: Academic paper search
- `domain-intel`: Passive domain reconnaissance
- `github-issues`: GitHub entity tracking
- `blogwatcher`: Content monitoring
