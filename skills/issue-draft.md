---
name: issue-draft
description: "Prepares a Jira issue and creates it only after approval"
---
1. Clarify the desired project. Use jira_list_projects if the project key is missing or unclear. Never invent a project.
2. Get available issue types with jira_list_issue_types. Clarify the appropriate type with the user and load required fields with jira_get_create_fields.
3. Collect the summary, description and all required values. Get allowed field values with jira_get_create_fields and field_id. Ask for missing required information; never invent it.
4. If the user wants to be the assignee, identify them with jira_get_myself and use @me. Resolve other assignees with jira_find_user and ask if ambiguous.
5. Show the complete draft including project, type and assignee. Call jira_create_issue without confirmation_code to request an approval preview.
6. Show the code and ask for yes CODE. Create the issue with unchanged arguments only after this explicit approval. Changes to the draft require a new approval.
7. Return the issue key and link from Jira. Never claim success on an error; after an ambiguous timeout, first check whether the issue already exists.
