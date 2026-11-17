"""Black-box regression checks for the 26.06 merge, using independent fixtures."""
import io
import itertools
from pathlib import Path
import random
import shutil
import string
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib


def cabinet(entries, method):
    """Build a CAB with one folder and stored or MSZIP 32 KiB data blocks."""
    contents = b''.join(entries.values())
    files = bytearray()
    offset = 0
    for name, data in entries.items():
        files += struct.pack('<IIHHHH', len(data), offset, 0, 0x5421, 0, 0x20)
        files += name.encode('ascii') + b'\0'
        offset += len(data)
    blocks = bytearray()
    count = 0
    for offset in range(0, len(contents), 32768):
        chunk = contents[offset:offset + 32768]
        if method == 1:
            coder = zlib.compressobj(wbits=-15)
            coded = b'CK' + coder.compress(chunk) + coder.flush()
        else:
            coded = chunk
        blocks += struct.pack('<IHH', 0, len(coded), len(chunk)) + coded
        count += 1
    data_offset = 44 + len(files)
    header = struct.pack('<4sIIIIIBBHHHHH', b'MSCF', 0, data_offset + len(blocks),
                         0, 44, 0, 3, 1, 1, len(entries), 0, 0, 0)
    return header + struct.pack('<IHH', data_offset, count, method) + files + blocks


def szdd_header(size):
    return b'SZDD\x88\xf0\x27\x33A' + b't' + struct.pack('<I', size)


def szdd_literals(data):
    result = bytearray(szdd_header(len(data)))
    for offset in range(0, len(data), 8):
        chunk = data[offset:offset + 8]
        result += bytes([(1 << len(chunk)) - 1]) + chunk
    return result


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    binary = str(Path(sys.argv[1]).resolve())
    with tempfile.TemporaryDirectory(prefix='7zip-2606-') as temp:
        root = Path(temp)

        def run(args, success=True, stdin=None):
            result = subprocess.run([binary, *map(str, args)], cwd=root, input=stdin,
                                    capture_output=True, timeout=120)
            assert result.returncode in (0, 1, 2, 7, 8, 255), ('Crash', args, result.returncode)
            assert (result.returncode == 0) == success, (args, result.returncode,
                result.stdout.decode(errors='replace'), result.stderr.decode(errors='replace'))
            return result.stdout

        assert b'26.06' in run(['i']), 'Wrong upstream binary version'

        # Cover numeric carries, alphabetic carries, and GNU's automatic suffix growth.
        latin = [''.join(p) for p in itertools.product(string.ascii_lowercase, repeat=2)]
        gnu_latin = latin[:650] + ['za' + n for n in latin[:60]]
        numeric = [f'{i:02}' for i in range(100)]
        gnu_numeric = numeric[:90] + ['90' + n for n in numeric[:20]]
        cases = [
            ('payload.', [f'{i:03}' for i in range(1, 115)]),
            ('payload.', [f'{i:02}' for i in range(115)]),
            ('payload.', [f'{i:02}' for i in range(1, 115)]),
            ('payload.', latin), ('payload', latin[:28]),
            ('payload', [s.upper() for s in latin]),
            ('payload', gnu_latin), ('payload.', gnu_numeric)]
        for index, (prefix, suffixes) in enumerate(cases):
            case = root / f'split-{index}'
            case.mkdir()
            expected = bytearray()
            for i, suffix in enumerate(suffixes):
                chunk = f'part-{i:04}\n'.encode()
                (case / (prefix + suffix)).write_bytes(chunk)
                expected += chunk
            first = case / (prefix + suffixes[0])
            assert run(['x', '-tsplit', first, '-so']) == expected
            run(['t', '-tsplit', first])
            print(f'PASS split naming case {index}: {len(suffixes)} volumes', flush=True)

        # Verify the independent Linux split utility's actual filenames and contents.
        if sys.platform != 'win32' and shutil.which('split'):
            for numeric_mode in (False, True):
                case = root / ('gnu-numeric' if numeric_mode else 'gnu-latin')
                case.mkdir()
                expected = random.Random(9).randbytes(720)
                source = case / 'source'
                source.write_bytes(expected)
                prefix = case / 'payload.'
                subprocess.run(['split', '-b', '1', *(['-d'] if numeric_mode else []),
                                str(source), str(prefix)], check=True, timeout=30)
                first = case / ('payload.00' if numeric_mode else 'payload.aa')
                assert run(['x', '-tsplit', first, '-so']) == expected
            print('PASS independent GNU split alphabetic/numeric suffix expansion', flush=True)

        # A split ZIP exercises seekable multi-stream reads and smart folder detection.
        stream = io.BytesIO()
        payload = random.Random(11).randbytes(16384)
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_STORED) as archive:
            archive.writestr('photos/picture.bin', payload)
        encoded = stream.getvalue()
        case = root / 'split-zip'
        case.mkdir()
        for i, offset in enumerate(range(0, len(encoded), 101), 1):
            (case / f'photos.zip.{i:03}').write_bytes(encoded[offset:offset + 101])
        first = case / 'photos.zip.001'
        run(['t', first])
        assert run(['x', first, '-so']) == payload
        output = case / 'output'
        run(['x', '-smart', first, '-o' + str(output), '-y'])
        assert (output / 'photos/picture.bin').read_bytes() == payload
        print('PASS seekable split ZIP and smart extraction', flush=True)

        entries = {'photos/a.bin': random.Random(4).randbytes(40000),
                   'photos/b.txt': b'CAB MSZIP cross-block history\n' * 1800}
        for method in (0, 1):
            path = root / f'method-{method}.cab'
            data = cabinet(entries, method)
            path.write_bytes(data)
            run(['t', '-tcab', path])
            output = root / f'cab-output-{method}'
            run(['x', '-smart', '-tcab', path, '-o' + str(output), '-y'])
            actual = {p.relative_to(output).as_posix(): p.read_bytes()
                      for p in output.rglob('*') if p.is_file()}
            assert actual == entries
            bad = root / 'bad.cab'
            bad.write_bytes(data[:-5])
            run(['t', '-tcab', bad], success=False)
        print('PASS stored/MSZIP CAB extraction, block boundaries, and truncation', flush=True)

        for size in (0, 1, 7, 8, 32769, 131089):
            data = random.Random(size).randbytes(size)
            path = root / 'sample.tx_'
            path.write_bytes(szdd_literals(data))
            run(['t', '-tmslz', path])
            assert run(['x', '-tmslz', path, '-so']) == data
            assert run(['x', '-tmslz', '-si', '-so'], stdin=path.read_bytes()) == data
        # Backreferences into the initialized dictionary must be deterministic.
        for offset, expected in ((4080, b'\0' * 3), (0, b' ' * 3)):
            path.write_bytes(szdd_header(3) + bytes([0, offset & 255, (offset >> 4) & 240]))
            actual = run(['x', '-tmslz', path, '-so'])
            assert actual == expected, (offset, actual, expected)
        for bad in (szdd_header(1) + b'\x01',
                    szdd_header(2) + b'\0\0\0',
                    szdd_header(1) + b'\xffx', szdd_header(0x80000001)):
            path.write_bytes(bad)
            run(['t', '-tmslz', path], success=False)
        print('PASS SZDD streaming, dictionary initialization, bounds, and malformed input', flush=True)

        # The refactored copy coder must preserve unchanged data during archive updates.
        source = root / 'keep.bin'
        source.write_bytes(payload)
        added = root / 'added.txt'
        added.write_bytes(b'new file')
        for fmt, options in (('7z', []), ('7z', ['-m0=LZ4']), ('zip', []), ('tar', [])):
            archive = root / ('update-' + str(len(options)) + '.' + fmt)
            run(['a', archive, source, *options, '-y'])
            run(['a', archive, added, *options, '-y'])
            run(['t', archive])
            assert run(['x', archive, source.name, '-so']) == payload
            assert run(['x', archive, added.name, '-so']) == b'new file'
        print('PASS 7z, 7z/LZ4, ZIP and TAR archive updates preserve existing data', flush=True)
    print('PASS all upstream 26.06 regression checks')


if __name__ == '__main__':
    main()
