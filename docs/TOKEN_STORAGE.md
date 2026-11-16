# Jira-Token pro Nutzer merken

Die Option **Remember for my account** speichert den Jira-Token verschlüsselt im persönlichen Databricks-Workspace-Ordner. Sie gilt für das Databricks-Konto und funktioniert damit auch nach einem App-Neustart und auf einem anderen Browser. Es werden keine Tokens in Local Storage, IndexedDB, Browser-Cache oder Cookies abgelegt.

## Einmalige Einrichtung durch den App-Verantwortlichen

Ein eigener Verschlüsselungsschlüssel ist erforderlich. Ohne ihn bleibt die Funktion deaktiviert und die bisherige Sitzungsablage funktioniert weiter. Der Azure-OpenAI-Key wird nicht als Verschlüsselungsschlüssel verwendet.

Neben der gesperrten Checkbox zeigt die App, ob das Verschlüsselungs-Secret fehlt, ungültig ist oder die Benutzeranmeldung erneuert werden muss. **Setup help** öffnet direkt den passenden Abschnitt der Anleitung. Ein Code-Update allein legt das Secret nicht an und aktiviert die Funktion nicht.

1. Einen eingeschränkten Secret Scope verwenden, standardmäßig `jira-agent-credentials`, und darin einen **separaten** Eintrag `jira-agent-token-encryption-key` anlegen. Er muss einen von `cryptography.fernet.Fernet.generate_key()` erzeugten Schlüssel enthalten. Die Bibliothek ist bereits über MLflow installiert; es kommt kein neues Paket hinzu. Schlüsselwerte weder ins Repo noch in Chat, Logs oder Terminalausgaben schreiben. Beispiel für einen Databricks-verwalteten Scope, ausgeführt durch einen berechtigten Administrator:

   ```python
   from cryptography.fernet import Fernet
   from databricks.sdk import WorkspaceClient
   from jira_agent import BUNDLE

   w = WorkspaceClient()  # lokale Anmeldung des Administrators
   scope = BUNDLE['token_encryption_secret_scope']
   key_name = BUNDLE['token_encryption_secret_key']
   if not any(item.name == scope for item in w.secrets.list_scopes()):
       w.secrets.create_scope(scope=scope)
   if any(item.key == key_name for item in w.secrets.list_secrets(scope=scope)):
       raise RuntimeError('Secret already exists. Do not overwrite the encryption key.')
   w.secrets.put_secret(scope=scope, key=key_name, string_value=Fernet.generate_key().decode('ascii'))
   ```

   Bei einem Key-Vault-gestützten Scope muss der Eintrag im zugehörigen Vault angelegt werden. Den Schlüssel stabil halten und nach den Team-Vorgaben sichern: geht er verloren oder wird er ersetzt, können vorhandene Token-Dateien nicht mehr entschlüsselt werden. Nutzer müssen ihren Jira-Token dann neu verbinden. Zugriff auf den Scope nur für App-Service-Principal und berechtigte Administratoren vergeben.

2. In `databricks.yml` die beiden vorbereiteten optionalen Blöcke aktivieren: die Secret-Ressource **jira-token-key** mit READ und die Umgebungsvariable **JIRA_TOKEN_ENCRYPTION_KEY** mit `value_from: jira-token-key`. Scope und Key-Name stehen unter `variables.token_encryption_secret_scope` und `variables.token_encryption_secret_key`. Nur Referenzen ins Bundle schreiben, niemals den Schlüsselwert. Die Bindung kann auch im Databricks-App-UI eingerichtet werden; für wiederholbare Deployments muss sie ebenfalls im Bundle stehen.

3. Die App neu deployen. User Authorization benötigt weiterhin den bestehenden Scope `workspace.workspace`. Er erlaubt den Zugriff auf den persönlichen Workspace-Ordner mit den Rechten des angemeldeten Nutzers.

4. In der App den Jira-Token eingeben und **Remember for my account** auswählen. Die App prüft zuerst den Jira-Zugang. Erst danach wird die verschlüsselte Kopie gespeichert. In Settings → Connections wird angezeigt, ob der Token gemerkt wurde.

## Ablage und Wiederherstellung

- Datei: `/Users/<email>/.jira-agent/credentials/<app-und-jira-hash>.enc`.
- Die Datei enthält ausschließlich einen mit Fernet authentifiziert verschlüsselten Datensatz. Nutzer, App-Name, Jira-Adresse und Ablaufzeit sind Teil des geschützten Inhalts. Eine kopierte Datei eines anderen Nutzers, einer anderen App oder Jira-Instanz wird nicht verwendet.
- Lesen, Schreiben und Löschen erfolgen mit dem weitergeleiteten Databricks-Nutzertoken, nicht mit den Workspace-Rechten des App-Service-Principals. Der Service Principal erhält nur den für den Betrieb notwendigen Zugriff auf das separate App-Secret.
- Beim Wiederherstellen prüft die App Besitzer, App/Jira-Bindung und Ablaufdatum. Anschließend validiert sie den Jira-Token mit `/myself`. Erst dann wird er als aktive Sitzung verwendet. Der Browser erhält nur Statusinformationen, niemals den gespeicherten Token oder die verschlüsselte Datei.
- Die automatische Wiederverbindung gilt standardmäßig für 30 Tage ab dem Speichern (`session.remember_jira_days`, 1–365). Eine frühere Sperrung oder Ablaufzeit des Tokens in Jira gilt weiterhin. Nach Ablauf wird die gespeicherte Kopie nicht mehr benutzt; sie kann über **Disconnect and forget saved token** gelöscht oder beim erneuten Verbinden ersetzt werden.
- Die unverschlüsselte Arbeitskopie bleibt wie bisher im Arbeitsspeicher einer Sitzung. Sitzungen laufen nach 8 Stunden ab; danach kann ein noch gültiger gemerkter Token beim nächsten authentifizierten Aufruf erneut geladen werden. Bestätigungscodes und Aktionsbelege bleiben flüchtig und werden nicht mit dem Token gespeichert.
- Wiederherstellung und manuelles Verbinden sind pro Sitzung synchronisiert. Fehlende Dateien werden einmal geprüft; vorübergehende Dienstfehler erhalten eine kurze Wiederholungspause. So wird nicht bei jeder Modellrunde erneut auf die Ablage zugegriffen.

## Vergessen und Fehlerfälle

**Disconnect and forget saved token** löscht die verschlüsselte Datei und leert die Sitzungsschlüssel. Es widerruft den Jira-Token nicht in Jira. Dafür muss der Nutzer ihn zusätzlich in Jira widerrufen.

Scheitert das Löschen, meldet die App den Fehler und bleibt verbunden; sie behauptet nicht, der Token sei vergessen worden. Scheitert das Speichern, wird die neue Verbindung nicht als erfolgreich gemerkt angezeigt. Ein neu verbundener Token ohne Remember entfernt eine zuvor gespeicherte Kopie, wenn die Erinnerungsfunktion verfügbar ist.

Falsche Schlüssel, manipulierte oder abgelaufene Dateien und von Jira zurückgewiesene Tokens werden nicht aktiviert. Der Nutzer kann einen neuen Token eingeben oder die alte Kopie vergessen. Persönliche Einstellungen in `settings.json` bleiben frei von Zugangsdaten. Eigene Azure-Keys werden weiterhin nur im Arbeitsspeicher gehalten.

## Prüfen

```bash
uv run pytest tests -q
```

Die Tests prüfen Verschlüsselung, Nutzer-/App-/Jira-Bindung, Wiederherstellung nach Verlust des Arbeitsspeichers, Ablehnung ungültiger Tokens, Fehlerfälle, parallele Zugriffe und das explizite Vergessen. Die echten Workspace-Berechtigungen und die Secret-Bindung müssen nach Einrichtung im Ziel-Workspace geprüft werden.
