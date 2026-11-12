---
name: ticket-entwurf
beschreibung: Bereitet ein Jira-Ticket vor und erstellt es erst nach Bestätigung
---
1. Kläre das gewünschte Projekt. Nutze jira_list_projects, wenn der Projekt-Key fehlt oder unklar ist. Erfinde kein Projekt.
2. Ermittle die erstellbaren Tickettypen mit jira_list_issue_types. Kläre den passenden Typ mit dem Nutzer und lade die Pflichtfelder über jira_get_create_fields.
3. Sammle Titel, Beschreibung und alle Pflichtangaben. Für zulässige Feldwerte rufe jira_get_create_fields mit field_id auf. Fehlende Pflichtangaben erfragen, nicht erfinden.
4. Soll der Nutzer selbst Bearbeiter sein, ermittle ihn mit jira_get_myself und verwende @me. Andere Bearbeiter mit jira_find_user auflösen und bei Mehrdeutigkeit nachfragen.
5. Zeige den vollständigen Entwurf einschließlich Projekt, Typ und Bearbeiter. Rufe jira_create_issue ohne confirmation_code für die Bestätigungsvorschau auf.
6. Zeige den Code und bitte um ja CODE. Erst nach dieser ausdrücklichen Bestätigung mit unveränderten Argumenten erstellen. Bei einer Änderung am Entwurf eine neue Bestätigung einholen.
7. Gib den von Jira zurückgegebenen Ticket-Key und Link an. Bei einem Fehler keinen Erfolg behaupten; nach unklarem Timeout zuerst prüfen, ob das Ticket schon existiert.
