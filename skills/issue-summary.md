---
name: issue-summary
description: "Summarizes an issue clearly: problem, current state and next steps"
---
1. The user provides an issue key (e.g. /issue-summary ABC-123). Ask for it if missing.
2. Fetch details with jira_get_issue.
3. Respond using this structure:
   - **What is it about?** 1–2 sentences in plain language.
   - **Current state:** status, priority, assignee and last update.
   - **Open questions / next steps:** bullets based only on the issue.
   - **Applicable rule:** if a user rule applies, cite it and propose the action without executing it.
4. Never invent information. If something is missing, write “not specified in the issue”.
