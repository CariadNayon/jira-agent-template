# Stabilitätsstand und reproduzierbare Abnahme

Stand: 17. November 2026, Version 0.3.0. Erster Meilenstein aus [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Ergebnis und Grenzen

Die Ausgangsversion 0.2.6 (`a840fe1b84ba0f24bd0f86c5168d8f5aef6e742f`) bestand 215 Offline-Tests. Die korrigierte Version besteht 252 Tests unter Python 3.11 und 3.12. Der vollständige Frontend-Build wird zusätzlich von GitHub Actions geprüft.

Die benannten Stabilitätsfälle wurden mit synthetischen Diensten wiederholt ausgeführt. Der Bericht unterscheidet diese ausdrücklich von echten Modell- und Jira-Tests. Die lokale Laufzeit ist kein Beleg für Azure-Latenz, Modellqualität oder Kapazität im Workspace. In dieser Arbeitsumgebung fehlen Azure-Key und Databricks-Anmeldung; daher sind reale Modellmessung, echte Jira-Abnahme, Vorschau-Deployment und Lakebase-/UC-Einrichtung noch offen.

## Nachgewiesene und korrigierte Probleme

Die folgenden Prüfungen wurden sowohl gegen den unveränderten Ausgangsstand als auch gegen den neuen Stand ausgeführt:

| Prüfung | v0.2.6 | v0.3.0 |
|---|---|---|
| Ticketdetails liefern den tatsächlichen Projekt-Key | fehlt | vorhanden |
| Eine eindeutig abgelehnte Änderung wird als nicht ausgeführt erkannt | als unklar behandelt | `outcome=not_executed` |
| Neuer Auftrag nach Korrektur kann eine neue Vorschau erhalten | durch unklaren Beleg blockiert | neue Freigabe möglich, alter Code bleibt verbraucht |
| Expliziter Skill bleibt bei Folgemeldungen vollständig verfügbar | nur Name/Beschreibung | vollständige Anleitung bleibt aktiv |
| Modellaufrufe verwenden höchstens zwei SDK-Wiederholungen | bis zu sechs | standardmäßig zwei plus kumulatives Wartebudget |

Zusätzliche Prüfungen belegen, dass unklare Ergebnisse nach Timeout/5xx weiterhin nicht automatisch wiederholt werden. Eine spätere Validierung darf eine bereits mögliche Änderung nicht als „nicht ausgeführt“ ausgeben. Parallele Tool-Aufrufe dürfen ihre Beobachtungen nicht vermischen. Fehlgeformte Standardfelder werden vor der Ticketerstellung abgelehnt.

Das Wartebudget begrenzt Backoff zwischen Modellversuchen, nicht die gesamte Bearbeitungszeit. HTTP-Timeouts, Toolzeit und Streaming sind getrennte Größen. Ein zu langer Retry-After führt zur Rückgabe des ursprünglichen Dienstfehlers, nicht zu einem verfrühten weiteren Versuch. Kontingente werden dadurch nicht erhöht.

## Offline wiederholen

```bash
uv run stability-check --list
uv run stability-check --repeat 2 --json-report work/stability-report.json
uv run pytest tests -q
```

`stability-check` bündelt 26 benannte Szenarien und verknüpft jeden Fall mit den tatsächlich ausgeführten Tests im JUnit-Bericht. Ein Fall ohne passende Tests oder mit übersprungenen/fehlgeschlagenen Prüfungen wird nicht grün gemeldet. Der JSON-Bericht enthält Fall, Wiederholung, Testnamen, Status und lokale Testdauer; keine Prompts oder Zugangsdaten. Ein Fehler liefert Exit-Code 1.

Abgedeckt werden Ticket-Suche, Beispielsuche, Erstellen/Zuweisen/Lesen, Bearbeitungsabläufe, Custom Fields, Übergangsfelder, ungültige Eingaben, unveränderte Freigaben, Ablauf/Gesprächsbindung, parallele Bestätigungen, definitive Ablehnungen, unklare Schreibausgänge, teilweise ausgeführte Aktionen, Retry-After, kumuliertes Modell-Wartebudget, permanente Modellfehler, Wiederholungsgrenzen, Skill-Folgemeldungen, native Bilder, Dateibesitz/Ablauf, Scan-PDF, vollständige Tabellenberechnung, paginierte Exporte, Stream-Abbruch und weitergeleitete Nutzeridentität.

## Nutzer-Skill als Referenz

Der bereitgestellte Skill ist ausschließlich als Testdaten in `agent_server/evaluation.py` hinterlegt:

1. Projekt des Tickets `WEST1-14597` lesen.
2. Neues Ticket mit Titel **Demo mit Mathias test ticket** vorbereiten.
3. Bearbeiter aus dem persönlichen Jira-Token über `@me` auflösen.
4. Kurzes Gedicht über Cariad in die Beschreibung aufnehmen.
5. Ohne Freigabe nichts erstellen; nach Freigabe dieselben Werte übernehmen und Wiederholung als Beleg behandeln.

Der Offline-SDK-Test liefert Modellantworten über einen geskripteten HTTP-Transport und prüft den echten Runtime-/Tool-/Jira-Client-Pfad. Das beweist den Ablauf, nicht das Sprachverständnis eines echten Modells. Eine weitere Prüfung liefert absichtlich einen vom Ticketpräfix abweichenden Projekt-Key zurück, damit eine reine Präfix-Ableitung nicht als Projektermittlung durchgeht.

Die normalen Tools und App-Regeln enthalten keine fest eingebauten WEST1-Projekte oder Demo-Titel.

## Echte Modelle vergleichen

Mit vorhandenem Azure-/Databricks-Zugang:

```bash
uv run agent-evaluate --live --case reference_test_skill \
  --deployment gpt-4.1 --deployment gpt-5-mini --repeat 5 \
  --json-report work/model-comparison.json
```

Das verursacht echte Modellaufrufe. Jira und Dateien bleiben synthetisch; es werden keine echten Tickets angelegt. Jeder Benutzerturn erhält einen eigenen Modellclient und ein frisches Backoff-Budget wie in der App. Die Verbindungen werden wiederverwendet und die Clients danach geschlossen.

Der Bericht enthält pro Fall und Wiederholung Erfolg, Tool-Namen, Laufzeit, Modellrunden, Tool-Aufrufe und gemeldete Tokenmengen. Pro Deployment werden p50/p95-Laufzeiten und Erfolgszahlen ausgewiesen. Eine fehlende Konfiguration ist `blocked`, kein erfolgreich übersprungener Test. Reale Jira-Rechte, Browser-Anmeldung und Last mehrerer Nutzer bleiben eine gesonderte Live-Abnahme.

## Was danach folgt

Nachtrag v0.3.1: Ein zusätzlicher SDK-Streamingtest reproduziert drei erfolgreiche Jira-Metadatenaufrufe und eine anschließende Modell-429. Er prüft, dass kein Schreibaufruf und kein Agentenneustart erfolgt und der Wartehinweis erhalten bleibt. Weitere Tests prüfen die Meldungen für Rate Limits, ausgeschöpfte Kontingente und das Aktualisieren eines bereits heruntergeladenen Frontends. Damit ist die Fehlerbehandlung geprüft, nicht die verfügbare Live-Kapazität erhöht.

- SDK-Sessions und Hintergrundausführung aus der festgelegten Advanced-Vorlage übernehmen.
- Lakebase für Verlauf, freigegebene Laufzustände und dauerhafte Aktionsbelege einrichten; Besitzerprüfungen für Session-/Response-IDs abnehmen.
- Native SDK-Freigaben integrieren. Der aktuelle Legacy-Schreibpfad bleibt bis dahin aktiv; seine Belege sind weiterhin an den Worker und die Sitzung gebunden.
- Strukturierte, versionierte Skills und Agentenprofile im gemeinsamen Unity Catalog ergänzen.
- Live-Modellvergleich und Vorschau-Abnahme durchführen, bevor die laufende App auf den Advanced-Unterbau umgestellt wird.

## v0.4.0: Modelllast begrenzen und nach Drosselung fortsetzen

Der vorhandene Agents SDK übernimmt begrenzte Modellwiederholungen ohne Neustart früherer Tools. Queue/Cooldown wird pro Deployment geteilt; Anmeldedaten und Inhalte werden nicht geteilt. Der Fall „Ticket nach Freigabe erstellt, anschließend 429 mit Retry-After 32 Sekunden“ wird in beiden SDK-Ausgabewegen geprüft: nach virtuellem Warten derselbe Modellrequest, genau ein Jira-POST. Tests decken zusätzlich volle Queues, Abbrüche, hartes Kontingent, Provider-Vetos und verbleibendes Wartebudget ab. Details und Grenzen: [Performance](PERFORMANCE.md#deployment-auswahl-und-gemeinsame-lastgrenzen-v040).

`gpt-4.1-mini` ist der neue Template-Standard. Persönliche Overrides bleiben erhalten; Fast → Save setzt sie zurück. Detailed wählt manuell `gpt-4.1`. Ein automatischer Modellrouter und Live-Qualitäts-/Kapazitätsmessungen sind damit noch nicht umgesetzt.
