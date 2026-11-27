"""Assemble a reviewable static release copy; never commits or publishes it."""
import argparse
import json
import shutil
from pathlib import Path
from .business_service import ROOT, build


def assemble(output, agent_import=None):
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT / 'review') or output == ROOT / 'review':
        raise ValueError('release_output_must_be_a_dedicated_review_subdirectory')
    if output.exists() and any(output.iterdir()):
        raise ValueError('use_a_new_empty_release_directory')
    shutil.copytree(ROOT / 'site', output, dirs_exist_ok=True)
    rows = []
    if agent_import:
        batch = json.loads(Path(agent_import).read_text(encoding='utf8'))
        if batch.get('schema_version') != 'agent-import-1' or not isinstance(batch.get('data'), list):
            raise ValueError('agent_import_envelope_required')
        rows = batch['data']
    result = build(output / 'api/v1', imports=rows)
    return {'output': str(output), 'event_count': result['status']['event_count'], 'published': False,
            'warning': 'Candidate evidence is pending; validate and obtain release decision before any publication.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--agent-import', type=Path)
    args = parser.parse_args()
    print(json.dumps(assemble(args.output, args.agent_import), ensure_ascii=False))
