---
name: triage
description: "Reviews open unassigned issues and suggests assignees using my rules"
---
1. Use the project or filter specified by the user. Otherwise search with jira_search:
   `assignee is EMPTY AND resolution = Unresolved ORDER BY created DESC` (at most 20 issues).
2. Read details with jira_get_issue when an issue is unclear.
3. Check each issue against the user rules. Create a table:
   Issue | Summary | Suggestion (assignee or comment) | Rule.
   Mark issues with no matching rule as “no rule”.
4. Ask which suggestions should be applied. Apply them only after approval
   (jira_assign or jira_comment; every change requires its own approval).
