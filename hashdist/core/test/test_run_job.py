import sys
import os
from os.path import join as pjoin
from nose.tools import eq_
from textwrap import dedent
from subprocess import CalledProcessError

from .. import run_job
from .test_build_store import fixture as build_store_fixture


from .utils import MemoryLogger, logger as test_logger, assert_raises

env_to_stderr = [sys.executable, '-c',
                 "import os, sys; sys.stderr.write("
                 "'ENV:%s=%s' % (sys.argv[1], repr(os.environ.get(sys.argv[1], None))))"]
def filter_out(lines):
    return [x[len('DEBUG:ENV:'):] for x in lines if x.startswith('DEBUG:ENV:')]

@build_store_fixture()
def test_run_job_environment(tempdir, sc, build_store, cfg):
    # tests that the environment gets correctly set up and that the local scope feature
    # works
    job_spec = {
        "env": {"FOO": "foo"},
        "env_nohash": {"BAR": "$bar"},
        "commands": [
            {
                "env": {"BAR": "${FOO}x", "HI": "hi"},
                "commands": [
                    {"cmd": env_to_stderr + ["FOO"]},
                    {"cmd": env_to_stderr + ["BAR"]},
                    {"cmd": env_to_stderr + ["HI"]},
                    ],
            },
            {"cmd": env_to_stderr + ["FOO"]},
            {"cmd": env_to_stderr + ["BAR"]},
            {"cmd": env_to_stderr + ["HI"]},
            {"cmd": env_to_stderr + ["PATH"]}
        ]}
    logger = MemoryLogger()
    ret_env = run_job.run_job(logger, build_store, job_spec, {"BAZ": "BAZ"},
                              {"virtual:bash": "bash/ljnq7g35h6h4qtb456h5r35ku3dq25nl"},
                              tempdir, cfg)
    assert 'HDIST_CONFIG' in ret_env
    del ret_env['HDIST_CONFIG']
    expected = {
        'PATH': '',
        'HDIST_LDFLAGS': '',
        'HDIST_CFLAGS': '',
        'HDIST_IMPORT': '',
        'HDIST_IMPORT_PATHS': '',
        'HDIST_VIRTUALS': 'virtual:bash=bash/ljnq7g35h6h4qtb456h5r35ku3dq25nl',
        'BAR': '$bar',
        'FOO': 'foo',
        'BAZ': 'BAZ'}
    eq_(expected, ret_env)
    lines = filter_out(logger.lines)
    eq_(["FOO='foo'", "BAR='foox'", "HI='hi'", "FOO='foo'", "BAR='$bar'", 'HI=None', "PATH=''"],
        lines)

@build_store_fixture()
def test_inputs(tempdir, sc, build_store, cfg):
    job_spec = {
        "commands": [
            {"cmd": [sys.executable, "$in0", "$in1"],
             "inputs": [
                 {"text": ["import sys",
                           "import json",
                           "with open(sys.argv[1]) as f:"
                           "    print json.load(f)['foo']"]},
                 {"json": {"foo": "Hello1"}}
                 ]
             },
            {"cmd": [sys.executable, "$in0"],
             "inputs": [{"string": "import sys\nprint 'Hello2'"}]
             },
            ]
        }
    logger = MemoryLogger()
    ret_env = run_job.run_job(logger, build_store, job_spec, {"BAZ": "BAZ"},
                              {"virtual:bash": "bash/ljnq7g35h6h4qtb456h5r35ku3dq25nl"},
                              tempdir, cfg)
    assert 'DEBUG:Hello1' in logger.lines
    assert 'DEBUG:Hello2' in logger.lines

@build_store_fixture()
def test_capture_stdout(tempdir, sc, build_store, cfg):
    job_spec = {
        "commands": [
            {"cmd": ["$echo", "  a  b   \n\n\n "], "to_var": "HI"},
            {"cmd": env_to_stderr + ["HI"]}
        ]}
    logger = MemoryLogger()
    run_job.run_job(logger, build_store, job_spec, {"echo": "/bin/echo"}, {}, tempdir, cfg)
    eq_(["HI='a  b'"], filter_out(logger.lines))

@build_store_fixture()
def test_script_redirect(tempdir, sc, build_store, cfg):
    job_spec = {
        "commands": [
            {"cmd": ["$echo", "hi"], "append_to_file": "$foo", "env": {"foo": "foo"}}
        ]}
    run_job.run_job(test_logger, build_store, job_spec,
                    {"echo": "/bin/echo"}, {}, tempdir, cfg)
    with file(pjoin(tempdir, 'foo')) as f:
        assert f.read() == 'hi\n'

@build_store_fixture()
def test_attach_log(tempdir, sc, build_store, cfg):
    with file(pjoin(tempdir, 'hello'), 'w') as f:
        f.write('hello from pipe')
    job_spec = {
        "commands": [
            {"hit": ["logpipe", "mylog", "WARNING"], "to_var": "LOG"},
            {"cmd": ["/bin/dd", "if=hello", "of=$LOG"]},
        ]}
    logger = MemoryLogger()
    run_job.run_job(logger, build_store, job_spec, {}, {}, tempdir, cfg)
    assert 'WARNING:mylog:hello from pipe' in logger.lines

@build_store_fixture()
def test_error_exit(tempdir, sc, build_store, cfg):
    job_spec = {
        "commands": [
            {"cmd": ["/bin/false"]},
        ]}
    logger = MemoryLogger()
    with assert_raises(CalledProcessError):
        run_job.run_job(logger, build_store, job_spec, {}, {}, tempdir, cfg)

@build_store_fixture()
def test_log_pipe_stress(tempdir, sc, build_store, cfg):
    # Stress-test the log piping a bit, since the combination of Unix FIFO
    # pipes and poll() is a bit tricky to get right.

    # We want to launch many clients who each concurrently send many messages,
    # then check that they all get through to the MemoryLogger(). We do this by
    # writing out two Python scripts and executing them...
    NJOBS = 5
    NMSGS = 300 # must divide 2
    
    with open(pjoin(tempdir, 'client.py'), 'w') as f:
        f.write(dedent('''\
        import os, sys
        msg = sys.argv[1] * (256 // 4) # less than PIPE_BUF, more than what we set BUFSIZE to
        for i in range(int(sys.argv[2]) // 2):
            with open(os.environ["LOG"], "a") as f:
                f.write("%s\\n" % msg)
                f.write("%s\\n" % msg)
            # hit stdout too
            sys.stdout.write("stdout:%s\\nstdout:%s\\n" % (sys.argv[1], sys.argv[1]))
            sys.stdout.flush()
            sys.stderr.write("stderr:%s\\nstderr:%s\\n" % (sys.argv[1], sys.argv[1]))
            sys.stderr.flush()
        '''))

    with open(pjoin(tempdir, 'launcher.py'), 'w') as f:
        f.write(dedent('''\
        import sys
        import subprocess
        procs = [subprocess.Popen([sys.executable, sys.argv[1], '%4d' % i, sys.argv[3]]) for i in range(int(sys.argv[2]))]
        for p in procs:
            if not p.wait() == 0:
                raise AssertionError("process failed: %d" % p.pid)
        '''))

    job_spec = {
        "commands": [
            {"hit": ["logpipe", "mylog", "WARNING"], "to_var": "LOG"},
            {"cmd": [sys.executable, pjoin(tempdir, 'launcher.py'), pjoin(tempdir, 'client.py'), str(NJOBS), str(NMSGS)]},
        ]}
    logger = MemoryLogger()
    old = run_job.LOG_PIPE_BUFSIZE
    try:
        run_job.LOG_PIPE_BUFSIZE = 50
        run_job.run_job(logger, build_store, job_spec, {}, {}, tempdir, cfg)
    finally:
        run_job.LOG_PIPE_BUFSIZE = old

    log_bins = [0] * NJOBS
    stdout_bins = [0] * NJOBS
    stderr_bins = [0] * NJOBS
    for line in logger.lines:
        parts = line.split(':')
        if len(parts) != 3:
            continue
        level, log, msg = parts
        if log == 'mylog':
            assert level == 'WARNING'
            assert msg == msg[:4] * (256 // 4)
            idx = int(msg[:4])
            log_bins[idx] += 1
        elif log == 'stdout':
            assert level == 'DEBUG'
            stdout_bins[int(msg)] += 1
        elif log == 'stderr':
            assert level == 'DEBUG'
            stderr_bins[int(msg)] += 1
    assert all(x == NMSGS for x in log_bins)
    assert all(x == NMSGS for x in stdout_bins)
    assert all(x == NMSGS for x in stderr_bins)
    
@build_store_fixture()
def test_notimplemented_redirection(tempdir, sc, build_store, cfg):
    job_spec = {
        "commands": [
            {"hit": ["logpipe", "mylog", "WARNING"], "to_var": "log"},
            {"cmd": ["/bin/echo", "my warning"], "append_to_file": "$log"}
        ]}
    with assert_raises(NotImplementedError):
        logger = MemoryLogger()
        run_job.run_job(logger, build_store, job_spec, {}, {}, tempdir, cfg)

@build_store_fixture()
def test_script_cwd(tempdir, sc, build_store, cfg):
    os.makedirs(pjoin(tempdir, 'a', 'b', 'c'))
    job_spec = {
        "commands": [
            {"cwd": "a",
             "commands": [
                 {"cwd": "b",
                  "commands": [
                      {"cwd": "c",
                       "commands": [
                          {"cmd": ["/bin/pwd"], "append_to_file": "out", "cwd": ".."}
                           ]}]}]}]}
    logger = MemoryLogger()
    run_job.run_job(logger, build_store, job_spec, {}, {}, tempdir, cfg)
    assert os.path.exists(pjoin(tempdir, 'a', 'b', 'out'))
    with open(pjoin(tempdir, 'a', 'b', 'out')) as f:
        assert f.read().strip() == pjoin(tempdir, 'a', 'b')


def test_substitute():
    env = {"A": "a", "B": "b"}
    def check(want, x):
        eq_(want, run_job.substitute(x, env))
    def check_raises(x):
        with assert_raises(KeyError):
            run_job.substitute(x, env)
    yield check, "ab", "$A$B"
    yield check, "ax", "${A}x"
    yield check, "\\", "\\"
    yield check, "\\\\", "\\\\"
    yield check, "a$${x}", "${A}\$\${x}"
    yield check_raises, "$Ax"
    yield check_raises, "$$"

def test_stable_topological_sort():
    def check(expected, problem):
        # pack simpler problem description into objects
        problem_objs = [dict(id=id, before=before, preserve=id[::-1])
                        for id, before in problem]
        got = run_job.stable_topological_sort(problem_objs)
        got_ids = [x['id'] for x in got]
        assert expected == got_ids
        for obj in got:
            assert obj['preserve'] == obj['id'][::-1]
    
    problem = [
        ("t-shirt", []),
        ("sweater", ["t-shirt"]),
        ("shoes", []),
        ("space suit", ["sweater", "socks", "underwear"]),
        ("underwear", []),
        ("socks", []),
        ]

    check(['shoes', 'space suit', 'sweater', 't-shirt', 'underwear', 'socks'], problem)
    # change order of two leaves
    problem[-2], problem[-1] = problem[-1], problem[-2]
    check(['shoes', 'space suit', 'sweater', 't-shirt', 'socks', 'underwear'], problem)
    # change order of two roots (shoes and space suit)
    problem[2], problem[3] = problem[3], problem[2]
    check(['space suit', 'sweater', 't-shirt', 'socks', 'underwear', 'shoes'], problem)

    # error conditions
    with assert_raises(ValueError):
        # repeat element
        check([], problem + [("socks", [])])

    with assert_raises(ValueError):
        # cycle
        check([], [("x", ["y"]), ("y", ["x"])])

