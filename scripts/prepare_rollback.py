"""Prepare an OFFLINE UI rollback copy while preserving every current API byte.

No deployment, Git mutation, collector, search provider, or database operations.
Data rollback requires a separate reconciliation of any later human decisions.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from .business_service import ROOT


def api_hashes(site):
    return {p.relative_to(site / 'api').as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (site / 'api').rglob('*') if p.is_file()}


def prepare(backup, current, output, expected_backup_hashes):
    backup, current, output = (Path(p).resolve() for p in (backup, current, output))
    if not output.is_relative_to(ROOT / 'review') or output == ROOT / 'review':
        raise ValueError('offline_review_output_required')
    if output.is_relative_to(backup) or output.is_relative_to(current):
        raise ValueError('rollback_output_must_be_separate_from_inputs')
    if output.exists() and any(output.iterdir()):
        raise ValueError('new_empty_rollback_directory_required')
    if not (backup / 'index.html').is_file() or not (current / 'api').is_dir():
        raise ValueError('backup_site_and_current_api_required')
    # The operator supplies the separately saved backup manifest, not an unchecked label.
    actual = {p.relative_to(backup).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in backup.rglob('*') if p.is_file()}
    if actual != expected_backup_hashes:
        raise ValueError('backup_manifest_mismatch')
    for file in (current / 'api').rglob('*.json'):
        json.loads(file.read_text(encoding='utf8'))
    before = api_hashes(current)
    if not before:
        raise ValueError('current_api_must_not_be_empty')
    output.mkdir(parents=True, exist_ok=True)
    for file in backup.iterdir():
        if file.name == 'api':
            continue
        if file.is_dir():
            shutil.copytree(file, output / file.name)
        else:
            shutil.copy2(file, output / file.name)
    shutil.copytree(current / 'api', output / 'api')
    if api_hashes(output) != before:
        raise ValueError('current_api_preservation_failed')
    return {'prepared': True, 'deployed': False, 'mode': 'previous_ui_with_current_last_good_api',
            'preserved_api_files': len(before), 'output': str(output)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-site', type=Path, required=True)
    parser.add_argument('--backup-manifest', type=Path, required=True)
    parser.add_argument('--current-site', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.backup_manifest.read_text(encoding='utf8'))
    print(json.dumps(prepare(args.backup_site, args.current_site, args.output, manifest['files']), ensure_ascii=False))
