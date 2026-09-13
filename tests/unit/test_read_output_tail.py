"""Tests for read_output_tail: tail semantics, encoding safety, bounded read.

The function feeds /api/jobs/<id>/output and must never 500 on a log file
that contains non-UTF-8 bytes, and must not slurp whole multi-MB logs for a
small tail.
"""
from retrobridge.jobs.utils import read_output_tail


def _write(tmp_path, name, content):
    p = tmp_path / name
    if isinstance(content, str):
        p.write_text(content)
    else:
        p.write_bytes(content)
    return str(p)


def test_returns_all_lines_when_tail_is_none(tmp_path):
    path = _write(tmp_path, 'all.txt', 'one\ntwo\nthree\n')
    assert read_output_tail(path) == ['one', 'two', 'three']


def test_returns_last_n_lines(tmp_path):
    path = _write(tmp_path, 'tail.txt', 'l1\nl2\nl3\nl4\nl5\n')
    assert read_output_tail(path, tail=2) == ['l4', 'l5']


def test_tail_larger_than_file_returns_all_lines(tmp_path):
    path = _write(tmp_path, 'small.txt', 'a\nb\n')
    assert read_output_tail(path, tail=10) == ['a', 'b']


def test_tail_zero_is_treated_as_unlimited(tmp_path):
    path = _write(tmp_path, 'zero.txt', 'a\nb\n')
    assert read_output_tail(path, tail=0) == ['a', 'b']


def test_negative_tail_is_treated_as_unlimited(tmp_path):
    path = _write(tmp_path, 'neg.txt', 'a\nb\n')
    assert read_output_tail(path, tail=-1) == ['a', 'b']


def test_missing_file_returns_empty_list(tmp_path):
    assert read_output_tail(str(tmp_path / 'nope.txt')) == []


def test_empty_file_returns_empty_list(tmp_path):
    path = _write(tmp_path, 'empty.txt', '')
    assert read_output_tail(path, tail=5) == []


def test_file_without_trailing_newline(tmp_path):
    path = _write(tmp_path, 'noeol.txt', 'a\nb\nc')
    assert read_output_tail(path, tail=2) == ['b', 'c']


def test_crlf_line_endings_are_normalized(tmp_path):
    # Current behavior: text-mode universal newlines strip the \r.
    path = _write(tmp_path, 'crlf.txt', 'a\r\nb\r\nc\r\n')
    assert read_output_tail(path, tail=2) == ['b', 'c']


def test_lone_cr_line_endings_are_normalized(tmp_path):
    path = _write(tmp_path, 'lonecr.txt', 'a\rb\rc\r')
    assert read_output_tail(path, tail=2) == ['b', 'c']


def test_non_utf8_bytes_do_not_raise(tmp_path):
    raw = b'ok line\n\xff\xfe\x80 bad bytes\nlast\n'
    path = _write(tmp_path, 'bad.txt', raw)
    expected_second = b'\xff\xfe\x80 bad bytes\n'.decode('utf-8', errors='replace').rstrip('\n')
    assert read_output_tail(path, tail=2) == [expected_second, 'last']


def test_last_lines_of_large_file(tmp_path):
    path = _write(tmp_path, 'large.txt',
                  ''.join(f'line{i}\n' for i in range(5000)))
    assert read_output_tail(path, tail=3) == ['line4997', 'line4998', 'line4999']


def test_single_long_line_followed_by_short_line(tmp_path):
    path = _write(tmp_path, 'longline.txt', ('x' * 20000) + '\ny\n')
    assert read_output_tail(path, tail=1) == ['y']
