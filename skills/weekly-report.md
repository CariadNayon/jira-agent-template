---
name: weekly-report
description: "Weekly report of my issues: resolved, in progress and new, with an Excel export"
---
1. Use the current week unless the user specifies another period (e.g. week 46 or last week).
2. Search with jira_search (at most 50 per page; continue with next_start_at when necessary):
   - Resolved: `assignee = currentUser() AND resolved >= startOfWeek()`
   - In progress: `assignee = currentUser() AND resolution = Unresolved AND updated >= startOfWeek()`
   - Newly assigned: `assignee = currentUser() AND created >= startOfWeek()`
   Adjust date functions for the requested period, e.g. `startOfWeek(-1)` and `endOfWeek(-1)`. If results are incomplete, explicitly qualify counts and summaries.
3. Respond with:
   - Three counts at the top (resolved / in progress / new).
   - A short list per section: KEY – Summary (Status).
   - 2–3 sentences about the main themes and notable findings.
4. Offer an Excel export of the listed issues (export_file with source="jql", format="xlsx").
