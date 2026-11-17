# Laufzeit des gesamten Agenten

Die Optimierungen liegen im gemeinsamen Unterbau, nicht in einer Sonderroute für einzelne Ticketaktionen. Sie greifen für normale Chat-Anfragen und Skills sowie für Streaming- und nicht-streamende Aufrufe.

## Was wiederverwendet wird

- Jira nutzt eine `requests.Session` pro Worker-Thread. HTTP-Verbindungen bleiben zwischen Tool-Aufrufen und Anfragen nutzbar. Zugangsdaten werden jedem einzelnen Request mitgegeben; die Session speichert keine Benutzer-Authentifizierung oder Cookies. Schreibaufrufe erhalten keine zusätzlichen automatischen Wiederholungen.
- Azure nutzt einen gemeinsamen HTTP-Verbindungspool pro Event-Loop. Jeder Lauf behält einen eigenen SDK-Client mit seinem Key; beim Abschluss wird dieser Client geschlossen. Der Pool enthält keine Standard-Authentifizierung oder Cookies. Bestehende HTTPX-Proxy- und Zertifikatseinstellungen gelten weiterhin. Der bestehende Server-Lifespan wird um das Schließen der Pools beim Herunterfahren ergänzt. Ab v0.4.0 übernimmt der vorhandene Agents SDK die Modellwiederholungen. Native Replay-Prüfungen verhindern Wiederholung nach sichtbarer Stream-Ausgabe oder einem als unsicher markierten Versuch. Der HTTP-Client deaktiviert dabei seine eigenen automatischen Versuche; es gibt keine verschachtelten Retry-Schleifen. Das SDK setzt beim fehlgeschlagenen Modellaufruf fort und behält vorherige Tool-Ergebnisse. Der Agentenlauf und Jira-Schreibaufrufe werden nicht neu gestartet. Höchstens zwei Wiederholungen pro Modellaufruf (`llm.max_retries`). Bekannte positive 429-Wartezeiten werden durch den unten beschriebenen gemeinsamen Cooldown erfüllt. Für sonstige vom Provider als vorübergehend eingestufte Fehler oder fehlendes Retry-After bleibt das vorhandene SDK-Backoff mit kumulativ 30 Sekunden (`llm.retry_wait_seconds`) erhalten. Dauerhafte Fehler, ausgeschöpftes Kontingent und ein ausdrückliches `x-should-retry: false` werden nicht wiederholt. HTTP-Timeout pro Versuch: `llm.timeout_seconds` (60 Sekunden). Queue-/Backoff-Budgets sind keine Gesamtlaufzeitlimits; Netzwerk-/Toolzeit und Streaming kommen hinzu. Die kleinen Adapter verwenden SDK-Hooks, deren Kompatibilität mit dem installierten SDK getestet wird.
- Tool-Module werden einmal pro Prozess entdeckt. Neue Tools benötigen wie andere Codeänderungen einen App-Neustart/Deploy. Die tatsächliche Auswahl wird weiterhin pro Anfrage nach Konfiguration und verfügbaren Ressourcen geprüft.
- Der Databricks-Client für Datenabfragen wird nur aufgebaut, wenn Tabellen freigegeben sind. Das erstmalige Laden persönlicher Einstellungen und Skills nutzt weiterhin die jeweiligen Nutzerrechte.
- Team-Skills werden anhand von Dateipfad, Änderungszeit und Größe zwischengespeichert. Änderungen werden beim nächsten Zugriff erkannt; Aufrufer erhalten eigene Kopien. Persönliche Einstellungen und Skills behalten ihre bisherige benutzerbezogene Ablage.

Es werden keine Jira-Tickets, Feldberechtigungen oder SQL-Ergebnisse zwischengespeichert. Alte Werte werden dadurch nicht als aktuelle Ergebnisse ausgegeben.

Die Azure-Factory markiert ihre eigenen SDK-Clients mit `_jira_agent_client`. Nur diese werden vom gemeinsamen Laufzeit-Kontext geschlossen. Eigene Provider mit selbst verwalteten oder geteilten Clients behalten die Verantwortung für deren Lebensdauer.

## Deployment-Auswahl und gemeinsame Lastgrenzen (v0.4.0)

Der Template-Standard ist `gpt-4.1-mini`. Settings → Model → **Fast (template default)** leert den persönlichen Deployment-Override; **Save** aktiviert die Auswahl ab der nächsten Nachricht. Ein leerer Override folgt auch nach erneutem Öffnen der Einstellungen dem Template. Bestehende ausdrückliche Auswahlen wie `gpt-4o-2` werden nicht überschrieben. **Detailed** setzt den konfigurierten Preset `gpt-4.1`. Beide Deployments müssen im verwendeten Azure-Endpunkt existieren. Das ist eine manuelle Auswahl; automatisches Routing nach Aufgabenkomplexität und ein Live-Qualitäts-/Geschwindigkeitsvergleich sind weiterhin offen.

Ab v0.5.0 wählt man das Deployment in einem Dropdown. Die Liste steht zentral unter `llm.deployments` in `jira_agent/config.yaml` und wird beim Kopieren des Templates an die eigene Azure-Ressource angepasst. Sie enthält die genannten OpenAI-Chat-Deployments; Embedding-Modelle sind keine Chat-Modelle, Claude benötigt einen passenden Provider. Die Liste wird nicht aus Azure abgefragt und bestätigt keine Zugriffsrechte, API-Kompatibilität oder Kapazität. Nicht gelistete bestehende Namen bleiben unter **Custom deployment** erhalten und bearbeitbar. Fast übernimmt weiterhin den Template-Standard; eine konkrete Modelloption speichert einen persönlichen Override.

Pro Endpunkt und Deployment ist standardmäßig eine Modellantwort gleichzeitig aktiv (`llm.max_inflight: 1`). Der Platz bleibt bis zum Ende der Antwort, auch beim Streaming, belegt. Bis zu acht weitere Aufrufe warten (`llm.max_pending: 8`); Überlast wird begrenzt abgewiesen. Alle Modellrunden desselben Benutzerturns teilen ein Wartebudget von 60 Sekunden für Queue und bekannten Azure-Cooldown (`llm.queue_wait_seconds`). Nach einer 429 gilt Retry-After für alle Nutzer dieses Deployments. Der nächste Aufruf wartet vor dem Senden; reicht sein verbleibendes Budget nicht, wird nicht vorzeitig erneut gesendet. Ein Retry-After von 32 Sekunden kann damit innerhalb desselben Laufs überbrückt werden. Wiederholte Drosselung bleibt begrenzt und kann weiterhin als Fehler enden.

Die Steuerung gilt im App-Worker und dessen Event-Loop. Andere Apps oder Instanzen, gemeinsame Kontingente mehrerer Deployments und deren Verbraucher werden dadurch nicht koordiniert. Eine Parallelitätsgrenze ist keine genaue TPM-/RPM-Steuerung. Es werden keine zusätzlichen Azure-Kapazitäten provisioniert und keine Quoten erhöht. Mini hat nicht automatisch mehr freie Kapazität. Die App bleibt bei einem Worker. Nur Deployment-Kennungen und Zeit-/Kapazitätswerte werden geteilt; Nutzer, Keys, Prompts und Tool-Ergebnisse bleiben getrennt.

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
| `azure_retry_waits`, `azure_retry_wait_ms`, `azure_retry_budget_exhausted` | Backoff-Vorgänge, tatsächlich gewartete Zeit und abgewiesene weitere Wartezeiten |
| `model_queue_entries`, `model_queue_timeouts`, `model_queue_wait_ms` | Queue-/Cooldown-Eintritte, abgewiesene Wartezeiten/Überlast und tatsächlich gewartete Zeit |
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

## Modell-429 nach erfolgreichen Jira-Leseaufrufen

Ein Ablauf wie `jira_get_issue` → `jira_list_issue_types` → `jira_get_create_fields` benötigt anschließend eine weitere Modellantwort. Eine 429 außerhalb der Tool-Ergebnisse deutet auf die Modell-/AI-Service-Seite hin; abgeschlossene Leseaufrufe belegen keine Ticketerstellung. Die Ursache und das aktive Kontingent müssen mit den App-/Azure-Messwerten geprüft werden.

Ab v0.3.1 erklärt der Modellclient eine endgültige 429 ohne rohe Anbieterantwort. Ein vorhandener `Retry-After` wird als Wartehinweis übernommen. Meldet der Anbieter ausdrücklich `insufficient_quota` oder `billing_hard_limit_reached`, verlangt die Meldung eine Prüfung des Kontingents statt eines bloßen Wartens. Der Fehler sagt nichts darüber aus, ob zuvor im Auftrag eine Jira-Änderung erfolgte.

Die Oberfläche erklärt auch knappe ältere Meldungen wie `Error code: 429` und weist nur bedingt auf Jira hin: Wer bereits eine Änderung freigegeben hat, soll deren Ergebnis vor einer Wiederholung prüfen. Der Agent wird weiterhin weder nach Dienstfehlern noch nach leeren/abgebrochenen Streams automatisch neu gestartet. Bereits übertragene Ergebnisse bleiben erhalten; eine leere Anzeige gilt nicht als Nachweis, dass keine Änderung erfolgt ist.

Für die Ursachenprüfung erfassen: Zeitpunkt, App-Version, tatsächliches Deployment aus Settings → Model, `azure_http_status_429`, `azure_retry_budget_exhausted`, vorhandenes Retry-After und die zugeteilten TPM-/RPM-Grenzen. Keine Tokens oder Schlüssel weitergeben. Mehr Wiederholungen erhöhen kein Kontingent; ein anderes Deployment hilft nur mit tatsächlich verfügbarer Kapazität. Ein Modellwechsel oder eine Kürzung des Kontexts wird nicht ohne Prüfung als Fehlerbehebung ausgegeben.

Ab v0.4.0 prüfen echte SDK-Läufe mit synthetischem HTTP-Transport außerdem: getrennte Nutzer-Keys bei gemeinsamer Lastgrenze, unabhängige Deployments, geteiltes Retry-After, kumulatives Queue-Budget, volle Warteschlange, Abbruch wartender/laufender Aufrufe und die Belegung bis zum Stream-Ende. Ein Retry-After von 32 Sekunden nach einer tatsächlich über den Freigabeadapter ausgeführten Fake-Jira-Ticketerstellung wird mit virtueller Zeit getestet: gleicher Modellrequest wird wiederholt, genau ein Jira-POST, keine doppelten HTTP-Retries. Der Test läuft mit und ohne Streaming. Das ist keine Messung des Live-Modells.
