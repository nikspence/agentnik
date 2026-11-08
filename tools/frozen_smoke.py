"""Windows frozen startup smoke: own Qt window, isolated DB, graceful exit."""
import argparse
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]


def smoke(executable, seconds=30):
    if os.name!='nt':raise ValueError('Frozen window smoke currently requires Windows')
    executable=Path(executable).resolve(strict=True)
    if seconds<=0:raise ValueError('Startup deadline must be positive')
    root=ROOT/'test-output';root.mkdir(exist_ok=True)
    data=Path(tempfile.mkdtemp(prefix='frozen-python-',dir=root))
    user32=ctypes.WinDLL('user32',use_last_error=True)
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user32.EnumWindows.argtypes=[callback_type,wintypes.LPARAM]
    user32.EnumWindows.restype=wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user32.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
    user32.PostMessageW.restype=wintypes.BOOL
    startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
    process=subprocess.Popen([str(executable),'--data-dir',str(data)],startupinfo=startup,
                             stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+seconds;handle=None
        @callback_type
        def find(window,unused):
            nonlocal handle
            owner=wintypes.DWORD();user32.GetWindowThreadProcessId(window,ctypes.byref(owner))
            if owner.value==process.pid:
                title=ctypes.create_unicode_buffer(256);user32.GetWindowTextW(window,title,256)
                if title.value=='Agentnik':handle=window
            return True
        while time.monotonic()<deadline:
            if process.poll() is not None:raise RuntimeError('Frozen executable exited before readiness')
            user32.EnumWindows(find,0)
            if handle and (data/'history.sqlite3').is_file():break
            time.sleep(.2)
        else:raise TimeoutError('Frozen Qt window/database did not initialize before deadline')
        if not user32.PostMessageW(handle,0x10,0,0):raise ctypes.WinError(ctypes.get_last_error())
        if process.wait(timeout=10)!=0:raise RuntimeError('Frozen executable returned a nonzero exit code')
        return {'window':'Agentnik','isolated_database':True,'exit_code':0,'data_directory':str(data)}
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=5)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('executable',type=Path);p.add_argument('--seconds',type=int,default=30)
    args=p.parse_args()
    try:smoke(args.executable,args.seconds)
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:p.exit(1,'Smoke failed: '+str(exc)+'\n')
    print('PASS: frozen Qt window, isolated database, and graceful exit code 0')


if __name__=='__main__':main()
