"""Keep static asset versions tied to their published Git content."""
import argparse
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--write', action='store_true')
    mode.add_argument('--check', action='store_true')
    args = parser.parse_args()
    index = ROOT / 'site/index.html'
    original = index.read_text(encoding='utf-8')
    updated = original
    for name in ('app.js', 'share-image.js', 'styles.css'):
        content = (ROOT / 'site' / name).read_bytes().replace(b'\r\n', b'\n')
        digest = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()[:12]
        updated, count = re.subn(r'\./' + re.escape(name) + r'(?:\?v=[a-f0-9]+)?(?=["\'])', './' + name + '?v=' + digest, updated)
        if count != 1:
            raise ValueError('Expected exactly one versioned resource: ' + name)
    if args.write:
        index.write_text(updated, encoding='utf-8')
    elif original != updated:
        print('Asset versions are stale; run python scripts/stamp_assets.py --write')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
