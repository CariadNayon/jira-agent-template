# Laufzeit des gesamten Agenten

Die Optimierungen liegen im gemeinsamen Unterbau, nicht in einer Sonderroute für einzelne Ticketaktionen. Sie greifen für normale Chat-Anfragen und Skills sowie für Streaming- und nicht-streamende Aufrufe.

## Was wiederverwendet wird

- Jira nutzt eine `requests.Session` pro Worker-Thread. HTTP-Verbindungen bleiben zwischen Tool-Aufrufen und Anfragen nutzbar. Zugangsdaten werden jedem einzelnen Request mitgegeben; die Session speichert keine Benutzer-Authentifizierung oder Cookies. Schreibaufrufe erhalten keine zusätzlichen automatischen Wiederholungen.
- Azure nutzt einen gemeinsamen HTTP-Verbindungspool pro Event-Loop. Jeder Lauf behält einen eigenen SDK-Client mit seinem Key; beim Abschluss wird dieser Client geschlossen. Der Pool enthält keine Standard-Authentifizierung oder Cookies. Bestehende HTTPX-Proxy- und Zertifikatseinstellungen gelten weiterhin. Der bestehende Server-Lifespan wird um das Schließen der Pools beim Herunterfahren ergänzt.
- Tool-Module werden einmal pro Prozess entdeckt. Neue Tools benötigen wie andere Codeänderungen einen App-Neustart/Deploy. Die tatsächliche Auswahl wird weiterhin pro Anfrage nach Konfiguration und verfügbaren Ressourcen geprüft.
- Der Databricks-Client für Datenabfragen wird nur aufgebaut, wenn Tabellen freigegeben sind. Das erstmalige Laden persönlicher Einstellungen und Skills nutzt weiterhin die jeweiligen Nutzerrechte.
- Team-Skills werden anhand von Dateipfad, Änderungszeit und Größe zwischengespeichert. Änderungen werden beim nächsten Zugriff erkannt; Aufrufer erhalten eigene Kopien. Persönliche Einstellungen und Skills behalten ihre bisherige benutzerbezogene Ablage.

Es werden keine Jira-Tickets, Feldberechtigungen oder SQL-Ergebnisse zwischengespeichert. Alte Werte werden dadurch nicht als aktuelle Ergebnisse ausgegeben.

Die Azure-Factory markiert ihre eigenen SDK-Clients mit `_jira_agent_client`. Nur diese werden vom gemeinsamen Laufzeit-Kontext geschlossen. Eigene Provider mit selbst verwalteten oder geteilten Clients behalten die Verantwortung für deren Lebensdauer.

## Weniger Modellkontext und unnötige Modellrunden

Der System-Prompt besteht aus einem gemeinsamen Kern und Fachanweisungen für die tatsächlich verfügbaren Tools. Ohne hochgeladene Dateien entfallen die ausführlichen PDF-/Tabellen-Anweisungen; ohne SQL-Tools entfällt die SQL-Anleitung. Berechtigungen, Bestätigungen, der Schutz vor Anweisungen in Dateien/Tickets und ehrliche Fehlermeldungen bleiben im gemeinsamen Kern.

Die Regeln empfehlen für alle Abläufe die kleinste notwendige Menge an Aufrufen, die Wiederverwendung bereits geprüfter Informationen und gemeinsame Aufrufe unabhängiger lesender Tools. Metadaten werden passend zur tatsächlichen Aktion geladen. Das sind Modell-Anweisungen; sie garantieren keine feste Anzahl an Modellrunden. Die Messwerte zeigen, welche Abläufe weiter verbessert werden müssen.

Bei Einführung sank der feste Anweisungstext für reine Jira-Anfragen von 5.619 auf 3.413 Zeichen (rund 39 %). Diese Zahl bezieht sich auf den festen Text, nicht auf den gesamten Request: Nutzereinstellungen, Skills, Tool-Schemata, Verlauf und Bilder kommen hinzu. Die tatsächlichen Tokens werden pro Lauf gemessen.

Der Chatverlauf wird nicht still abgeschnitten oder zusammengefasst. Eine spätere Kontextverdichtung muss Dateireferenzen, laufende Bestätigungen und Tool-Aufruf-/Ergebnis-Paare erhalten.

## Engpässe nach dem Deployment messen

Jeder Agentenlauf schreibt eine JSON-Zeile mit `event: agent_performance` in die App-Logs. `request_id` ist eine zufällige Kennung des Laufs; im zugehörigen MLflow-Trace steht sie unter `performance.request_id`. Die neue Laufzeitzeile enthält nur technische Zähler und Zeiten, keine Prompts, Argumente, Ticket-Keys, Nutzerkennungen oder Zugangsdaten. Bestehende MLflow-Traces können weiterhin Chat- und Tool-Inhalte enthalten.

| Feld | Bedeutung |
|---|---|
| `total_ms`, `outcome` | Gesamtdauer des Backend-Laufs; completed, error oder cancelled |
| `prepare_ms` | Aufbau von Kontext, Tools, Modell und Einstellungen |
| `llm_calls`, `llm_ms` | Anzahl logischer Modellrunden und aufsummierte Wartezeit bis zu deren Abschluss |
| `input_tokens`, `output_tokens`, `cached_input_tokens` | Vom SDK gemeldete Tokens über alle Modellrunden; Cache-Treffer hängen von Azure ab |
| `azure_http_calls`, `azure_http_ms` | HTTP-Versuche des SDK und deren Dauer; bei Streaming endet diese Dauer beim Erhalt der Header, nicht beim letzten Token |
| `azure_http_status_429` usw. | HTTP-Statuszähler; wiederholte 429 weisen auf Drosselung hin |
| `jira_calls`, `jira_ms`, `jira_status_200` usw. | Jira-HTTP-Aufrufe, Dauer und Statuszähler |
| `tool_calls`, `tool_ms` | Tool-Aufrufe inklusive Vorschau und Rückgaben sowie ihre Laufzeit |
| `tool_<name>_calls`, `tool_<name>_ms` | Anzahl und Zeit pro registriertem Tool, auch für SQL, Dateien und eigene Integrationen |
| `first_event_ms`, `first_text_ms` | Beim Streaming: Zeit bis zum ersten Backend-Ereignis bzw. ersten Text-Delta; keine Messung der Browserdarstellung |
| `input_items`, `instruction_chars`, `available_tools` | Größe des Verlaufs, Anweisungstext und Anzahl angebotener Tools |

Nicht angefallene Zähler können fehlen. Tool-Zeiten enthalten Jira-Zeiten; Modellzeiten enthalten HTTP-Wartezeit und gegebenenfalls SDK-Backoff. Parallele Zeiten können sich überlappen. Die Spalten deshalb nicht zur Gesamtdauer addieren. Bei Abbruch sind Messungen unvollständig; eine bereits laufende blockierende Jira-Anfrage kann noch enden. Ihr Ausgang muss vor einer Wiederholung geprüft werden.

Zur Auswertung mehrere vergleichbare Anfragen betrachten, einschließlich des ersten Aufrufs nach dem Start und aufgewärmter Folgeaufrufe. Viele `llm_calls` sprechen für unnötige Zwischenschritte, viele Tokens für großen Kontext. Hohe Jira-Zeiten zeigen externe Wartezeit. Mehr Azure-HTTP-Versuche als Modellrunden können auf SDK-Wiederholungen hinweisen; Statuszähler helfen beim Einordnen. Bei langen Modellzeiten trotz weniger Aufrufe Azure-Auslastung, Deployment und Antwortlänge im Trace prüfen. Einstellungen wie Modell und Berechtigungen dabei gleich lassen, damit Vergleiche aussagekräftig bleiben.

## Was lokal geprüft wird

```bash
uv run pytest tests -q
```

Die Tests verwenden einen lokalen HTTP/1.1-Server und das echte OpenAI SDK: Wiederverwendung derselben TCP-Verbindung, getrennte Authentifizierungs-Header, unterdrückte Cookies, Event-Loop-Grenzen und sichtbare HTTP-429-Wiederholungen. Weitere Tests prüfen Modell-/Tool-Zähler einschließlich Streaming, Tokenmessung, Fehler-/Abbruchpfade, bestehende Server-Lifespans, Skill-Cache und die Fachanweisungen.

Das belegt keine bestimmte Live-Beschleunigung. Erst die Messungen in der bereitgestellten App zeigen die tatsächlichen Azure-, Jira- und Netzwerklaufzeiten. Es wird kein zusätzlicher Dienst und kein neues Paket benötigt.
