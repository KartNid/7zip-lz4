"""Black-box smart extraction checks using independently generated archives."""
import bz2
import gzip
import io
import lzma
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import zipfile


def main():
    binary = str(Path(sys.argv[1]).resolve())
    passed = 0
    with tempfile.TemporaryDirectory(prefix='7zip-smart-test-') as temp:
        root = Path(temp)
        scratch = root / 'temporary'
        scratch.mkdir()
        env = dict(os.environ, TMPDIR=str(scratch), TMP=str(scratch), TEMP=str(scratch))

        def run(args, success=True, cwd=None):
            p = subprocess.run([binary, *map(str, args)], cwd=cwd or root,
                               env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               timeout=120)
            if (p.returncode == 0) != success:
                raise AssertionError((args, p.returncode, p.stdout.decode(errors='replace')))
            assert not list(scratch.glob('7z-smart-*')), 'Leaked a temporary decoded stream'
            return p

        def files(path):
            return {p.relative_to(path).as_posix(): p.read_bytes()
                    for p in path.rglob('*') if p.is_file()}

        def zip_data(entries):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as z:
                for name, value in entries.items():
                    z.writestr(name, value)
            return stream.getvalue()

        def tar_data(entries):
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode='w', format=tarfile.PAX_FORMAT) as t:
                for name, value in entries.items():
                    item = tarfile.TarInfo(name)
                    item.mtime = 1234567890
                    if name.endswith('/'):
                        item.type = tarfile.DIRTYPE
                        t.addfile(item)
                    else:
                        item.size = len(value)
                        t.addfile(item, io.BytesIO(value))
            return stream.getvalue()

        def check(name, data, expected, dirs=()):
            nonlocal passed
            case = root / str(passed)
            case.mkdir()
            archive = case / name
            archive.write_bytes(data)
            output = case / 'output'
            run(['x', '-smart', archive, '-o' + str(output), '-y'])
            assert files(output) == expected, (name, files(output), expected)
            for directory in dirs:
                assert (output / directory).is_dir(), (name, directory)
            passed += 1
            print('PASS smart ' + name, flush=True)
            return archive, output

        check('flat.zip', zip_data({'a.txt': b'a', 'b.txt': b'b'}),
              {'flat/a.txt': b'a', 'flat/b.txt': b'b'})
        archive, output = check('single.zip', zip_data({'a.txt': b'a'}), {'single/a.txt': b'a'})
        # Repeat without touching existing output; also account for a colliding file.
        (output / 'single (2)').write_bytes(b'keep')
        run(['x', '-smart', archive, '-o' + str(output), '-y'])
        assert (output / 'single/a.txt').read_bytes() == b'a'
        assert (output / 'single (2)').read_bytes() == b'keep'
        assert (output / 'single (3)/a.txt').read_bytes() == b'a'
        check('implicit.zip', zip_data({'photos/a.txt': b'a', 'photos/sub/b.txt': b'b'}),
              {'photos/a.txt': b'a', 'photos/sub/b.txt': b'b'})
        check('explicit.zip', zip_data({'photos/': b'', 'photos/a.txt': b'a'}), {'photos/a.txt': b'a'})
        check('mixed.zip', zip_data({'photos/a.txt': b'a', 'readme.txt': b'b'}),
              {'mixed/photos/a.txt': b'a', 'mixed/readme.txt': b'b'})
        check('two.zip', zip_data({'one/a.txt': b'a', 'two/b.txt': b'b'}),
              {'two/one/a.txt': b'a', 'two/two/b.txt': b'b'})
        check('empty-dir.zip', zip_data({'photos/': b''}), {}, ['photos'])
        check('empty.zip', zip_data({}), {})
        check('release.v1.zip', zip_data({'a.txt': b'a'}), {'release.v1/a.txt': b'a'})
        check('中文 空格.zip', zip_data({'读我.txt': '你好'.encode()}),
              {'中文 空格/读我.txt': '你好'.encode()})

        layouts = [
            ({'photos/a.txt': b'a', 'photos/sub/b.txt': b'b'},
             {'photos/a.txt': b'a', 'photos/sub/b.txt': b'b'}),
            ({'./': b'', './photos/': b'', './photos/a.txt': b'a'}, {'photos/a.txt': b'a'}),
            ({'a.txt': b'a', 'b.txt': b'b'}, {'bundle/a.txt': b'a', 'bundle/b.txt': b'b'}),
            ({'a.txt': b'a'}, {'bundle/a.txt': b'a'})]
        wrappers = [('gz', gzip.compress), ('bz2', bz2.compress), ('xz', lzma.compress),
                    ('lzma', lambda b: lzma.compress(b, format=lzma.FORMAT_ALONE))]
        import lz4.frame
        wrappers.append(('lz4', lambda b: lz4.frame.compress(b, content_checksum=True)))
        for entries, expected in layouts:
            tar = tar_data(entries)
            check('bundle.tar', tar, expected)
            for extension, compress in wrappers:
                check('bundle.tar.' + extension, compress(tar), expected)
        for extension, compress in [('tgz', gzip.compress), ('tbz2', bz2.compress), ('txz', lzma.compress)]:
            check('bundle.' + extension, compress(tar_data({'a.txt': b'a'})), {'bundle/a.txt': b'a'})

        # Detect TAR by decoded contents rather than requiring a .tar filename.
        check('bundle.gz', gzip.compress(tar_data({'a.txt': b'a'})), {'bundle/a.txt': b'a'})
        check('plain.txt.gz', gzip.compress(b'plain text'), {'plain.txt/plain.txt': b'plain text'})
        check('nested.zip', zip_data({'payload.tar': tar_data({'a.txt': b'a'})}),
              {'nested/payload.tar': tar_data({'a.txt': b'a'})})
        # A pre-existing root tree is left intact, including nested symlinks.
        case = root / 'existing-root'
        case.mkdir()
        (case / 'photos').mkdir()
        (case / 'photos/keep.txt').write_bytes(b'keep')
        existing = root / 'existing.zip'
        existing.write_bytes(zip_data({'photos/a.txt': b'a'}))
        run(['x', '-smart', existing, '-o' + str(case), '-y'])
        assert files(case) == {'photos/keep.txt': b'keep', 'existing/photos/a.txt': b'a'}
        if os.name != 'nt':
            output = root / 'link-output'
            output.mkdir()
            outside = root / 'outside'
            outside.mkdir()
            (output / 'photos').symlink_to(outside, target_is_directory=True)
            run(['x', '-smart', existing, '-o' + str(output), '-y'])
            assert not list(outside.iterdir()), 'Followed a pre-existing output symlink'
            assert (output / 'existing/photos/a.txt').read_bytes() == b'a'
        # A skippable frame before TAR data must also be transparent in smart mode.
        import struct
        frame = lz4.frame.compress(tar_data({'a.txt': b'a'}))
        check('bundle.tar.lz4', struct.pack('<II', 0x184D2A50, 4) + b'skip' + frame,
              {'bundle/a.txt': b'a'})

        for extension, compress in wrappers:
            frame = compress(tar_data({'a.txt': b'a'}))
            for bad in (frame[:-1], frame[:len(frame)//2]):
                badfile = root / ('broken.tar.' + extension)
                badfile.write_bytes(bad)
                output = root / 'bad-output'
                run(['x', '-smart', badfile, '-o' + str(output), '-y'], success=False)
                assert not files(output), 'Published output from a truncated outer stream'
        for extension, compress in [('gz', gzip.compress),
                                    ('lz4', lambda b: lz4.frame.compress(b, content_checksum=True))]:
            bad = bytearray(compress(tar_data({'a.txt': b'a'})))
            bad[-1] ^= 0x80
            badfile = root / ('checksum.tar.' + extension)
            badfile.write_bytes(bad)
            run(['x', '-smart', badfile, '-o' + str(root / 'checksum-output'), '-y'], success=False)
            assert not files(root / 'checksum-output')
            badfile.write_bytes(compress(b'This is not a TAR archive'))
            run(['x', '-smart', badfile, '-o' + str(root / 'bad-tar-output'), '-y'], success=False)
            assert not files(root / 'bad-tar-output')

        # Existing extraction remains one layer for gzip; nested archives in ZIP
        # are ordinary files. Explicit -smart- disables the new behavior.
        normal = root / 'normal.tar.gz'
        normal.write_bytes(gzip.compress(tar_data({'a.txt': b'a'})))
        run(['x', normal, '-o' + str(root / 'normal'), '-y'])
        assert (root / 'normal/normal.tar').is_file()
        run(['x', '-smart-', archive, '-o' + str(root / 'disabled'), '-y'])
        assert files(root / 'disabled') == {'a.txt': b'a'}
        for args in (['x', '-smart', '-so', archive], ['e', '-smart', archive],
                     ['t', '-smart', archive], ['x', '-smart', '-spf', archive]):
            run(args, success=False)

        # Exercise native 7z codecs, encrypted headers, and multiple input archives.
        source = root / 'source'
        source.mkdir()
        (source / 'a.txt').write_bytes(b'a')
        for method in ('LZMA2', 'LZ4'):
            arc = root / (method + '.7z')
            run(['a', arc, 'a.txt', '-m0=' + method, '-pSmartTest', '-mhe=on'], cwd=source)
            run(['x', '-smart', arc, '-pSmartTest', '-o' + str(root / method), '-y'])
            assert files(root / method) == {method + '/a.txt': b'a'}
        first = root / 'first.zip'
        second = root / 'second.zip'
        first.write_bytes(zip_data({'a': b'a'}))
        second.write_bytes(zip_data({'b': b'b'}))
        run(['x', '-smart', first, '-ai!' + str(second), '-o' + str(root / 'batch'), '-y'])
        assert files(root / 'batch') == {'first/a': b'a', 'second/b': b'b'}
        print('PASS smart collisions, outer integrity, cleanup, opt-out, encrypted 7z/LZ4, and batch extraction')
        print('PASS all smart extraction checks (' + str(passed) + ' layout cases)')


if __name__ == '__main__':
    main()
