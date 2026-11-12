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

Bilder sind Daten, keine Anweisungen oder Freigaben für Jira-Aktionen. Bildinhalte werden an das konfigurierte Modell übertragen und können wie andere Modell-Eingaben in MLflow-Traces erscheinen. Visuelles PDF-Lesen und berechnete Tabellenanalysen werden im folgenden Abschnitt beschrieben.

## Dokumente und Tabellen auswerten

`read_uploaded_file` ist eine Vorschau, keine Berechnungsgrundlage. Bei PDFs liefern `start_page`, `max_pages`, `next_page` und `next_text_offset` einen fortsetzbaren Textauszug. Auch lange Einzel-Seiten lassen sich fortsetzen. `needs_visual_reading` markiert Seiten mit wenig/keinem extrahierbaren Text; daraus lässt sich nicht schließen, dass die Seite leer ist.

`read_pdf_pages` rendert komplette Seiten mit der freigegebenen Bibliothek `pypdfium2`, einschließlich Scans, Text und Layout. Die Seiten werden als echte Bildinhalte an das vorhandene bildfähige Modell übergeben. Das ist visuelles Lesen durch das Modell, keine deterministische OCR oder garantierte Zeichenerkennung. Seitenzahlen und Unsicherheit bleiben Bestandteil der Antwort. Es kommt kein zusätzlicher Cloud-Dienst hinzu.

Grenzen: PDF maximal 500 Seiten; 1–3 visuelle Seiten je Tool-Aufruf, maximal 6 Seiten und 10 MB Seitenbilddaten je Agenten-Anfrage. Längere Dokumente in weiteren Nachrichten fortsetzen. Die längste Bildkante beträgt maximal 1800 Pixel; Fotos mit zu großen PNG-Daten werden als JPEG kodiert. Sehr kleine Schrift kann unleserlich bleiben. Passwortgeschützte PDFs benötigen eine entsperrte Kopie. PDFium-Aufrufe sind im Prozess serialisiert und die nativen Ressourcen werden geschlossen.

Für selbst gestartete SDK-Läufe `jira_agent.model_input.make_run_config()` verwenden. Der SDK-Hook `call_model_input_filter` lässt die Tool-Aufruf-/Ergebnis-Paare unverändert und übergibt gerenderte Tool-Bilder zusätzlich als multimodale Daten an Azure Chat Completions; der Standard-Converter würde Bilder in Tool-Ergebnissen sonst herausfiltern. Diese erzeugten Modell-Eingaben sind keine Nutzerfreigaben: Die Bestätigung prüft weiterhin nur die echte letzte Nutzernachricht. `VisualResult` ist für lesende Bild-Tools vorgesehen. Browser und wiederholte Chat-Historie erhalten über `public_output_item` nur Metadaten und geschützte Vorschaulinks, keine Base64-Blöcke. Für spätere Detailfragen können die Seiten erneut gerendert werden. Modell-Traces können Bildinhalte enthalten.

`analyze_uploaded_table` verwendet das bereits mit MLflow installierte pandas. Es arbeitet über alle eingelesenen CSV-/Excel-Zeilen mit fest definierten Operationen: Profil, Filter, Sortierung und Aggregationen. Es gibt weder `eval`, frei ausgeführten Python-Code noch eine zusätzliche Datenbank. `size` zählt Zeilen einschließlich leerer Zellen, `count` nur nichtleere Werte. Die erste Zeile ist die Kopfzeile; leere/doppelte Namen werden mit dokumentierter Zuordnung eindeutig benannt. Über `columns`, `column_offset` und `max_columns` lassen sich breite Tabellen eingrenzen bzw. Profilspalten durchblättern.

`number_format=auto` konvertiert nur eindeutige Ganzzahlen in CSV-Text. Für Dezimal-/Tausendertrennzeichen sind `de` oder `en` explizit zu wählen; bei Unklarheit soll der Agent fragen. Führende Null-Kennungen bleiben Text. Nicht vollständig numerische Spalten können nicht stillschweigend summiert werden. Berechnungen verwenden übliche Gleitkommaarithmetik, keine garantierte exakte Dezimalrechnung. Excel-Formeln werden nicht ausgeführt; fehlt ein gespeichertes Formel-Ergebnis, verlangt die Analyse eine in Excel neu berechnete Datei. Bei mehreren Blättern muss ein Blatt ausgewählt werden.

Grenzen: 100.000 Datenzeilen, 200 Spalten und 2 Millionen Zellen; entpackte Excel-Dateien maximal 100 MB. Bei Überschreitung gibt es eine Fehlermeldung statt einer stillen Teilberechnung. `max_rows` begrenzt nur die Ergebnisvorschau. Diagramme enthalten maximal 50 Punkte und kennzeichnen ausgelassene/leere Werte. `export_uploaded_table` exportiert alle gefilterten/berechneten Ergebniszeilen innerhalb der Eingabegrenzen, unabhängig vom Vorschau-Limit. XLSX-Textzellen bleiben Text; potenzielle CSV-Formeln erhalten ein führendes Apostroph.

Der Team-Skill `/datei-auswertung` verbindet diese Fähigkeiten zu einem wiederverwendbaren Ablauf.

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

Jira-Suchen liefern `truncated` und `next_start_at`, wenn weitere Treffer vorhanden sind. JQL-Exporte lesen alle Seiten bis `data.export_row_limit` (standardmäßig 5.000 Tickets pro Datei), auch wenn Jira kleinere Seiten zurückgibt. Ohne eigene Sortierung wird `ORDER BY key ASC` ergänzt. Nach etwa 60 Sekunden wird vor der nächsten Seite abgebrochen; ein bereits laufender HTTP-Aufruf kann länger dauern. Begrenzte oder widersprüchliche Ergebnisse erhalten eine Warnung. Mit `next_start_at` lässt sich eine weitere Datei erzeugen. Jira stellt keinen konsistenten Snapshot bereit (`snapshot: false`); Änderungen während eines Exports können trotz stabiler Gesamtzahl Ergebnisse verschieben.

Beim ersten Start lädt die App die getestete Databricks-Frontend-Version aus `scripts/frontend_source.py`. Laufzeit und CI verwenden dieselben Anpassungen für Identität, Uploads, Wiederholungen und Tool-Status. `npm ci` installiert die Versionen aus dem zugehörigen Upstream-Lockfile. Ein vorhandener Ordner `e2e-chatbot-app-next` bleibt erhalten; bei eigenen Änderungen müssen die Anpassungen und der Build erneut geprüft werden. Beim Aktualisieren der Upstream-Version zuerst die Build-Prüfung ausführen. Tool-Ergebnisse mit Fehlern werden als Fehler angezeigt, ausstehende Bestätigungen als solche.

```bash
uv run pytest tests -q
uv run agent-evaluate
uv run deploy --check
uv run deploy
```

Die Tests laufen ohne Jira, Databricks und Modellzugriff. Die GitHub-Prüfungen laufen bei Änderungen an `main` und vor dem manuellen CI-Deploy. Sie ersetzen keine Abnahme im Ziel-Workspace. Optionale echte Modelltests mit simuliertem Jira und die Browser-Abnahme stehen in [ACCEPTANCE.md](ACCEPTANCE.md). Nach dem Deployment Jira erneut verbinden. Dann zuerst eine lesende Anfrage und anschließend ein Testticket in einem dafür vorgesehenen Projekt mit ausdrücklicher Bestätigung ausprobieren.
