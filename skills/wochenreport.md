---
name: wochenreport
beschreibung: Wochenbericht meiner Tickets – erledigt, in Arbeit, neu – mit Excel-Export
---
1. Zeitraum: die aktuelle Woche, außer der Nutzer nennt einen anderen (z. B. „KW 46“ oder „letzte Woche“).
2. Suche mit jira_search (max. 50):
   - Erledigt: `assignee = currentUser() AND resolved >= startOfWeek()`
   - In Arbeit: `assignee = currentUser() AND resolution = Unresolved AND updated >= startOfWeek()`
   - Neu zugewiesen: `assignee = currentUser() AND created >= startOfWeek()`
   Passe die Datumsfunktionen an den gewünschten Zeitraum an (z. B. `startOfWeek(-1)` und `endOfWeek(-1)`).
3. Antworte mit:
   - drei Zahlen oben (erledigt / in Arbeit / neu),
   - je Abschnitt einer kurzen Liste „KEY – Zusammenfassung (Status)“,
   - 2–3 Sätzen Fazit (Schwerpunkte, Auffälligkeiten).
4. Biete am Ende einen Excel-Export aller genannten Tickets an (export_file mit source="jql", format="xlsx").
