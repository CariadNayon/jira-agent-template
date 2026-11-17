"""Named offline stability scenarios and repeatable JUnit-based reports. No paid model or Jira calls."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
# Each scenario names the executable assertions that establish its result.
SCENARIOS = {
    'reference_skill': ('Supplied demo skill through SDK, approval and replay', 'tests/acceptance/test_reference_skill.py'),
    'ticket_search': ('My open issues with project and pagination', 'tests/test_ticket_search.py::test_my_open_tickets_keep_project_and_pagination_without_identity_lookup'),
    'ticket_example': ('An example search does not invent an assignee restriction', 'tests/test_ticket_search.py::test_example_ticket_does_not_silently_filter_to_current_user'),
    'create_assign_read': ('Discover fields, create, assign and read back', 'tests/test_jira_workflows.py::test_discover_create_assign_and_read_back_ticket'),
    'edit_workflow': ('Update, status, links and worklog preserve untouched fields', 'tests/test_jira_workflows.py::test_existing_issue_workflow_preserves_unspecified_fields'),
    'custom_fields': ('Required fields and bounded metadata values', 'tests/test_jira_workflows.py::test_metadata_pagination_required_custom_fields_and_option_bounds'),
    'transition_fields': ('Workflow transition requirements', 'tests/test_jira_workflows.py::test_transition_fields_are_discovered_and_passed_without_guessing'),
    'invalid_input': ('Invalid mutations make no remote changes', 'tests/test_jira_workflows.py::test_invalid_actions_do_not_write'),
    'approval_integrity': ('Changed arguments and other users cannot reuse approval', 'tests/test_jira_workflows.py::test_all_new_writes_require_explicit_unchanged_user_approval'),
    'approval_expiry': ('Expired approval, other chat and other user', 'tests/test_single_use_actions.py::test_approval_expires_and_cannot_be_reused_for_another_chat_or_user'),
    'approval_parallel': ('Concurrent retries execute one mutation', 'tests/test_single_use_actions.py::test_concurrent_retries_cannot_pass_the_same_approval'),
    'rejected_write': ('Jira 4xx errors allow a new explicitly approved correction', 'tests/test_stability_failures.py::test_rejected_write_does_not_lock_out_a_new_explicit_attempt'),
    'uncertain_write': ('Timeout/5xx after mutation cannot be blindly repeated', 'tests/test_stability_failures.py::test_ambiguous_mutation_is_not_reissued'),
    'partial_write': ('Later validation cannot conceal an earlier mutation', 'tests/test_stability_failures.py::test_a_later_validation_error_cannot_hide_an_already_applied_change'),
    'model_wait_limit': ('Long Retry-After does not cause an unbounded wait', 'tests/test_model_retry_budget.py::test_long_retry_after_fails_promptly_instead_of_sleeping_or_retrying'),
    'model_retry_budget': ('The wait budget spans model rounds', 'tests/test_model_retry_budget.py::test_wait_budget_is_shared_across_model_rounds_in_one_run'),
    'model_permanent_error': ('400/401/403 are not retried', 'tests/test_model_retry_budget.py::test_permanent_model_errors_are_not_retried'),
    'model_retry_count': ('Persistent 429 has a bounded number of attempts', 'tests/test_model_retry_budget.py::test_retry_count_is_bounded_when_a_service_keeps_throttling'),
    'skill_continuity': ('Explicit skills survive approval and stay in the right chat', 'tests/test_skill_continuity.py'),
    'image_inputs': ('Native image payload through both agent endpoints', 'tests/test_image_inputs.py::test_real_sdk_sends_image_to_azure_for_both_agent_paths'),
    'file_isolation': ('Expired and other-user images are not forwarded', 'tests/test_image_inputs.py::test_expiry_and_wrong_owner_never_send_image_bytes'),
    'pdf_inputs': ('Rendered PDF reaches model without leaking image bytes into public history', 'tests/test_pdf_vision.py::test_actual_sdk_delivers_rendered_pages_to_model_but_not_browser_history'),
    'table_aggregation': ('Calculate over every uploaded table row', 'tests/test_table_analysis.py::test_aggregates_all_rows_not_preview'),
    'export_pagination': ('Export all 150 issues beyond the first page', 'tests/acceptance/test_export_journey.py::test_export_150_tickets_is_complete_not_first_100'),
    'stream_failure': ('Keep transmitted chunks without starting a second agent run', 'tests/test_frontend_safety.py::test_stream_reader_preserves_chunks_without_replay'),
    'user_identity': ('Preserve trusted forwarded identity', 'tests/test_frontend_identity.py::test_forwarded_identity_is_header_only'),
}


def report_cases(root: ET.Element, target: str) -> list[dict]:
    path, _, function = target.partition('::')
    module = path.removesuffix('.py').replace('/', '.')
    result = []
    for case in root.iter('testcase'):
        name, classname = case.get('name', ''), case.get('classname', '')
        if classname != module or function and name.split('[', 1)[0] != function:
            continue
        status = next((tag for tag in ('failure', 'error', 'skipped') if case.find(tag) is not None), 'passed')
        result.append({'test': classname + '::' + name, 'status': status, 'seconds': float(case.get('time', 0))})
    return result


def percentile(values, fraction):
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 3) if values else None


def main():
    from jira_agent import __version__
    p = argparse.ArgumentParser(description='Run the named offline stability scenarios; no external services.')
    p.add_argument('--list', action='store_true')
    p.add_argument('--case', action='append', choices=sorted(SCENARIOS), dest='cases')
    p.add_argument('--repeat', type=int, default=1)
    p.add_argument('--json-report', type=Path, default=ROOT / 'work/stability-report.json')
    args = p.parse_args()
    if not 1 <= args.repeat <= 20:
        p.error('--repeat must be between 1 and 20.')
    if args.list:
        for name, (description, _) in SCENARIOS.items():
            print(f'{name}: {description}')
        return
    selected = args.cases or list(SCENARIOS)
    runs = []
    exit_codes = []
    with tempfile.TemporaryDirectory(prefix='jira-stability-') as tmp:
        for iteration in range(args.repeat):
            xml = Path(tmp) / f'results-{iteration}.xml'
            command = [sys.executable, '-m', 'pytest', '-q', *dict.fromkeys(SCENARIOS[name][1] for name in selected),
                       f'--junitxml={xml}']
            completed = subprocess.run(command, cwd=ROOT)
            exit_codes.append(completed.returncode)
            root = ET.parse(xml).getroot() if xml.exists() else ET.Element('testsuites')
            for name in selected:
                tests = report_cases(root, SCENARIOS[name][1])
                runs.append({'case': name, 'iteration': iteration + 1, 'passed': bool(tests)
                             and all(t['status'] == 'passed' for t in tests), 'tests': tests,
                             'seconds': round(sum(t['seconds'] for t in tests), 3)})
    report = {'mode': 'offline-synthetic-services', 'app_version': __version__,
              'passed': all(code == 0 for code in exit_codes) and all(r['passed'] for r in runs),
              'pytest_exit_codes': exit_codes,
              'scenarios': len(selected), 'repeat': args.repeat, 'runs': runs,
              'timing_scope': 'Local test execution only; not live model, browser rendering or service latency.',
              'live_model': 'not_run', 'live_jira': 'not_run'}
    args.json_report.parent.mkdir(parents=True, exist_ok=True)
    args.json_report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'scenarios': len(selected), 'runs': len(runs),
                      'report': str(args.json_report), 'mode': report['mode']}))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
