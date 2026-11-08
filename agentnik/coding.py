"""Coding approval contract and bounded simulation. No command/network executor."""
from dataclasses import dataclass,asdict
import hashlib
import json
import math
import re
import threading
import time
import uuid


def plain(value):
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]','',str(value))[:2048]


@dataclass(frozen=True)
class CommandProposal:
    run_id:str
    command_id:str
    argv:tuple
    cwd:str

    def __post_init__(self):
        if not all(isinstance(v,str) and 0<len(v)<=4096 for v in (self.run_id,self.command_id,self.cwd)):
            raise ValueError('Invalid command proposal identity or directory')
        if not isinstance(self.argv,tuple) or not self.argv or not self.argv[0] or len(self.argv)>64 or any(not isinstance(v,str) or '\x00' in v for v in self.argv):
            raise ValueError('Command arguments must be an immutable string tuple')
        if len(json.dumps(self.argv).encode())>4096:raise ValueError('Command argument budget exceeded')

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(asdict(self),sort_keys=True).encode()).hexdigest()


class SimulationRun:
    """One exact proposal per simulation; approval never enables an OS executor."""
    def __init__(self,cwd,seconds=60):
        if type(seconds) not in (int,float) or not math.isfinite(seconds) or not 0<seconds<=60:raise ValueError('Simulation deadline must be between 0 and 60 seconds')
        self.deadline=time.monotonic()+seconds
        self.run_id=uuid.uuid4().hex;self.cwd=cwd;self.cancel=threading.Event()
        self._decision=threading.Event();self._lock=threading.Lock();self.pending=None;self.answer=None;self.seconds=seconds

    def decide(self,fingerprint,approved):
        with self._lock:
            if self.cancel.is_set() or time.monotonic()>=self.deadline or self.pending is None or self.answer is not None or self.pending.fingerprint!=fingerprint:
                return False
            if type(approved) is not bool:return False
            self.answer=approved;self._decision.set();return True

    def stop(self):
        with self._lock:self.cancel.set();self.pending=None;self._decision.set()

    def run(self,emit):
        def event(kind,**data):
            if not self.cancel.is_set():emit(dict(run_id=self.run_id,kind=kind,**data))
        try:
            proposal=CommandProposal(self.run_id,uuid.uuid4().hex,('git','status','--short'),self.cwd)
            with self._lock:self.pending=proposal
            event('proposal',proposal=asdict(proposal),fingerprint=proposal.fingerprint,
                  recommendation='Not checked · simulation; no System One request was made')
            deadline=self.deadline
            while not self._decision.wait(.05):
                if self.cancel.is_set():return
                if time.monotonic()>=deadline:
                    event('finished',status='timed_out',text='Simulation approval timed out. No command ran.');return
            with self._lock:
                if self.cancel.is_set():return
                allowed=self.answer
            if not allowed:
                event('finished',status='rejected',text='Simulated step rejected. No command ran.');return
            event('output',text='SIMULATED: git status output would appear here. No process was started.')
            event('diff',text='SIMULATED DIFF (no file was created or changed)\n--- a/example.txt\n+++ b/example.txt\n@@ -1 +1 @@\n-old\n+proposed')
            event('finished',status='completed',text='Simulation completed. No command, file edit, or model request occurred.')
        finally:
            with self._lock:self.pending=None
