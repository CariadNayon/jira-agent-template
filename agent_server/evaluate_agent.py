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
    args=parser.parse_args()
    if args.list:
        for name,description in CASES.items():print(f'{name}: {description}')
        return
    if not args.live:
        if args.cases:parser.error('--case ist für den optionalen --live-Modelltest vorgesehen.')
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
        load_dotenv(ROOT/'.env')
        print('Echtes Modell: Dieser Lauf verursacht Modellaufrufe. Jira und Dateien sind synthetische Testdaten.')
        try:
            model=await asyncio.wait_for(asyncio.to_thread(build_model,CFG['llm']['provider'],
                                         CFG['llm'],dict(DEFAULT_SETTINGS),{}),timeout=30)
        except Exception as exc:
            report={'mode':'live-model-fake-services','passed':False,'blocked':True,
                    'reason':f'Modell-Konfiguration nicht verfügbar ({type(exc).__name__}). Azure-Key/Databricks-Anmeldung prüfen.'}
            return report,2
        try:
            results=[await run_case(name,model) for name in (args.cases or list(CASES))]
        finally:
            client=getattr(model,'_client',None)
            if client is not None:await client.close()
        passed=all(r['passed'] for r in results)
        return {'mode':'live-model-fake-services','passed':passed,'cases':results,
                'note':'Keine Abnahme echter Jira-/SQL-Rechte oder der Browser-Anmeldung.'},0 if passed else 1
    report,status=asyncio.run(live())
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if args.json_report:
        args.json_report.parent.mkdir(parents=True,exist_ok=True)
        args.json_report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    raise SystemExit(status)


if __name__=='__main__':evaluate()
