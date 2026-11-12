---
name: ticket-zusammenfassung
beschreibung: Fasst ein Ticket verständlich zusammen – Problem, Stand, nächste Schritte
---
1. Der Nutzer nennt einen Ticket-Key (z. B. „/ticket-zusammenfassung ABC-123“). Fehlt er, frage danach.
2. Hole die Details mit jira_get_issue.
3. Antworte in genau diesem Aufbau:
   - **Worum geht es?** 1–2 Sätze in einfacher Sprache.
   - **Stand:** Status, Priorität, Bearbeiter, zuletzt geändert.
   - **Offene Punkte / nächste Schritte:** Stichpunkte, nur was aus dem Ticket hervorgeht.
   - **Passende Regel:** falls eine Regel des Nutzers zutrifft, nenne sie und schlage die Aktion vor (nicht ausführen).
4. Erfinde nichts. Fehlt eine Information, schreibe „nicht im Ticket angegeben“.
