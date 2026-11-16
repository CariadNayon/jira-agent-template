---
name: search-tickets
description: Finds Jira tickets with clear project, text, assignee and status filters
---
1. Extract the user's requested filters. Prefer jira_search_tickets for project, plain text phrase, assignee, open/resolved state and exact Jira status. Use @me for “my tickets” and @unassigned for unassigned tickets. Empty assignee means anyone. Never silently limit a general search to the current user.
2. Ask only for genuinely ambiguous filters, such as an unknown project or person. Use jira_list_projects with a query or jira_find_user when needed. Do not invent project keys or translate Jira status values. “Open” means unresolved and includes in-progress issues.
3. Use a small preview, normally 10 tickets; use 1 if the user asks for one example. Show a compact table with key, summary, status, assignee and last update. State the search scope and distinguish total matches from displayed rows.
4. Respect truncated and next_start_at. Continue the same filters with next_start_at if the user asks for more; never describe a preview as all matches. For full exports, use export_file with the returned query and report its completeness limits.
5. Use jira_search only for explicit advanced JQL or filters not supported by jira_search_tickets. Preserve user-supplied JQL. This workflow makes no changes.
