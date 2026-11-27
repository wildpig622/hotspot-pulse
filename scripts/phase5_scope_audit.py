"""Explicit release audit/minimization; never part of production collection."""
import argparse
import ast
import collections
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from .business_service import ROOT
from .phase3_public_evidence import redact, EMAIL, PHONE

OUT = ROOT / 'docs/phase5-release-2026-11-27'


def git(*args):
    return subprocess.check_output(['git', '-c', 'safe.directory=' + ROOT.as_posix(), *args], cwd=ROOT).decode('utf8').splitlines()


def minimize():
    backup = ROOT / 'review/phase5-original-public-evidence'
    manifest = []
    for folder in ('phase2-evidence-2026-11-26', 'phase3-evidence-2026-11-26'):
        for file in sorted((ROOT / 'docs' / folder).rglob('*')):
            if not file.is_file():
                continue
            relative = file.relative_to(ROOT)
            raw = file.read_bytes()
            target = backup / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(file, target)
            action = None
            if file.suffix in {'.gz', '.zip'}:
                file.unlink()  # Explicit files only, scoped under the two named evidence directories.
                action = 'raw_response_removed_from_current_tree'
            elif file.suffix == '.json':
                value = json.loads(raw)
                stats = collections.Counter()
                def walk(obj, key=''):
                    if isinstance(obj, dict):
                        result = {}
                        for k, v in obj.items():
                            if k in {'body_text', 'body', 'html', 'raw_html', 'response_body', 'raw_file', 'raw_path'}:
                                stats['unnecessary_body_or_archive_fields_removed'] += 1
                                continue
                            result[k] = walk(v, k)
                        return result
                    if isinstance(obj, list):
                        return [walk(v, key) for v in obj]
                    if isinstance(obj, str):
                        if key.endswith('sha256') or key in {'event_id', 'source_record_id', 'observation_id', 'canonical_id'}:
                            return obj
                        clean, counts = redact(obj)
                        stats.update(counts)
                        # Public evidence is a short derivative; original local hashes remain in manifest.
                        if not re.match(r'^https?://', clean) and len(clean) > 320:
                            clean = clean[:160] + ' [PUBLIC_EXCERPT_TRUNCATED]'
                            stats['long_strings_minimized'] += 1
                        return clean
                    return obj
                value = walk(value)
                if any(stats.values()):
                    file.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
                    action = 'minimal_contact_redacted_derivative'
            elif file.suffix == '.txt' and ('platforms' in str(relative)):
                # Verbose third-party command output is unnecessary for release review.
                file.write_text('Raw platform command output removed from current tree. See source-availability.json and runs.json for availability; original retained locally.\n', encoding='utf8')
                action = 'raw_platform_stdout_replaced_by_note'
            if action:
                manifest.append({'path': relative.as_posix(), 'original_sha256': hashlib.sha256(raw).hexdigest(), 'original_bytes': len(raw), 'action': action,
                                 'current_sha256': hashlib.sha256(file.read_bytes()).hexdigest() if file.exists() else None})
    (OUT / 'evidence-minimization.json').write_text(json.dumps({'note': 'Current-tree minimization only. Previously pushed commits still contain historical objects; history has NOT been rewritten.', 'files': manifest}, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


def audit():
    baseline_paths = set(git('diff', '--name-only', 'origin/main...29f99b0'))
    current = set(git('diff', '--name-only', 'origin/main...HEAD')) | set(git('diff', '--name-only')) | set(git('ls-files', '--others', '--exclude-standard'))
    main_paths = set(git('ls-tree', '-r', '--name-only', 'origin/main'))
    net = {p for p in current if (ROOT / p).exists() or p in main_paths}
    paths = baseline_paths | current
    categories = collections.defaultdict(list)
    issues = []
    pr_findings = []
    credential_findings = []
    def contacts(text, suffix):
        findings = []
        def walk(value, key=''):
            if isinstance(value, dict):
                for k, v in value.items():
                    walk(v, k)
            elif isinstance(value, list):
                for v in value:
                    walk(v, key)
            elif isinstance(value, str):
                if key.endswith(('_id', '_ids', 'sha256')) or key in {'sha256', 'membership', 'aliases', 'cursor'}:
                    return
                if re.fullmatch(r'(?:hp|evt|off|src|obs|p4)_[A-Za-z0-9_-]+', value):
                    return
                if EMAIL.search(value) or PHONE.search(value):
                    findings.append({'field': key, 'email': len(EMAIL.findall(value)), 'phone': len(PHONE.findall(value))})
        if suffix == '.json':
            walk(json.loads(text))
        elif EMAIL.search(text) or PHONE.search(text):
            findings.append({'email': len(EMAIL.findall(text)), 'phone': len(PHONE.findall(text))})
        return findings
    for path in sorted(paths):
        if path.startswith(('docs/', 'config/phase')):
            category = 'experiment_evidence_or_configuration'
        elif path.startswith('tests/'):
            category = 'tests'
        elif path.startswith('scripts/phase') or path == 'scripts/demand_candidates.py' or path == 'scripts/event_observations.py':
            category = 'manual_experiment'
        else:
            category = 'production_or_contract'
        categories[category].append(path)
        file = ROOT / path
        if file.is_file() and file.suffix in {'.json', '.js', '.mjs', '.py', '.yml', '.md', '.txt', '.html', '.css'}:
            text = file.read_text(encoding='utf8')
            found = contacts(text, file.suffix)
            if found:
                pr_findings.append({'path': path, 'findings': found, 'classification': 'synthetic_test_or_detector_pattern' if path.startswith(('tests/', 'scripts/phase3_public_evidence.py')) else 'requires_review'})
            if re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bghp_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}|\bsk-[A-Za-z0-9]{32,}', text):
                credential_findings.append(path)
    # Inspect every file that would actually be uploaded as the static website.
    for file in (ROOT / 'site').rglob('*'):
        if not file.is_file() or file.suffix not in {'.json', '.js', '.html', '.css', '.mjs'}:
            continue
        text = file.read_text(encoding='utf8')
        counts = contacts(text, file.suffix)
        if counts:
            issues.append({'path': file.relative_to(ROOT).as_posix(), 'type': 'potential_contact_match_requires_review', 'findings': counts})
    # Traverse static imports reachable from the only production refresh entry.
    pending = ['refresh_service']; reached = set(); experimental = []
    while pending:
        module = pending.pop()
        if module in reached:
            continue
        reached.add(module)
        file = ROOT / 'scripts' / (module + '.py')
        if not file.exists():
            continue
        tree = ast.parse(file.read_text(encoding='utf8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                names = [node.module.split('.')[0]] if node.module else [n.name for n in node.names]
                pending.extend(n for n in names if (ROOT / 'scripts' / (n + '.py')).exists())
        if module.startswith('phase'):
            experimental.append(module)
    payload = {'main_sha': git('rev-parse', 'origin/main')[0], 'phase4_start_changed_files': len(baseline_paths), 'current_accumulated_paths_including_deletions': len(paths),
               'candidate_net_pr_paths': len(net), 'retired_prior_added_paths': sorted(p for p in paths if not (ROOT / p).exists() and p not in main_paths),
               'categories': dict(categories), 'production_imports': sorted(reached), 'production_reaches_experiment': experimental,
               'release_artifact_root': 'site/', 'excluded_from_website': ['docs/', 'tests/', 'scripts/', 'config/', 'review/'],
               'static_site_privacy_findings': issues, 'historical_git_objects_not_rewritten': True}
    payload.update(pr_contact_findings=pr_findings, credential_pattern_findings=credential_findings,
                   privacy_limits='Pattern scan only, not proof that all personal information or every possible credential is absent. Stable ID fields are excluded after schema inspection.')
    (OUT / 'scope-audit.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'paths': len(paths), 'categories': {k: len(v) for k, v in categories.items()}, 'production_experiments': experimental, 'site_privacy_findings': len(issues)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--minimize', action='store_true'); args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.minimize:
        minimize()
    audit()
