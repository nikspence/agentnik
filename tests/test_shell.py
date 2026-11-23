"""Local, temporary tests for approved command process handling."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from agentnik import shell
from agentnik.tools import Limits,Runtime,LimitError


class RetryingTemporaryDirectory(tempfile.TemporaryDirectory):
    def cleanup(self):
        # Windows can briefly retain a terminated process's working directory.
        deadline=time.monotonic()+5
        while True:
            try:return super().cleanup()
            except PermissionError:
                if time.monotonic()>=deadline:raise
                time.sleep(.05)


class ShellExecutor(unittest.TestCase):
    def test_goal_deadline_stops_running_command_and_retains_prior_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);runtime=Runtime(limits=Limits(turn_seconds=90));out=[]
            command="Set-Content -LiteralPath 'started.txt' -Value 'yes'; Start-Sleep -Seconds 60; Set-Content -LiteralPath 'late.txt' -Value 'no'" if os.name=='nt' else "printf yes > started.txt; sleep 60; printf no > late.txt"
            def run():
                try:shell.execute(command,directory,runtime)
                except Exception as exc:out.append(exc)
            thread=threading.Thread(target=run);thread.start()
            try:
                deadline=time.monotonic()+45
                while not (root/'started.txt').exists() and thread.is_alive() and time.monotonic()<deadline:time.sleep(.05)
                self.assertTrue((root/'started.txt').exists(),'Shell did not start the command')
                runtime.external_deadline=time.monotonic()+.2;thread.join(5)
                self.assertFalse(thread.is_alive());self.assertEqual(len(out),1);self.assertIsInstance(out[0],LimitError)
                self.assertIn('goal time limit',str(out[0]));self.assertFalse((root/'late.txt').exists())
            finally:
                runtime.cancel.set();thread.join(5)

    def test_shell_uses_run_deadline_not_request_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Runtime(limits=Limits(request_seconds=.1,turn_seconds=45))
            command="Start-Sleep -Milliseconds 400; Write-Output 'done'" if os.name=='nt' else "sleep 0.4; printf done"
            result=shell.execute(command,directory,runtime)
            self.assertEqual(result['exit_code'],0);self.assertIn('done',result['output'])

    def test_output_is_bounded_and_environment_omits_credentials(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'AGENTNIK_TEST_KEY':'secret-value'}):
            command="Write-Output 'shell-ok'; Write-Output ('x' * 40000)" if os.name=='nt' else "printf 'shell-ok\\n'; head -c 40000 /dev/zero | tr '\\0' x"
            result=shell.execute(command,directory,Runtime())
            self.assertEqual(result['exit_code'],0);self.assertIn('shell-ok',result['output'])
            self.assertTrue(result['truncated']);self.assertLessEqual(len(result['output'].encode()),shell.MAX_OUTPUT)
            self.assertNotIn('AGENTNIK_TEST_KEY',shell.snapshot_environment())

    @unittest.skipUnless(os.name=='nt','Windows job object process-tree check')
    def test_cancellation_stops_windows_child_process(self):
        import ctypes
        with RetryingTemporaryDirectory() as directory:
            pidfile=Path(directory)/'child.pid';escaped=str(pidfile).replace("'","''")
            command="$p = Start-Process -FilePath powershell.exe -ArgumentList '-NoProfile','-NonInteractive','-Command','Start-Sleep -Seconds 30' -PassThru; Set-Content -LiteralPath '"+escaped+"' -Value $p.Id; Start-Sleep -Seconds 30"
            runtime=Runtime();out=[]
            def run():
                try:shell.execute(command,directory,runtime)
                except Exception as exc:out.append(exc)
            thread=threading.Thread(target=run);thread.start()
            try:
                # Hosted Windows runners can take much longer to start both
                # PowerShell processes than a developer workstation.
                deadline=time.monotonic()+90
                while not pidfile.exists() and thread.is_alive() and time.monotonic()<deadline:time.sleep(.05)
                self.assertTrue(pidfile.exists(),f'Child PID file was not created; worker alive={thread.is_alive()}, errors={out!r}');pid=int(pidfile.read_text().strip());runtime.cancel.set();thread.join(5)
                self.assertFalse(thread.is_alive());self.assertIsInstance(out[0],InterruptedError)
                kernel=ctypes.WinDLL('kernel32',use_last_error=True)
                kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
                kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
                handle=kernel.OpenProcess(0x1000,False,pid);code=ctypes.c_ulong()
                try:self.assertFalse(handle and kernel.GetExitCodeProcess(handle,ctypes.byref(code)) and code.value==259)
                finally:
                    if handle:kernel.CloseHandle(handle)
            finally:
                runtime.cancel.set();thread.join(5)


if __name__=='__main__':unittest.main()
