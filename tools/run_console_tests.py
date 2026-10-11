#!/usr/bin/env python3
"""Run console regression tests with network and subprocess guards; no hardware."""
from pathlib import Path
import datetime,json,os,socket,subprocess,unittest

ROOT=Path(__file__).resolve().parents[1]
def main():
    os.chdir(ROOT/'outputs/Watcher控制台')
    os.environ['MPLCONFIGDIR']=str(ROOT/'work/watcher-control-runtime/matplotlib')
    os.environ['XDG_CACHE_HOME']=str(ROOT/'work/watcher-control-runtime/cache')
    original_connect=socket.socket.connect;original_bind=socket.socket.bind
    def check(address):
        if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1','localhost'):
            raise AssertionError('Only loopback tests allowed: '+repr(address))
    def connect(sock,address):check(address);return original_connect(sock,address)
    def bind(sock,address):check(address);return original_bind(sock,address)
    # Windows asyncio lazily subclasses Popen during test discovery. Keep a
    # class here while still rejecting every unmocked child-process launch.
    class ForbiddenPopen(subprocess.Popen):
        def __init__(self,*args,**kwargs):
            raise AssertionError('All test child processes must be mocked')
    socket.socket.connect=connect;socket.socket.bind=bind;subprocess.Popen=ForbiddenPopen
    suite=unittest.defaultTestLoader.discover('tests',pattern='test_*.py')
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    report={'verified_at':datetime.datetime.now().astimezone().isoformat(),'tests':result.testsRun,
            'failures':len(result.failures),'errors':len(result.errors),'verified':result.wasSuccessful(),
            'guards':['network restricted to loopback','unmocked subprocesses forbidden'],'hardware_access':False}
    destination=ROOT/'work/team-validation/console-tests.json'
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if result.wasSuccessful() else 1
if __name__=='__main__':raise SystemExit(main())
