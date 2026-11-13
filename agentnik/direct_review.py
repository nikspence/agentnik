"""User-configured independent review runs using the normal approval boundary."""
import json
import threading
import uuid

from . import core, compat_tools, ollama_tools, responses_tools
from .code_agent import CodingRun, ProjectFiles, REVIEW_RUBRICS
from .independent_review import STRUCTURED_INSTRUCTIONS, DRIFT_REVIEW_INSTRUCTIONS, REPOSITORY_FIT_INSTRUCTIONS, RUBRIC_VERSION, execute_review_batch, parse_structured_findings, prepare_snapshot, review_endpoint_identity, review_batch_approved_at
from .research import scrub
from .tools import Limits, Runtime


class DirectReviewRun(CodingRun):
    direct_review = True

    def __init__(self, root, target, definitions, models, *, limits=None, selected_track=None, extra_secrets=(), save_progress=False):
        if not isinstance(target,str) or not target or not isinstance(definitions,list) or not 1<=len(definitions)<=3:
            raise ValueError('Choose a document and one to three review passes')
        if not isinstance(models,dict) or not models:
            raise ValueError('Configure at least one reviewer model')
        for item in definitions:
            if not isinstance(item,dict) or set(item)!={'role','model','paths'} or not isinstance(item['role'],str) or item['role'] not in (*REVIEW_RUBRICS,'drift','repository_fit') or not isinstance(item['model'],str) or item['model'] not in models or not isinstance(item['paths'],list) or len(item['paths'])>3 or any(not isinstance(p,str) or not p for p in item['paths']) or (item['role']=='comprehension' and item['paths']) or (item['role'] in ('drift','repository_fit') and not item['paths']):
                raise ValueError('Invalid review pass or evidence selection')
        self.definitions=[{'role':item['role'],'model':item['model'],'paths':list(item['paths'])} for item in definitions]
        self.models={key:dict(value) for key,value in models.items()};self.target=target
        if type(save_progress) is not bool:raise ValueError('Invalid review progress setting')
        self.save_progress=save_progress
        self.extra_secrets=[value for value in extra_secrets if isinstance(value,str) and value]
        super().__init__(next(iter(self.models.values())),root,'',limits=limits,selected_track=selected_track)

    def run(self, emit):
        runtime=Runtime(self.cancel,Limits(argument_bytes=1000000,model_bytes=2000000,request_seconds=45,**{k:v for k,v in self.limits.items() if k!='model_seconds'}))
        secrets=[connection.get('api_key','') for connection in self.models.values()]+self.extra_secrets
        def scrub_values(value):
            if isinstance(value,dict):return {key:scrub_values(item) for key,item in value.items()}
            if isinstance(value,list):return [scrub_values(item) for item in value]
            return scrub(value,secrets)
        def event(kind,**data):
            runtime.check();emit(dict(run_id=self.run_id,kind=kind,**scrub_values(data)))
        try:
            files=ProjectFiles(self.root);passes=[]
            if self.selected_track:
                from .track_execution import prepare_track
                if prepare_track(files,self.selected_track['id'],secrets,runtime.limits.context_bytes)!=self.selected_track:raise ValueError('Selected track changed; review it and start again')
            for index,item in enumerate(self.definitions,1):
                connection=self.models[item['model']]
                rubric=DRIFT_REVIEW_INSTRUCTIONS if item['role']=='drift' else REPOSITORY_FIT_INSTRUCTIONS if item['role']=='repository_fit' else REVIEW_RUBRICS[item['role']]
                snapshot=prepare_snapshot(files,self.target,STRUCTURED_INSTRUCTIONS+rubric,secrets,json.dumps(item['paths']) if item['paths'] else None,lambda:runtime.charge('calls',1,runtime.limits.calls))
                proposal={'operation':'independent_review','role':item['role'],'cwd':str(files.root),'path':self.target,'model':connection['model'],'destination':core.endpoint(connection).split('?',1)[0],'diff':snapshot['prompt'],'source_sha256':snapshot['source_sha256'],'target_payload_sha256':snapshot['target_payload_sha256'],'evidence':snapshot['evidence'],'payload_sha256':snapshot['payload_sha256'],'payload_bytes':snapshot['payload_bytes'],'batch_pass':index}
                passes.append({'approved':False,'connection':connection,'proposal':proposal,'snapshot':snapshot})
            for item in passes:
                if not self.review(item['proposal'],lambda e:event(e.pop('kind'),**e),runtime,'operation_proposal'):
                    raise ValueError('Review rejected; no reviewer requests were sent')
                item['approved']=True
            if self.selected_track and prepare_track(files,self.selected_track['id'],secrets,runtime.limits.context_bytes)!=self.selected_track:raise ValueError('Selected track changed during approval; review it and start again')
            batch_approved_at=review_batch_approved_at()
            batch=uuid.uuid4().hex;ids=[batch+'-'+str(i+1) for i in range(len(passes))];cancellations=[threading.Event() for _ in passes]
            track_context={'id':self.selected_track['id'],'digest':self.selected_track['digest']} if self.selected_track else None
            def review_record(index,status,structured):
                proposal=passes[index]['proposal']
                return {'id':ids[index],'role':proposal['role'],'rubric_version':RUBRIC_VERSION,'batch_approved_at':batch_approved_at,'endpoint':review_endpoint_identity(passes[index]['connection'],secrets),'model':proposal['model'],'path':self.target,'source_sha256':proposal['source_sha256'],'target_payload_sha256':proposal['target_payload_sha256'],'payload_sha256':proposal['payload_sha256'],'evidence':proposal['evidence'],'track_context':track_context,'pass_status':status,'structured':structured}
            if self.save_progress:
                event('independent_review_manifest',snapshot_id=self.run_id,reviews=[review_record(i,'pending',{'status':'not_available','findings':[]}) for i in range(len(passes))])
                while not self.manifest_ack.wait(.05):runtime.check()
                runtime.check()
                if not self.manifest_saved:raise ValueError('Could not save review progress; no reviewer requests were sent')
            with self.lock:
                for ident,cancel in zip(ids,cancellations):self.child_cancellations[ident]=cancel
            def review_event(index,status,structured,measurements=None,reason=None):
                record=review_record(index,status,structured)
                if measurements is not None:record['measurements']=measurements
                if reason is not None:record['reason']=reason
                event('independent_review_result',review=record)
            for index,item in enumerate(passes):
                review_event(index,'pending',{'status':'not_available','findings':[]})
                event('subagent',subagent={'id':ids[index],'status':'running','text':'Independent '+item['proposal']['role']+' review queued · '+item['proposal']['model']})
            def send(connection,body,child):
                adapter=responses_tools if connection.get('protocol')=='responses' else ollama_tools if core.native_ollama(connection) else compat_tools
                state={};_,calls=adapter.request(connection,body,child,lambda _:None,state)
                if calls:raise ValueError('Reviewer requested unavailable tools')
                return {'text':state.get('text',''),'usage':state.get('metrics',{})}
            def completed(index,outcome):
                structured=parse_structured_findings(outcome['analysis'],truncated=outcome['truncated']) if outcome['status']=='completed' else {'status':'not_available','findings':[]}
                measurements={**outcome['usage'],'elapsed_seconds':outcome['elapsed_seconds']} if outcome['status']=='completed' else None
                review_event(index,outcome['status'],structured,measurements,outcome.get('reason'))
                proposal=passes[index]['proposal'];usage=outcome.get('usage',{});detail=' · input '+str(usage.get('input_tokens') if usage.get('input_tokens') is not None else 'unknown')+' tokens, output '+str(usage.get('output_tokens') if usage.get('output_tokens') is not None else 'unknown')+' tokens'
                if measurements is not None:detail+=' · '+str(measurements['elapsed_seconds'])+'s'
                text='Independent '+proposal['role']+' review · '+proposal['model']+' · '+outcome['status']+' · '+structured['status']+detail+' · '+(outcome.get('analysis') or outcome.get('reason',''))[:900]
                event('subagent',subagent={'id':ids[index],'status':outcome['status'] if outcome['status'] in ('completed','failed','cancelled') else 'failed','text':text[:1600]});event('output',text=text[:1600])
            try:results=execute_review_batch(files,passes,runtime,send,cancellations,model_timeout=self.limits['model_seconds'],secrets=secrets,on_complete=completed)
            finally:
                with self.lock:
                    for ident in ids:self.child_cancellations.pop(ident,None)
            event('finished',status='completed',text='Independent review finished. Findings are untrusted; inspect each pass status.',usage='Review passes: '+str(len(results)))
        except Exception as exc:
            if not self.cancel.is_set():
                message=scrub(str(exc),secrets)[:500]
                emit({'run_id':self.run_id,'kind':'finished','status':'failed','text':'Independent review stopped: '+message})
        finally:runtime.closed=True
