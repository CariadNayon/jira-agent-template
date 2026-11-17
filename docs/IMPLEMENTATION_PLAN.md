# Umsetzungsplan: robustes Jira-Agenten-Template

Stand: 17. November 2026. Umsetzung begonnen. P0: Offline-Baseline und reproduzierbare Fehlertests liegen vor; Live-Messung bleibt ohne Zugang offen. Erste Korrekturen aus P2/P3/P4 sind umgesetzt. Von P5 ist der erste Schnitt umgesetzt: veröffentlichte, unveränderliche Skill-Versionen in Unity Catalog ([REGISTRY.md](REGISTRY.md), Schema `ude_dev_we_cariad_t1s_sandbox.t1_jira_agent`), standardmäßig aus und noch nicht gegen ein echtes Warehouse geprüft. Advanced-Migration, Lakebase, Agentenprofile und Freigabestatus sind noch nicht eingerichtet.

## Ziel und Entscheidungen

- Grundlage: offizielle Databricks-Vorlage `agent-openai-advanced` und vorhandenes OpenAI Agents SDK. Kein Wechsel zu Pi, LangGraph oder Dify in dieser Umsetzung.
- Jira bleibt der erste vollständig abgenommene Anwendungsfall. Der gemeinsame Unterbau unterstützt weitere Agentenprofile.
- Lakebase speichert operative App-Daten: Gespräche, freigegebene Laufzustände, Eigentümer-Zuordnungen und Aktionsbelege. Unity Catalog verwaltet veröffentlichte Skills und Agentendefinitionen mit Versionen.
- Fachliche Zugriffe auf Jira und Unity Catalog erfolgen weiterhin mit den Rechten des angemeldeten Nutzers. Technische App-Daten in Lakebase benötigen strikt geprüfte Eigentümer- und Zugriffsregeln.
- Keine Tokens oder Keys in Gesprächshistorie, serialisiertem RunState, Agentendefinitionen oder unverschlüsselten Datenbankfeldern. Browser-Passwortmanager bleibt der einfache Verbindungsweg; die verschlüsselte Databricks-Erinnerung bleibt optional.
- Bestehende Tools, Upload-/Bild-/PDF-/Tabellenfunktionen, persönliche Einstellungen und Skills werden erhalten oder ausdrücklich migriert.
- Agentenprofile sind Konfigurationen mit freigegebenen Tools und Skill-Versionen. Eine Multi-Agent-Orchestrierung ist zunächst nicht erforderlich.
- Produktoberfläche und Guide bleiben Englisch. Technische Absprachen erfolgen Deutsch.

## Geprüfte Ausgangsstände

- Jira-Repository: `a840fe1b84ba0f24bd0f86c5168d8f5aef6e742f`, Version 0.2.6.
- Databricks-App-Templates: `71f815f6a6b09b514b79105390ad73ec0e6bf220`, Verzeichnis `agent-openai-advanced`.
- Vor jeder Implementierung Remote-Stand erneut abgleichen. Alte lokale Zwischenstände nicht ungeprüft einspielen.
- Die Advanced-Vorlage liefert persistente SDK-Sessions, Hintergrundausführung und Stream-Wiederaufnahme. Sie ist eine Vorlage, keine bereits für unsere Nutzer-/Jira-Rechte abgenommene Anwendung.
- Gezielte Anpassungspunkte: Die Beispielvorlage übernimmt eine clientseitige Session-ID und dedupliziert anhand der Nachrichtenanzahl. Für uns müssen Eigentümerprüfung und inhaltliche Deduplizierung verbindlich sein. Initialisierung über private SDK-APIs wird gekapselt und mit den gewählten Paketversionen geprüft.
- Hintergrundausführung überlebt einen HTTP-Abbruch; die Wiederaufnahme nach Prozessabsturz oder Deployment ist gesondert nachzuweisen. Gespeicherter Verlauf allein beweist keine fortsetzbare Ausführung.

## Reihenfolge und Abnahme

### P0 – Ausgangsmessung und reproduzierbare Fehler

Arbeiten:
- Aktuellen `main` isoliert auschecken; vorhandene Offline- und Frontend-Prüfungen ausführen und tatsächliche Ergebnisse dokumentieren.
- 20–30 repräsentative Fälle erstellen: Suche, Anzeige, Erstellen, Bearbeiten, Zuweisen, Status, Kommentare, eigene Skills, Anhänge und lange Gespräche.
- Den tatsächlichen Testticket-Skill als Referenzfall übernehmen; seine festen Werte bilden die erwarteten Ergebnisse. Keine Projektwerte erfinden.
- Fehlerfälle ergänzen: 400/401/403/429, 5xx, ungültige Tool-Argumente, Timeouts vor/nach Schreibaufruf, parallele Anfragen, verlorener Stream, Neustart und fehlende Verbindung.
- Modellzeit, Toolzeit, Wiederholungen, Kontextgröße und erste sichtbare Rückmeldung erfassen. Azure- und Jira-Drosselung unterscheiden; Kontingente und API-Kompatibilität der angebotenen Deployments erfassen.
- Klar reproduzierbare dringende Fehler bereits als kleine Korrekturen für die bestehende App freigeben, sofern die jeweilige Abnahme besteht. Die großen Migrationsschritte sind dafür keine Voraussetzung.

Fertig, wenn: Ein reproduzierbarer Prüfbericht mit Baseline und priorisierter Fehlerliste vorliegt. Ohne Live-Zugang werden Live-Fälle als ungeprüft ausgewiesen.

### P1 – Advanced-Unterbau und Lakebase integrieren

Arbeiten:
- Freigegebenen Upstream-Stand und kompatible Paketversionen festhalten. Aus der Vorlage Sessions, Server und Stream-Protokoll übernehmen; unseren Azure-Provider und fachlichen ToolContext einbinden.
- Zuerst eine separate Vorschau-App vorsehen, vorgeschlagener Name `agent-jira-v3-preview`.
- Einrichtung über vorhandene Quickstart-/Deploy-Befehle erweitern: vorhandene Lakebase-Ressourcen verwenden oder im Rahmen einer berechtigten Ersteinrichtung provisionieren. Keine vorhandenen Ressourcen überschreiben. Ressourcen und nicht geheime Referenzen zentral konfigurieren.
- Datenbankmigrationen versionieren und Startbereitschaft prüfen. Datenbankausfälle verständlich anzeigen; keine stillschweigende flüchtige Ersatzablage für angeblich gespeicherte Daten.
- Session-IDs, Response-IDs, Stream-Retrieve und gegebenenfalls Cancel an die vertrauenswürdige Databricks-Identität, App und Unterhaltung binden. Vom Client mitgegebene IDs ersetzen keine Autorisierung.
- Das SDK verwaltet den kanonischen Verlauf. Frontend-Replays über IDs/Inhalt prüfen, statt allein Nachrichtenanzahlen zu vergleichen. Tool-Aufruf-/Ergebnis-Paare und Dateiverweise erhalten.
- Eigentümergesteuertes Löschen und Aufbewahrungsfristen für Chats, Laufzustände und Traces festlegen. Uploads behalten zunächst ihre bisherige zeitliche Gültigkeit; ein gespeicherter Chat verlängert diese nicht automatisch. Nach Ablauf oder Verlust temporärer Dateien verständlich um erneutes Anhängen bitten. Eine spätere dauerhafte Dateiablage wird getrennt geplant.
- Hintergrundaufträge übernehmen keine unbeschränkt gültigen Berechtigungen. Nach Ablauf eines benötigten Zugangs pausieren sie mit einer klaren Aufforderung zur erneuten Verbindung.
- Zunächst bei einem Worker bleiben: flüchtige Zugangsdaten und Uploads sind noch nicht automatisch für mehrere Worker geeignet.

Fertig, wenn: Zwei Nutzer keine fremden Gespräche, Antworten oder Streams abrufen können; Verlauf persistent ist; Reconnect keinen zweiten Auftrag startet; Abbruch- und Neustartverhalten belegt ist.

### P2 – SDK-Freigaben und Jira-Schreibpfad stabilisieren

Arbeiten:
- Schreib-Tools weiterhin als `write=True` klassifizieren und auf die nativen SDK-Freigaben abbilden. Modellaufruf pausieren, feste Argumente anzeigen, vom authentifizierten Nutzer bestätigen/ablehnen lassen und denselben Lauf fortsetzen.
- Legacy-`yes CODE` während einer definierten Übergangszeit kompatibel behandeln. Pro Auftrag genau einen Freigabemechanismus verwenden. DOM-/Textsuche nach Bestätigungscodes danach aus dem primären Ablauf entfernen.
- Pausierten Laufzustand über eine Allowlist serialisieren. Keine JiraClient-Instanzen, Header, Tokens oder Kontextobjekte mit Geheimnissen persistieren. Identität und Zugänge beim Fortsetzen erneut auflösen und prüfen.
- Pending Approvals und Aktionsbelege in Lakebase führen, mit atomarem Claim, stabiler Aktions-ID und Bindung an Nutzer, App, Gespräch, Tool und Argumente.
- Validierungsfehler vor einem Aufruf, definitive Ablehnungen und unbekannte Ergebnisse nach einem möglicherweise ausgeführten Schreibaufruf trennen. Unbekannte Ergebnisse nicht automatisch wiederholen; zuerst in Jira abgleichen oder zur Klärung anhalten.
- Jira-Änderungen nicht durch einen neuen Agentenlauf, Modellwechsel, Reconnect oder eine wiederholte Bestätigung erneut auslösen. Eine absolute Exactly-once-Garantie ohne passende Jira-Schnittstelle wird nicht versprochen.
- Bestehendes Auto-Approve auf diesen Ausführungspfad abgleichen. Keine automatische Übernahme offener Freigaben in einen anderen Auftrag; serverseitig begrenzte Delegation wäre eine eigene, separat abzunehmende Funktion.
- Fähigkeitenmatrix gegen reale Projektregeln abnehmen: Suche, Details, Erstellen, Felder, Bearbeiter, Priorität, Status, Kommentare, Labels, Verknüpfungen, Arbeitszeit und erlaubte projektspezifische Felder. Weitere Fähigkeiten nur aus nachgewiesenen Lücken ergänzen.

Fertig, wenn: Verweigerte Freigaben keine Änderung auslösen, geänderte Argumente eine neue Freigabe brauchen und Replay-/Timeout-/Neustartfälle keine automatische doppelte Änderung verursachen.

### P3 – Rate Limits, Fehler und Geschwindigkeit

Arbeiten:
- Eine gemeinsame Fehlerstruktur einführen: ungültige Eingabe, fehlende Berechtigung, abgelaufener Zugang, vorübergehende Störung, Drosselung, unbekannter Schreibausgang. Verständliche Meldung und passende nächste Aktion anzeigen.
- Startpolitik für Modellaufrufe: höchstens zwei Wiederholungen und höchstens 30 Sekunden kumulierte Wiederholungswartezeit pro interaktivem Auftrag; echte Provider-Hinweise berücksichtigen. Keine unbegrenzten verschachtelten Wiederholungen. Werte anschließend anhand der Baseline überprüfen.
- Gleichzeitige Modellanfragen pro Deployment begrenzen und Nutzer fair einreihen. Mehrere Deployments nur bei nachgewiesener unabhängiger Kapazität als Ausweichweg betrachten.
- Bestehende Verbindungspools weiterverwenden, unabhängige Leseabfragen parallelisieren und Kontext/Tool-Auswahl passend zum Agenten begrenzen.
- Metadaten mit kurzer, gezielter Gültigkeit und korrekter Nutzer-/Projekt-/Ticketzuordnung zwischenspeichern. Berechtigungen niemals aus einem fremden Cache übernehmen; Jira prüft die Änderung abschließend.
- Aktuelles `gpt-4o-2` als Vergleichsbasis behalten. `gpt-4.1` als ersten Standardkandidaten gegen `gpt-5-mini` testen. `gpt-5.2` nur als gezielten stärkeren Weg vorsehen; Claude erst nach Prüfung des passenden Providers. Keine zusätzliche Modellrunde nur zum Routing einfacher Aufträge.
- Ein Modellwechsel darf keine bereits ausgeführten Schritte wiederholen und keine offenen Freigaben verändern. Modell-/Provider-Eigenschaften zentral registrieren; Bildunterstützung nicht pauschal für jedes Deployment behaupten.

Fertig, wenn: Vergleichsbericht Erfolgsrate, p50/p95-Dauer, Tokenverbrauch, Wiederholungen und Drosselung ausweist; die gewählte Standardkonfiguration bei realistischer Last besser abschneidet als die Baseline.

### P4 – Verlässliche Skills und lange Gespräche

Arbeiten:
- Vorhandene Markdown-Skills weiter unterstützen; zusätzlich strukturierte Abläufe mit Eingaben, festen Vorgaben, Feldtypen, zulässigen Tools und erwarteten Ergebnissen anbieten.
- Skills per Auswahl, explizitem Befehl und passender natürlicher Anfrage laden. Nur bei echter Mehrdeutigkeit nachfragen. Aktiven Skill und Version pro Gespräch/Auftrag behalten, auch bei Rückfragen, Modellwechseln und Freigaben.
- Für den Testticket-Skill feste Werte unverändert übernehmen, fehlende Werte gezielt erfragen und Jira-Metadaten zur Validierung einsetzen. Vorschau und tatsächliche Ausführung gegen dieselben geprüften Werte testen.
- Kontextverdichtung des SDK prüfen und passend einsetzen; nötigenfalls einen kleinen Adapter ergänzen. Aktiver Auftrag, Skill-Version, bestätigte Werte, Dateiverweise und offene Freigaben dürfen nicht verloren gehen. Nicht unterstützte Fähigkeiten nicht als SDK-Standard voraussetzen.
- Prüfmodus für Skills: Schema-/Berechtigungsprüfung und Ausführung gegen simuliertes Jira ohne echte Änderungen.

Fertig, wenn: Der Referenz-Skill in wiederholten Modelltests seine Werte beibehält und nach Rückfragen oder längerem Gespräch korrekt fortgesetzt wird.

### P5 – Gemeinsamer Katalog und eigene Agenten

Arbeiten:
- Konfigurierbaren UC-Katalog/Schema einführen. Vorhandene SQL-Lesetools bleiben auf SELECT und freigegebene Tabellen beschränkt. Registry-Schreibzugriffe erhalten einen eigenen, eng begrenzten, parametrisierten Backend-Pfad; das LLM bekommt kein allgemeines DML-Tool.
- Veröffentlichte Skill- und Agentenversionen unveränderlich speichern; Eigentümer, Freigabestatus, erlaubte Nutzer/Gruppen, Versionsverweise und Testergebnisse erfassen. Entwürfe persönlich halten; Veröffentlichung ausdrücklich und berechtigt ausführen.
- UC-Berechtigungen und Veröffentlichungsrollen so wählen, dass normale Nutzer freigegebene Definitionen nutzen können, ohne fremde veröffentlichte Definitionen beliebig verändern zu können. Rechteprüfung nicht allein durch ausgeblendete UI-Schaltflächen ersetzen.
- Zugriff auf Definitionen mit Nutzerrechten; Cache nach Identität/Rechten und Version begrenzen. Ausfall des Katalogs klar behandeln; keine unberechtigte Ausweichidentität.
- Agentenprofil: Name, Zweck, Anweisungen, Tool-Auswahl, Skill-Versionen, Modellrichtlinie und zugelassene Datenquellen. Effektive Fähigkeiten sind die Schnittmenge aus Plattformregeln, Agentenprofil und Nutzerrechten.
- UI-Ablauf: erstellen → testen → veröffentlichen → nutzen/kopieren. Referenzen laufender Aufträge auf ihre begonnenen Versionen festhalten; Versionswechsel erst für neue Aufträge.
- Persönliche Skills aus dem bisherigen Workspace-Format verlustfrei importieren; nichts automatisch veröffentlichen oder löschen. Team-Skills aus dem Repo als erste versionierte Katalogeinträge übernehmen.
- Keine Zugangsdaten oder frei ausführbaren Python-Code als Agentenkonfiguration speichern.

Fertig, wenn: Ein berechtigter Nutzer einen Skill und einen Agenten erstellen/veröffentlichen kann, ein zweiter ihn verwenden/kopieren kann und beide weiterhin nur ihre eigenen Jira-/Datenrechte erhalten.

### P6 – Einfacher Einstieg und durchgängige Oberfläche

Arbeiten:
- Einen empfohlenen Bootstrap-Ablauf dokumentieren und automatisieren: eigene Repository-Kopie, App-Name, zentrale Ressourcen-Konfiguration, berechtigtes Setup/Deploy, Jira verbinden.
- Einmalige Einrichtung durch App-Verantwortliche und tägliche Nutzung trennen. Beim Erstellen eines weiteren Agentenprofils keine zusätzliche App oder Datenbank verlangen. Eigene Code-Forks bleiben möglich.
- Für neue Workspaces existierende Ressourcen vorausprüfen und fehlende Rechte verständlich benennen. Erforderliche Infrastruktur nicht durch viele manuelle Notebook- und YAML-Schritte verstecken.
- Status verständlich darstellen: wartet, arbeitet, benötigt Angaben, benötigt Freigabe, abgeschlossen, fehlgeschlagen, Ausgang unklar. Tooldetails bleiben eingeklappt; echte Resultate und passende Wiederaufnahme-/Korrekturaktionen bleiben sichtbar.
- Browser-Passwortmanager unterstützen; optionale Databricks-Tokenablage als Zusatzoption darstellen. Keine erneute Secret-Scope-Pflicht für normale Nutzer.
- Englischsprachigen Guide anhand des tatsächlichen neuen Ablaufs überarbeiten. Unterschiede zwischen GitHub-Stand, bereitgestellter Version und aktiver Laufzeitversion sichtbar machen.

Fertig, wenn: Eine neue Person ohne Hilfe einen eigenen Code-Fork starten kann und ein normaler Nutzer ohne Infrastruktur-Einrichtung einen veröffentlichten Agenten verwenden kann.

### P7 – Pilot und Umstellung

Arbeiten:
- Vorschau mit mindestens zwei normalen Nutzerkonten und einem dafür vorgesehenen Jira-Testprojekt abnehmen. Reale Tests erzeugen nur ausdrücklich vorgesehene Testdaten.
- Mehrfach wiederholte Standardfälle, parallele Nutzung und Fehler-/Wiederaufnahmefälle prüfen. Alle Aussagen über Live-Erfolg anhand der bereitgestellten App belegen.
- Vorläufige Leistungsziele: sichtbare UI-Rückmeldung innerhalb einer Sekunde; einfache Leseaufträge p95 unter zehn Sekunden und einfache Änderungen p95 unter zwanzig Sekunden ohne die Zeit, in der der Nutzer auf die Freigabe antwortet. Diese Ziele in P0 mit definierter Last und verfügbaren Kontingenten bestätigen oder begründet anpassen. Provider-Wartezeiten nicht aus den Nutzer-Laufzeitmessungen verstecken.
- Datenbankmigrationen zunächst rückwärtskompatibel halten. Vor Umstellung getestete Rückkehr zum vorherigen Release vorsehen; ungeklärte Schreibaktionen auch nach einem Rollback nicht automatisch wiederholen.
- Änderungen wie gewünscht nach bestandenen Checks direkt auf `main`, ohne PR. Deployment und Datenmigration separat ausführen und dokumentieren. Den alten Ausführungspfad erst nach bestandener neuer Abnahme entfernen.

Fertig, wenn: Jira-Kernfälle und Skill-Referenzfälle die Abnahme bestehen, Nutzertrennung belegt ist, Last-/Fehlerberichte vorliegen und die laufende App die freigegebene Version anzeigt.

## Voraussetzungen für die Umsetzung

- Berechtigter Databricks-Zugang für Vorschau-App, Lakebase, SQL Warehouse, UC-Objekte und erforderliche Ressourcenbindungen; Schlüssel nicht im Chat austauschen.
- Lakebase-Verfügbarkeit und zulässige Konfiguration/Kosten im Workspace prüfen. Gemeinsame Ressourcen berechtigt einmal einrichten, keine Pro-Nutzer-Provisionierung.
- Jira-Testprojekt und der echte Testticket-Skill beziehungsweise dessen nicht geheime Vorgaben.
- Modellendpunkte, API-Unterstützung und Kontingente prüfen; die Deployment-Liste allein enthält diese Angaben nicht.
- Neue Pakete und Ressourcen vor ihrer tatsächlichen Einführung konkret ausweisen. Dieses Planungsdokument installiert oder provisioniert nichts.

## Bewusst später

- Keine allgemeine Multi-Agent-Orchestrierung, kein zusätzlicher MCP-Server und kein Frameworkwechsel parallel zur Stabilisierung.
- Keine automatische Ausführung beliebiger hochgeladener Skill-Skripte.
- Keine dauerhaften Klartext-Zugangsdaten in Lakebase oder UC.
- Keine vollständige Jira-Administration, keine unbegrenzten Batch-Änderungen und keine garantierte Fehlerfreiheit bei externen Dienstausfällen.

## Quellen

- https://github.com/CariadNayon/jira-agent-template/tree/a840fe1b84ba0f24bd0f86c5168d8f5aef6e742f
- https://github.com/databricks/app-templates/tree/71f815f6a6b09b514b79105390ad73ec0e6bf220/agent-openai-advanced
- https://github.com/openai/openai-agents-python/blob/v0.20.0/docs/human_in_the_loop.md
- https://github.com/openai/openai-agents-python/blob/v0.20.0/docs/sessions/index.md

## Ergänzung v0.4.0

Umgesetzt: Deployment-bezogene Parallelitätsgrenze, begrenzte Queue, geteilter Retry-After-Cooldown, natives SDK-Retry nur des Modellaufrufs, Tests nach freigegebener Jira-Änderung und Fast-/Detailed-Auswahl. Der Queue-/Cooldown-Anteil erhält 60 Sekunden kumulatives Budget; sonstiges SDK-Backoff bleibt bei 30 Sekunden. Keine verschachtelten HTTP-Retries. `gpt-4.1-mini` folgt dem vereinbarten Fast-Standard, explizite Overrides bleiben erhalten. Die bisherige Empfehlung für den ersten Standardkandidaten oben wird dadurch ersetzt; die Live-Abnahme bleibt offen. Automatisches Routing, produktionsweite TPM-/RPM-Steuerung und Advanced-/Lakebase-/UC-Arbeiten sind weiterhin nicht abgeschlossen.
