"""Black-box smart extraction checks using independently generated archives."""
import bz2
import gzip
import io
import lzma
import os
import random
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import zipfile


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
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
        # Repeat into the same ordinary folder, preserving unrelated files.
        (output / 'single/a.txt').write_bytes(b'old')
        (output / 'single/keep.txt').write_bytes(b'keep')
        (output / 'single (2)').write_bytes(b'keep')
        run(['x', '-smart', archive, '-o' + str(output), '-y'])
        assert (output / 'single/a.txt').read_bytes() == b'a'
        assert (output / 'single (2)').read_bytes() == b'keep'
        assert (output / 'single/keep.txt').read_bytes() == b'keep'
        assert not (output / 'single (3)').exists()
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
        # A pre-existing common root is merged, without an extra container.
        case = root / 'existing-root'
        case.mkdir()
        (case / 'photos').mkdir()
        (case / 'photos/keep.txt').write_bytes(b'keep')
        existing = root / 'existing.zip'
        existing.write_bytes(zip_data({'photos/a.txt': b'a'}))
        run(['x', '-smart', existing, '-o' + str(case), '-y'])
        assert files(case) == {'photos/keep.txt': b'keep', 'photos/a.txt': b'a'}
        if os.name != 'nt':
            output = root / 'link-output'
            output.mkdir()
            outside = root / 'outside'
            outside.mkdir()
            (output / 'photos').symlink_to(outside, target_is_directory=True)
            run(['x', '-smart', existing, '-o' + str(output), '-y'])
            assert not list(outside.iterdir()), 'Followed a pre-existing output symlink'
            assert (output / 'existing/photos/a.txt').read_bytes() == b'a'
            (case / 'photos/sub').symlink_to(outside, target_is_directory=True)
            existing.write_bytes(zip_data({'photos/sub/a.txt': b'a'}))
            run(['x', '-smart', existing, '-o' + str(case), '-y'], success=False)
            assert not list(outside.iterdir()), 'Followed a nested directory link in a reused tree'

        # Every conflict policy works inside both reused layouts and decoded TARs.
        merge_checks = 0
        names = ['app.info', '读我.txt', 'no-extension', '.hidden']
        for common_root in (False, True):
            for extension, encode in [('zip', zip_data),
                                      ('tar.gz', lambda e: gzip.compress(tar_data(e))),
                                      ('tar.lz4', lambda e: lz4.frame.compress(tar_data(e)))]:
                for mode in ('-aos', '-aoa', '-aou'):
                    case = root / ('merge-' + str(merge_checks))
                    case.mkdir()
                    parent = case / 'output'
                    dest = parent / ('photos' if common_root else 'bundle')
                    dest.mkdir(parents=True)
                    for name in names:
                        (dest / name).write_bytes(b'old')
                    (dest / 'app (2).info').write_bytes(b'keep2')
                    (dest / 'app (4).info').write_bytes(b'keep4')
                    (dest / 'keep.txt').write_bytes(b'keep')
                    entries = {(('photos/' if common_root else '') + n): b'new' for n in names}
                    entries[('photos/' if common_root else '') + 'fresh.txt'] = b'fresh'
                    archive2 = case / ('bundle.' + extension)
                    archive2.write_bytes(encode(entries))
                    run(['x', '-smart', archive2, '-o' + str(parent), mode])
                    expected = {n: b'new' if mode == '-aoa' else b'old' for n in names}
                    expected.update({'app (2).info': b'keep2', 'app (4).info': b'keep4',
                                     'keep.txt': b'keep', 'fresh.txt': b'fresh'})
                    if mode == '-aou':
                        expected.update({'app (3).info': b'new', '读我 (2).txt': b'new',
                                         'no-extension (2)': b'new', '.hidden (2)': b'new'})
                    assert files(dest) == expected, (common_root, extension, mode, files(dest))
                    assert list(parent.iterdir()) == [dest], 'Created a numbered directory instead of merging'
                    merge_checks += 1
        # A same-name file cannot be reused as a directory; choose a new container.
        output = root / 'file-collision'
        output.mkdir()
        (output / 'single').write_bytes(b'keep')
        (output / 'single (2)').write_bytes(b'keep2')
        run(['x', '-smart', archive, '-o' + str(output), '-y'])
        assert files(output) == {'single': b'keep', 'single (2)': b'keep2', 'single (3)/a.txt': b'a'}
        print(f'PASS {merge_checks} merge/conflict policy cases and file/link isolation', flush=True)
        # A skippable frame before TAR data must also be transparent in smart mode.
        import struct
        frame = lz4.frame.compress(tar_data({'a.txt': b'a'}))
        check('bundle.tar.lz4', struct.pack('<II', 0x184D2A50, 4) + b'skip' + frame,
              {'bundle/a.txt': b'a'})
        large = random.Random(17).randbytes(2 * 1024 * 1024 + 17)
        for extension, compress in [('gz', gzip.compress),
                                    ('lz4', lambda b: lz4.frame.compress(b, content_checksum=True))]:
            check('large.tar.' + extension, compress(tar_data({'big.bin': large})),
                  {'large/big.bin': large})

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
