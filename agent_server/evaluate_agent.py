"""Realistic acceptance: offline by default; opt-in real model calls with fake Jira/files."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent


def evaluate():
    from agent_server.evaluation import CASES
    parser=argparse.ArgumentParser(description='Jira-/Datei-Abnahme. Standard: offline ohne echte Dienste.')
    parser.add_argument('--list',action='store_true',help='Optionale Modell-Abnahmefälle anzeigen')
    parser.add_argument('--live',action='store_true',help='Echtes konfiguriertes Azure-Modell verwenden; Jira bleibt simuliert')
    parser.add_argument('--case',action='append',choices=sorted(CASES),dest='cases')
    parser.add_argument('--json-report',type=Path,help='Strukturierten Bericht speichern')
    parser.add_argument('--deployment', action='append', dest='deployments', help='Azure-Deployment für den Modellvergleich (wiederholbar)')
    parser.add_argument('--repeat', type=int, default=1, help='Wiederholungen pro Fall und Deployment, 1–20')
    args=parser.parse_args()
    if not 1 <= args.repeat <= 20: parser.error('--repeat muss zwischen 1 und 20 liegen.')
    if args.list:
        for name,description in CASES.items():print(f'{name}: {description}')
        return
    if not args.live:
        if args.cases:parser.error('--case ist für den optionalen --live-Modelltest vorgesehen.')
        if args.deployments or args.repeat != 1:parser.error('Modellvergleich benötigt --live; für wiederholte Offline-Prüfungen stability-check verwenden.')
        command=[sys.executable,'-m','pytest',str(ROOT/'tests/acceptance'),'-q']
        result=subprocess.run(command,cwd=ROOT)
        if args.json_report:
            args.json_report.parent.mkdir(parents=True,exist_ok=True)
            args.json_report.write_text(json.dumps({'mode':'offline-simulated','passed':result.returncode==0,
                                                     'note':'Keine Bewertung eines echten Modells.'},indent=2))
        raise SystemExit(result.returncode)
    async def live():
        from dotenv import load_dotenv
        from jira_agent import CFG
        from jira_agent.llm import build_model
        from jira_agent.runtime import DEFAULT_SETTINGS
        from agent_server.evaluation import run_case
        from agent_server.stability import percentile
        from jira_agent.connections import azure_connection_scope, close_connections
        load_dotenv(ROOT/'.env')
        print('Echtes Modell: Dieser Lauf verursacht Modellaufrufe. Jira und Dateien sind synthetische Testdaten.')
        results=[]; blocked=[]
        deployments=args.deployments or [CFG['llm']['deployment']]
        for deployment in deployments:
            try:
                model=await asyncio.wait_for(asyncio.to_thread(build_model,CFG['llm']['provider'],
                                             CFG['llm'],{**DEFAULT_SETTINGS, 'azure_deployment': deployment},{}),timeout=30)
            except Exception as exc:
                blocked.append({'deployment': deployment, 'reason':f'Modell-Konfiguration nicht verfügbar ({type(exc).__name__}). Azure-Key/Databricks-Anmeldung prüfen.'})
                continue
            try:
                for iteration in range(args.repeat):
                    for name in (args.cases or list(CASES)):
                        factory=lambda: build_model(CFG['llm']['provider'], CFG['llm'],
                                                    {**DEFAULT_SETTINGS, 'azure_deployment': deployment}, {})
                        with azure_connection_scope():
                            result=await run_case(name,model,model_factory=factory)
                        result.update({'deployment': deployment, 'iteration': iteration+1})
                        results.append(result)
            finally:
                client=getattr(model,'_jira_agent_client',None) or getattr(model,'_client',None)
                if client is not None:await client.close()
                await close_connections()
        passed=not blocked and bool(results) and all(r['passed'] for r in results)
        summary={deployment:{'runs':len(group), 'passed':sum(r['passed'] for r in group),
                            'p50_seconds':percentile([r['seconds'] for r in group],0.5),
                            'p95_seconds':percentile([r['seconds'] for r in group],0.95)}
                 for deployment in deployments if (group:=[r for r in results if r['deployment']==deployment])}
        return {'mode':'live-model-fake-services','passed':passed,'cases':results,'summary':summary,
                'blocked':blocked,'note':'Keine Abnahme echter Jira-/SQL-Rechte oder der Browser-Anmeldung.'},2 if blocked else 0 if passed else 1
    report,status=asyncio.run(live())
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if args.json_report:
        args.json_report.parent.mkdir(parents=True,exist_ok=True)
        args.json_report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    raise SystemExit(status)


if __name__=='__main__':evaluate()
