"""Bounded, explicitly approved shell execution; not an OS sandbox."""
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
from .tools import LimitError

MAX_OUTPUT = 32000
MAX_SECONDS = 60
ENVIRONMENT_KEYS = {'PATH','SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','TEMP','TMP','LANG','LC_ALL','LC_CTYPE','TERM'}
_ANSI = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[@-_])')


class WindowsJob:
    """Terminate the process tree on cancellation or when the job is closed."""
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        class Basic(ctypes.Structure):
            _fields_=[('PerProcessUserTimeLimit',ctypes.c_int64),('PerJobUserTimeLimit',ctypes.c_int64),('LimitFlags',wintypes.DWORD),('MinimumWorkingSetSize',ctypes.c_size_t),('MaximumWorkingSetSize',ctypes.c_size_t),('ActiveProcessLimit',wintypes.DWORD),('Affinity',ctypes.c_size_t),('PriorityClass',wintypes.DWORD),('SchedulingClass',wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_=[(name,ctypes.c_uint64) for name in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
        class Extended(ctypes.Structure):
            _fields_=[('BasicLimitInformation',Basic),('IoInfo',IO),('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR];self.kernel.CreateJobObjectW.restype=wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD];self.kernel.SetInformationJobObject.restype=wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE];self.kernel.AssignProcessToJobObject.restype=wintypes.BOOL
        self.kernel.CloseHandle.argtypes=[wintypes.HANDLE];self.kernel.CloseHandle.restype=wintypes.BOOL
        self.handle=self.kernel.CreateJobObjectW(None,None)
        if not self.handle:raise OSError(ctypes.get_last_error(),'Cannot create process job')
        info=Extended();info.BasicLimitInformation.LimitFlags=0x2000
        if not self.kernel.SetInformationJobObject(self.handle,9,ctypes.byref(info),ctypes.sizeof(info)):
            self.close();raise OSError(ctypes.get_last_error(),'Cannot configure process job')

    def assign(self,process):
        import ctypes
        if not self.kernel.AssignProcessToJobObject(self.handle,int(process._handle)):
            raise OSError(ctypes.get_last_error(),'Cannot isolate command process tree')

    def close(self):
        if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None


def shell_path():
    if os.name=='nt':return str(Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe')
    return '/bin/sh'


def snapshot_environment(secrets=()):
    return {key:value for key,value in os.environ.items() if key.upper() in ENVIRONMENT_KEYS and not any(secret and secret in value for secret in secrets)}


def execute(command,cwd,runtime,environment=None,program=None):
    """Execute with closed stdin, bounded captured output, and process-tree cleanup."""
    runtime.check();shell=program or shell_path()
    environment=snapshot_environment() if environment is None else dict(environment)
    argv=[shell,'-NoLogo','-NoProfile','-NonInteractive','-Command','-'] if os.name=='nt' else [shell,'-s']
    job=WindowsJob() if os.name=='nt' else None;process=None;reader=None;output=bytearray();truncated=[False]
    try:
        options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
        process=subprocess.Popen(argv,cwd=cwd,env=environment,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,**options)
        if job:job.assign(process)
        def drain():
            try:
                while True:
                    chunk=process.stdout.read(4096)
                    if not chunk:break
                    room=max(0,MAX_OUTPUT-len(output));output.extend(chunk[:room])
                    if len(chunk)>room:truncated[0]=True
            finally:process.stdout.close()
        reader=threading.Thread(target=drain,daemon=True);reader.start()
        runtime.check();process.stdin.write(command.encode('utf-8')+b'\n');process.stdin.close()
        deadline=time.monotonic()+min(MAX_SECONDS,runtime.timeout())
        while process.poll() is None:
            runtime.check()
            if time.monotonic()>=deadline:raise LimitError('Shell command time limit reached')
            runtime.cancel.wait(.05)
        code=process.returncode
    finally:
        if job:job.close()
        elif process:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        if process and process.poll() is None:
            try:process.kill()
            except (ProcessLookupError,PermissionError):pass
            process.wait(timeout=3)
        if reader:reader.join(timeout=3)
        elif process and process.stdout:process.stdout.close()
        if process and process.stdin and not process.stdin.closed:process.stdin.close()
    text=output.decode('utf-8','replace');text=_ANSI.sub('',text)
    text=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]','',text)
    return {'exit_code':code,'output':text,'truncated':truncated[0]}
