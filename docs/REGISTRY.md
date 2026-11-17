# Gemeinsamer Skill-Katalog (Unity Catalog)

Nutzer können eigene Skills als **unveränderliche, nummerierte Versionen** in einem gemeinsamen Unity-Catalog-Schema veröffentlichen. Andere Nutzer sehen sie in der Skill-Liste (Badge „Catalog vN“) und rufen sie wie Team-Skills mit `/name` auf. Das ist Teil P5 des [Umsetzungsplans](IMPLEMENTATION_PLAN.md).

**Stand:** Der Code ist umgesetzt und mit einem simulierten Warehouse getestet. Das SQL wurde **noch nicht gegen ein echtes Warehouse ausgeführt**, und die Tabelle existiert noch nicht. Die Funktion ist deshalb standardmäßig ausgeschaltet (`registry.enabled: false`).

## Ort

`jira_agent/config.yaml`:

```yaml
registry:
  enabled: false
  catalog: ude_dev_we_cariad_t1s_sandbox
  schema: t1_jira_agent
```

Die Tabelle heißt `skill_versions`. Katalog und Schema dürfen nur Buchstaben, Ziffern und `_` enthalten; sonst bleibt die Funktion aus.

## Einmalige Einrichtung (Schema-Besitzer oder Administrator)

Zum Zeitpunkt dieser Dokumentation ist das Schema `ude_dev_we_cariad_t1s_sandbox.t1_jira_agent` leer. Schreibrechte haben dort nur ausgewählte Gruppen und Personen (zum Beispiel `CARIAD.mdb-reporter.developers`). Wer die Tabelle anlegt, braucht `CREATE TABLE` auf dem Schema.

1. Tabelle anlegen. Sie ist **append-only**: Delta lehnt `UPDATE` und `DELETE` ab, eine veröffentlichte Version bleibt also unverändert.

```sql
CREATE TABLE IF NOT EXISTS `ude_dev_we_cariad_t1s_sandbox`.`t1_jira_agent`.`skill_versions` (
  skill_name STRING NOT NULL,
  version INT NOT NULL,
  description STRING NOT NULL,
  instructions STRING NOT NULL,
  content_sha256 STRING NOT NULL,
  owner STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  status STRING NOT NULL
) TBLPROPERTIES (delta.appendOnly = true)
```

2. Rechte vergeben. Wer lesen darf, entscheidet **Unity Catalog**, nicht die Oberfläche. Gruppen anpassen:

```sql
GRANT USE CATALOG ON CATALOG `ude_dev_we_cariad_t1s_sandbox` TO `<readers>`;
GRANT USE SCHEMA ON SCHEMA `ude_dev_we_cariad_t1s_sandbox`.`t1_jira_agent` TO `<readers>`;
GRANT SELECT ON TABLE `ude_dev_we_cariad_t1s_sandbox`.`t1_jira_agent`.`skill_versions` TO `<readers>`;
GRANT MODIFY ON TABLE `ude_dev_we_cariad_t1s_sandbox`.`t1_jira_agent`.`skill_versions` TO `<publishers>`;
```

   `<readers>` sind alle Nutzer der App, `<publishers>` die Personen, die veröffentlichen dürfen. Alle brauchen außerdem **CAN USE** auf dem SQL Warehouse der App (`databricks.yml` → `warehouse_id`).

3. In `jira_agent/config.yaml` `registry.enabled: true` setzen, `project.version` erhöhen, pushen. Nach dem Deploy erscheint in Settings → Skills bei eigenen Skills der Knopf **Publish to catalog**.

## So funktioniert es

- **Rechte der Nutzer:** Lesen und Veröffentlichen laufen mit dem Workspace-Token des angemeldeten Nutzers. Die App benutzt dafür keine eigene Identität. Fehlt ein Recht, zeigt Settings → Skills eine verständliche Meldung; der Chat läuft normal weiter.
- **Scope `sql`:** Damit das Veröffentlichen (ein `INSERT`) funktioniert, braucht die App den User-Scope `sql`; mit dem früheren `sql:restricted-query` wird das Schreiben abgewiesen. Der Scope steht in `databricks.yml` (`user_api_scopes`) und muss auch in den App-Einstellungen unter Authorization → User authorization gesetzt sein, wenn die App nicht mit `uv run deploy` bzw. `databricks bundle deploy` bereitgestellt wird. Nach der Änderung müssen sich Nutzer neu anmelden und zustimmen. Chat-Abfragen bleiben durch `check_readonly_sql` auf ein einzelnes SELECT beschränkt.
- **Veröffentlichen:** Nur eigene persönliche Skills. Pro Veröffentlichung entsteht eine neue Version (1, 2, 3 …). Ein unveränderter Inhalt erzeugt keine neue Version.
- **Namen:** Der erste Veröffentlicher besitzt den Namen. Andere können dafür keine weiteren Versionen anlegen (die Prüfung steckt in derselben SQL-Anweisung wie das Einfügen). Team-Skills aus `skills/` behalten ihre Namen.
- **Vorrang:** Team-Skill vor persönlichem Skill vor Katalog-Skill mit gleichem Namen.
- **Aufruf:** Im System-Prompt stehen nur Name und Beschreibung. Die Anleitung wird erst geladen, wenn der Skill mit `/name` aufgerufen wird. Die Skill-Liste wird 5 Minuten zwischengespeichert, Fehler 30 Sekunden.
- **SQL-Sicherheit:** Nutzertexte gehen nur als Parameter ins Statement, nie als SQL-Text. Das Modell hat keinen Zugriff auf diesen Pfad und kein allgemeines DML-Tool.

## Grenzen

- **Kein Zurückziehen und kein Löschen** einzelner Versionen. Wer die Tabelle besitzt, kann sie als Ganzes entfernen. Eine Rücknahme-Funktion ist noch nicht gebaut.
- Jeder mit `MODIFY` kann per SQL direkt Zeilen anhängen und dabei Besitzer oder Nummern angeben. `MODIFY` deshalb nur an vertrauenswürdige Veröffentlicher vergeben. Inhalte veröffentlichter Skills gelten als Anweisungen für das Modell: nur prüfen und freigeben, was Nutzern zugemutet werden darf.
- Versionen eines laufenden Gesprächs werden noch nicht festgehalten; ein Aufruf nutzt jeweils die neueste Version (Plan P4).
- Agentenprofile, Freigabestatus und Gruppenlisten aus dem Plan sind noch nicht umgesetzt.

## Erste Prüfung nach der Einrichtung

1. Als Veröffentlicher einen persönlichen Skill anlegen und **Publish to catalog** klicken: Meldung „Published … as version 1“.
2. Mit einem zweiten Konto Settings → Skills öffnen: Badge „Catalog v1“, **View** zeigt die Anleitung, im Chat funktioniert `/name`.
3. Zweites Konto versucht denselben Namen zu veröffentlichen: Fehlermeldung, kein neuer Eintrag.
4. Konto ohne `SELECT`: Skills-Seite zeigt die Hinweismeldung, der Chat bleibt nutzbar.
5. Ändern und erneut veröffentlichen: Version 2; Version 1 bleibt unverändert (`SELECT * FROM … ORDER BY skill_name, version`).
