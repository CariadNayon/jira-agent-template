---
name: triage
beschreibung: Prüft offene Tickets ohne Bearbeiter und schlägt nach meinen Regeln Zuständige vor
---
1. Falls der Nutzer ein Projekt oder einen Filter nennt, nutze ihn. Sonst suche mit jira_search:
   `assignee is EMPTY AND resolution = Unresolved ORDER BY created DESC` (max. 20 Tickets).
2. Lies bei unklaren Tickets die Details mit jira_get_issue.
3. Prüfe jedes Ticket gegen die Regeln des Nutzers. Erstelle eine Tabelle:
   Ticket | Zusammenfassung | Vorschlag (Bearbeiter oder Kommentar) | Regel.
   Tickets ohne passende Regel kennzeichnest du mit „keine Regel“.
4. Frage, welche Vorschläge umgesetzt werden sollen. Setze sie erst danach um
   (jira_assign bzw. jira_comment – jede Änderung mit Bestätigung).
