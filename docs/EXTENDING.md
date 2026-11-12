# Eigene Agenten auf dieser Basis bauen

Jira ist der erste Anwendungsfall. Die Vorlage enthält bereits die gemeinsame Laufzeit für Modellaufrufe, Benutzer-Sitzungen, Tools, Bestätigungen, Skills, Dateien und die Databricks-Oberfläche. Neue Anwendungsfälle erweitern diese Schichten, statt einen zweiten Agenten-Unterbau einzuführen.

## Die Bausteine

| Baustein | Verantwortung | Hier erweitern |
|---|---|---|
| Agent | Plant Schritte und wählt verfügbare Tools | `jira_agent/runtime.py`, `config.yaml` |
| Tool | Eine klar beschriebene technische Fähigkeit | neue Datei in `jira_agent/tools/` |
| Client | Verbindung zum externen Dienst; Validierung und REST-Aufrufe | `jira_agent/jira_client.py`, weitere eigene Clients |
| Skill | Wiederverwendbare Anleitung für mehrere Schritte | `skills/<name>.md` oder persönliche Skills im UI |
| Adapter | Einheitliche Schema-Erzeugung und Bestätigung von Änderungen | `jira_agent/adapter.py` |
| Test-Helfer | Dienst simulieren, damit Tests keine echten Änderungen ausführen | `jira_agent/testing.py` |

Die Package-Namen bleiben aus Kompatibilitätsgründen `jira_agent`. Ein Fork kann trotzdem andere Fähigkeiten ergänzen. Es gibt keine Jira-Projekt-Keys oder Bearbeiter in der neuen Aktionslogik. Bestehende persönliche Regeln im Workspace bleiben erhalten; prüfe sie beim Übernehmen der Vorlage.

## Verfügbare Fähigkeiten auswählen

`agent.enabled_tools` in `jira_agent/config.yaml` ist standardmäßig `null`: Alle registrierten Tools werden angeboten, soweit ihre Voraussetzungen erfüllt sind. `needs=["jira"]` blendet ein Tool beispielsweise aus, solange Jira nicht verbunden ist.

Ein rein lesender Jira-Agent kann stattdessen diese Liste verwenden:

```yaml
agent:
  max_turns: 12
  enabled_tools:
    - jira_search
    - jira_get_issue
    - jira_get_myself
    - jira_get_comments
  default_rules: |
    - Fasse die gefundenen Informationen kurz zusammen.
```

Die Liste ist eine Auswahl der Modell-Tools, keine Vergabe von Jira-/Databricks-Rechten. Unbekannte Namen sind ein Konfigurationsfehler. `[]` bietet keine Tools an. Der System-Prompt nennt die tatsächlich verfügbaren Tools. Bei einer expliziten Liste müssen neue Tools auch dort ergänzt werden.

## Ein eigenes Tool ergänzen

1. Neue Python-Datei unter `jira_agent/tools/` anlegen. Sie wird automatisch importiert; es ist keine zweite Registrierung nötig. Namen dürfen nicht doppelt vorkommen.
2. `ToolContext` als ersten Parameter verwenden. Vorhandene Clients und Dateiablagen wiederverwenden.
3. Funktion mit `@tool` dekorieren. Jede externe Änderung bekommt `write=True`, auch eine neue Integration. `needs` nennt notwendige Kontext-Ressourcen.
4. Parameter typisieren und im Docstring erklären. Rückgabe: ein kleines JSON-kompatibles `dict`. Fehler verständlich melden. Keine Zugangsdaten zurückgeben oder protokollieren.
5. Einen Test mit einem Fake-Client schreiben, insbesondere für fehlende Bestätigung, unzulässige Eingaben und Dienstfehler.

Ein Beispiel für die Ableitung eigener Abläufe aus vorhandenen Fähigkeiten (diese Funktion nicht unverändert zusätzlich registrieren, denn `jira_create_issue` existiert bereits):

```python
from jira_agent.testing import FakeJira, run_tool

jira = FakeJira(users=[{"name": "test.user", "displayName": "Test User"}])
preview = run_tool(
    "jira_create_issue", jira=jira, confirm=False,
    project="ABC", summary="Integration testen", issue_type="Task", assignee="@me",
)
assert preview["status"] == "BESTAETIGUNG_NOETIG"
assert not jira.issues
```

`run_tool` bestätigt mit `confirm=True` automatisch und ist nur ein Test-Helfer. Der echte Agent kann die Bestätigung nicht ersetzen. `@me` wird ausschließlich aus `/myself` des persönlichen Jira-Tokens aufgelöst.

Für eine andere Integration einen eigenen Client und bei Bedarf eine zusätzliche Ressource im `ToolContext` ergänzen, diese pro Benutzer in `prepare` initialisieren und über `needs` verfügbar machen. Keine gemeinsamen Benutzer-Zugangsdaten oder privilegierten App-Rechte zum Lesen persönlicher Daten verwenden. Einen neuen Datenbank- oder Framework-Unterbau braucht ein weiteres Tool nicht.

## Einen Ablauf als Skill speichern

Ein Skill kann vorhandene Tools kombinieren, aber keine neuen Berechtigungen oder technischen Fähigkeiten schaffen. Beispiel: `/ticket-entwurf` im Ordner `skills/`. Er erfragt Projekt und Pflichtfelder, erstellt einen Entwurf und ruft das Schreib-Tool erst für die Vorschau auf. Team-Skills erscheinen nach dem Deployment bei allen Nutzern dieser App.

Die Dateien unter `.claude/skills/` sind dagegen Arbeitsanleitungen für die KI, die den Code entwickelt. Für Copilot `AGENTS.md` und die passende Arbeitsanleitung explizit mitgeben.

## Bilder und Dateianhänge

Der Upload und die Verarbeitung sind getrennt: `POST /jira/api/upload?name=image.png&chat_id=<id>` prüft und speichert die Datei, erzeugt eine eindeutige Markdown-Referenz und bindet sie an Benutzer und Chat. Die Oberfläche verwendet die echte Chat-ID auch auf der Startseite. API-Aufrufer können ohne `chat_id` hochladen; die Datei wird beim ersten ausdrücklichen Verweis in einer Benutzernachricht an `context.conversation_id` gebunden. Bereits gebundene Dateien lassen sich nicht in einen anderen Chat umhängen.

`prepare_uploads` in `jira_agent/uploads.py` wertet ausschließlich Referenzen in Benutzernachrichten aus. Andere Uploads des Benutzers sowie Referenzen in Ticket-/Tool-Inhalten werden nicht automatisch bereitgestellt. Der Modell-Kontext bekommt nur die im Verlauf referenzierten Dateien dieses Chats. Die Besitzer können Dateien weiterhin über ihre authentifizierten Download-Links herunterladen.

PNG, JPEG und nicht animiertes WebP werden mit der bereits über matplotlib installierten Pillow-Bibliothek geprüft. Dateiendung und tatsächliches Format müssen passen; maximal 5 MB und 20 Millionen Pixel pro Bild. SVG, GIF, HEIC und beschädigte Bilder werden vor dem Speichern abgelehnt. Andere Uploads bleiben auf 20 MB begrenzt. Die Oberfläche prüft Format/Größe vorab und zeigt bei teilweise fehlgeschlagenen Uploads auch die erfolgreich hochgeladenen Anhänge an. Während eines Uploads wird das Absenden blockiert; ein Chatwechsel darf die fertigen Referenzen nicht in den falschen Chat einfügen.

Das Backend fügt Bilder als native `input_image`-Inhalte mit Data-URL in die zugehörige Benutzernachricht ein. Das vorhandene Agents SDK übersetzt sie für Azure Chat Completions in `image_url`. Der Adapter muss dafür weder Base64-Text als Tool-Ergebnis abschneiden noch einen externen Bild-Link abrufen. `read_uploaded_file` liefert für Bilder nur Name, Format und Abmessungen; Text-/Tabellendateien werden weiterhin über dieses Tool gelesen.

Bis zu vier zuletzt referenzierte Bilder und maximal 10 MB Bilddaten werden pro Anfrage übergeben. Aktuelle Bilder haben Vorrang. Ältere, aus Platzgründen ausgelassene oder abgelaufene Anhänge werden im Modell-Kontext ausdrücklich markiert. Die Dateien liegen weiterhin nur temporär im Arbeitsspeicher. Neue Uploads verwenden IDs in ihren Referenzen; alte `[Datei: name]`-Verweise werden nur aufgelöst, wenn der Name im bereits gebundenen Chat eindeutig ist.

`llm.supports_images: true` ist eine Konfigurationsangabe, kein automatischer Nachweis der Modellfähigkeit. Das tatsächliche Azure-Deployment und seine API-Version müssen Bild-Eingaben unterstützen. Für Textmodelle auf `false` setzen; dann werden Bild-Uploads abgewiesen. Bei einem eigenen Azure-Deployment gilt dieselbe Voraussetzung. Lokale Tests prüfen die tatsächlichen SDK-HTTP-Payloads gegen einen simulierten Azure-Endpunkt; die Erkennungsqualität muss im Ziel-Workspace getestet werden.

Bilder sind Daten, keine Anweisungen oder Freigaben für Jira-Aktionen. Bildinhalte werden an das konfigurierte Modell übertragen und können wie andere Modell-Eingaben in MLflow-Traces erscheinen. Gescanntes PDF, OCR und vollständige Dateianalysen sind dadurch noch nicht implementiert.

## Jira-Verhalten und Grenzen

- Die Integration richtet sich an Jira Data Center mit Bearer-Token und den paginierten Create-Metadaten-Endpunkten (ab Jira 8.4). Jira Cloud benötigt eine angepasste Authentifizierung und Benutzerauflösung.
- Vor der Erstellung Projekt, erstellbare Tickettypen und Pflichtfelder ermitteln. `jira_get_create_fields` liefert zuerst die Feldübersicht. Mit `field_id` die erlaubten Werte eines Felds abrufen, mit `value_query` suchen oder mit `value_offset` weiterblättern.
- `extra_fields` enthält projektspezifische Felder im Jira-API-Format, z. B. `{"customfield_10010": {"id": "42"}}`. Die IDs und Pflichtwerte müssen aus den Metadaten oder vom Nutzer kommen. Für Unteraufgaben muss u. a. ein zulässiger Unteraufgabentyp und `parent` mitgegeben werden; Jira prüft die Regeln des Projekts.
- Bearbeiten ersetzt nur die angegebenen Felder. `jira_get_edit_fields` zeigt die Felder an, die der konkrete Benutzer am konkreten Ticket bearbeiten darf.
- Statuswechsel verwenden die realen Workflow-Übergänge. Zusätzliche Übergangsfelder können über `fields` angegeben werden, sofern Jira sie in den Übergangsmetadaten ausweist. Jira prüft Pflichtfelder und Workflow-Regeln abschließend.
- Änderungen werden einzeln mit `ja CODE` bestätigt. Ein Vorschlag ist 10 Minuten gültig; sein Code wird vor der Ausführung atomar verbraucht. Er ist an Benutzer-Sitzung, Gespräch, Jira-Identität, Tool und unveränderte Argumente gebunden. Tickettexte und Datei-Inhalte gelten nicht als Bestätigung.
- Aktionsbelege liegen im `ActionLedger` der Benutzer-Sitzung. Ein wiederholter bestätigter Aufruf liefert das gespeicherte Ergebnis statt einer zweiten Änderung. Während der Ausführung kommt `AKTION_LAEUFT`. Fehler/Timeouts bleiben als ungeklärtes Ergebnis gesperrt: zuerst in Jira prüfen. Die Sperre gilt auch, wenn das Modell den Code bei einer Wiederholung weglässt.
- Soll dieselbe erfolgreiche Aktion absichtlich erneut ausgeführt werden, ist ein neuer Nutzerauftrag mit neuer Vorschau und neuem Code erforderlich. Derselbe alte Code liefert weiterhin nur seinen Beleg. Geänderte Argumente benötigen ebenfalls einen neuen Code.
- Der Frontend-Build deaktiviert automatische `streamText`-Wiederholungen und den Wechsel zu einem zweiten `generateText`-Agentenlauf nach Transportfehlern. Bereits übertragene Tool-Ergebnisse bleiben sichtbar; der Chat zeigt einen Fehlerhinweis und fordert zur Prüfung auf. Ein leerer Stream beweist nicht, dass Jira nichts ausgeführt hat.
- Diese Belege sind **nicht dauerhaft**: Sie leben nur in der aktuellen Benutzer-Sitzung desselben Workers. Nach Neustart, Abmelden oder Sitzungsablauf bleibt vor einer Wiederholung eine Prüfung in Jira erforderlich. Eine dauerhafte Garantie gegen doppelte Aktionen über Deployments hinweg benötigt eine persistente Ablage und dienstspezifische Abgleiche. Diese Änderung fügt keine Datenbank hinzu.
- Der Speicher ist auf 500 Vorschläge pro Sitzung begrenzt. Bei Erreichen des Limits werden weitere Vorschläge abgewiesen, statt alte Belege zu entfernen. Ungeklärte Aktionen können in derselben Sitzung nicht mit identischen Argumenten automatisch neu gestartet werden.
- Dauerhafte Chatverläufe, geplante Hintergrundjobs, Jira-Administration, Löschaktionen und vollständige Jira-Cloud-Unterstützung sind hier nicht implementiert.

## Prüfen und bereitstellen

```bash
uv run pytest tests -q
uv run deploy --check
uv run deploy
```

Die Tests laufen ohne Jira, Databricks und Modellzugriff. Sie prüfen die Tool-Ausführung, ersetzen aber keinen Modell- und Integrationstest im Ziel-Workspace. Nach dem Deployment Jira erneut verbinden. Dann zuerst eine lesende Anfrage und anschließend ein Testticket in einem dafür vorgesehenen Projekt mit ausdrücklicher Bestätigung ausprobieren.
