"""Verify the exact, attributed upstream language resources before packaging."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / 'docs/languages.json').read_text())
files = {p.name: p for p in (root / 'Lang').iterdir() if p.is_file()}
assert set(files) == set(manifest['files'])
assert len(files) == 93 and len(list((root / 'Lang').glob('*.txt'))) == 92
for name, digest in manifest['files'].items():
    data = files[name].read_bytes()
    assert hashlib.sha256(data).hexdigest() == digest, name
    text = data.decode('utf-8-sig').replace('\r\n', '\n')
    assert text.startswith(';!@Lang2@!UTF-8!\n'), name
    assert '\n0\n7-Zip\n' in text, name
for name in ('zh-cn', 'zh-tw', 'ja', 'ko', 'fr', 'de', 'es', 'ru'):
    assert name + '.txt' in files
print('PASS 93 official language resources: manifest, UTF-8, signatures, and checksums')
for path in (root / 'Lang/Custom').glob('*.txt'):
    text = path.read_text(encoding='utf-8-sig').replace('\r\n', '\n')
    assert text.startswith(';!@Lang2@!UTF-8!\n') and '\n2331\n' in text, path
print('PASS additive custom UI catalogs')
