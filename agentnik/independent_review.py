"""Read and validate saved legacy review history."""
import hashlib
import json
import math
import re
import copy
from datetime import datetime
from urllib.parse import urlsplit


MAX_SOURCE_BYTES = 8000
RUBRIC_VERSION = 1
REVIEW_ROLES = frozenset(('comprehension', 'requirements', 'design', 'readiness', 'repository_fit', 'drift'))
FINDINGS_VERSION = 1
MAX_FINDINGS_RESPONSE_BYTES = 16000
MAX_FINDINGS = 10






def validate_review_batch_approved_at(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z',value):raise ValueError('Invalid review approval time')
    try:datetime.strptime(value,'%Y-%m-%dT%H:%M:%SZ')
    except ValueError:raise ValueError('Invalid review approval time') from None
    return value


def validate_track_context(value):
    if value is None:return None
    from .tracks import IDENTIFIER
    if not isinstance(value,dict) or set(value)!={'id','digest'} or not isinstance(value['id'],str) or not IDENTIFIER.fullmatch(value['id']) or not isinstance(value['digest'],str) or not re.fullmatch('[0-9a-f]{64}',value['digest']):raise ValueError('Invalid review track context')
    return dict(value)


def track_context_matches(files, value):
    context=validate_track_context(value)
    if context is None:return None
    try:
        from .track_execution import prepare_track
        return prepare_track(files,context['id'])['digest']==context['digest']
    except (OSError,ValueError,UnicodeError,TypeError):return False


def track_review_summary(files, track, history):
    """Summarize saved session and project review records for inspection."""
    from .track_execution import validate_runtime_track
    from .track_review_storage import read_sidecar
    selected=validate_runtime_track(track);history=validate_review_history(history);project=read_sidecar(files,selected['id']);records=[]
    for origin,record in [('session',record) for record in history]+[('project',record) for record in project['snapshots']]:
        relevant=[]
        for original in record['reviews']:
            context=original.get('track_context')
            if not context or context['id']!=selected['id']:continue
            review=copy.deepcopy(original)
            sources=[(review['path'],review['source_sha256'])]+[(item['path'],item['sha256']) for item in review['evidence']]
            review['track_revision_status']='matches' if context['digest']==selected['digest'] else 'changed'
            review['source_status']='matches' if sources_unchanged(files,sources) else 'stale_or_unavailable'
            for finding in review['structured']['findings']:
                finding['user_disposition']=copy.deepcopy(review['dispositions'].get(finding['id'],{'status':'unresolved','rationale':''}))
            relevant.append(review)
        if relevant:records.append({'origin':origin,'snapshot_id':record['id'],'reviews':relevant})
    return {'track_id':selected['id'],'track_digest':selected['digest'],'snapshots':records,
            'notice':'Session and project snapshots are listed separately; older or unsaved reviews may be missing. Findings are untrusted. A run-context match does not mean the full track was reviewed.'}


def track_review_overview(summary):
    """Count recorded states without inferring a review verdict or missing work."""
    snapshots=summary['snapshots'];reviews=[review for snapshot in snapshots for review in snapshot.get('reviews',[])]
    return {'snapshots':len(snapshots),'passes':len(reviews),
            'completed':sum(review.get('pass_status','completed')=='completed' for review in reviews),
            'incomplete':sum(review.get('pass_status','completed')!='completed' for review in reviews),
            'invalid_output':sum(review.get('pass_status','completed')=='completed' and review['structured']['status']!='valid' for review in reviews),
            'stale_sources':sum(review.get('pass_status')=='stale' or review['source_status']!='matches' for review in reviews),
            'changed_tracks':sum(review['track_revision_status']!='matches' for review in reviews),
            'unresolved':sum(finding.get('user_disposition',{}).get('status','unresolved')=='unresolved' for review in reviews for finding in review['structured']['findings'])}


def validate_review_measurements(value):
    """Validate optional completed-pass measurements without estimating missing usage."""
    if not isinstance(value,dict) or set(value)!={'input_tokens','output_tokens','elapsed_seconds'}:raise ValueError('Invalid review measurements')
    for key,number in value.items():
        if number is None and key!='elapsed_seconds':continue
        if type(number) not in (int,float) or not 0<=number<=2**63-1 or (type(number) is float and not math.isfinite(number)):raise ValueError('Invalid review measurements')
    return dict(value)






def validate_review_endpoint_identity(value):
    if not isinstance(value,dict) or set(value)!={'protocol','origin'} or value['protocol'] not in ('chat','messages','responses'):raise ValueError('Invalid review endpoint identity')
    origin=value['origin']
    if origin is not None:
        if not isinstance(origin,str) or len(origin)>300 or not re.fullmatch(r'https?://(?:[a-z0-9.-]+|\[[0-9a-f:.]+\])(?::[0-9]{1,5})?',origin):raise ValueError('Invalid review endpoint identity')
        try:
            parsed=urlsplit(origin)
            if not parsed.hostname or (parsed.port is not None and not 1<=parsed.port<=65535):raise ValueError('Invalid review endpoint identity')
        except ValueError:raise ValueError('Invalid review endpoint identity') from None
    return dict(value)


def validate_review_history(history):
    """Validate explicitly saved, bounded session snapshots without reading files."""
    if not isinstance(history, list) or len(history) > 10 or len(json.dumps(history, ensure_ascii=True).encode('utf-8')) > 256000:
        raise ValueError('Invalid saved review history')
    seen=set()
    for record in history:
        if not isinstance(record, dict) or set(record)!={'version','id','track_id','reviews'} or type(record['version']) is not int or record['version']!=1 or not isinstance(record['id'],str) or not re.fullmatch('[0-9a-f]{32}',record['id']) or record['id'] in seen:
            raise ValueError('Invalid saved review record')
        seen.add(record['id'])
        if record['track_id'] is not None:
            from .tracks import IDENTIFIER
            if not isinstance(record['track_id'],str) or not IDENTIFIER.fullmatch(record['track_id']):raise ValueError('Invalid saved review track')
        reviews=record['reviews']
        if not isinstance(reviews,list) or not 1<=len(reviews)<=32:raise ValueError('Invalid saved reviews')
        review_ids=set()
        for review in reviews:
            required={'id','role','model','path','source_sha256','payload_sha256','evidence','structured','dispositions'}
            if not isinstance(review,dict) or not required<=set(review) or set(review)-required-{'pass_status','track_context','measurements','reason','rubric_version','endpoint','target_payload_sha256','batch_approved_at'}:raise ValueError('Invalid saved review')
            if 'batch_approved_at' in review:validate_review_batch_approved_at(review['batch_approved_at'])
            if 'target_payload_sha256' in review and (not isinstance(review['target_payload_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',review['target_payload_sha256'])):raise ValueError('Invalid transmitted document hash')
            if 'rubric_version' in review and (type(review['rubric_version']) is not int or not 1<=review['rubric_version']<=RUBRIC_VERSION):raise ValueError('Unsupported review rubric version')
            if 'endpoint' in review:validate_review_endpoint_identity(review['endpoint'])
            validate_track_context(review.get('track_context'))
            status=review.get('pass_status','completed')
            if status not in ('completed','failed','cancelled','stale','skipped','interrupted'):raise ValueError('Invalid saved review status')
            if 'reason' in review and (status=='completed' or not isinstance(review['reason'],str) or not 0<len(review['reason'])<=500):raise ValueError('Invalid saved review reason')
            if 'measurements' in review:
                if status!='completed':raise ValueError('Measurements require a completed review')
                validate_review_measurements(review['measurements'])
            if not isinstance(review['id'],str) or not re.fullmatch(r'[0-9a-f]{32}-[1-3]',review['id']) or review['id'] in review_ids or not isinstance(review['role'],str) or review['role'] not in REVIEW_ROLES:raise ValueError('Invalid saved review identity')
            review_ids.add(review['id'])
            if any(not isinstance(review[k],str) or not 0<len(review[k])<=4096 for k in ('model','path')) or any(not isinstance(review[k],str) or not re.fullmatch('[0-9a-f]{64}',review[k]) for k in ('source_sha256','payload_sha256')):raise ValueError('Invalid saved review metadata')
            evidence=review['evidence']
            if not isinstance(evidence,list) or len(evidence)>3:raise ValueError('Invalid saved evidence')
            for item in evidence:
                if not isinstance(item,dict) or set(item)!={'path','sha256','payload_sha256'} or not isinstance(item['path'],str) or not 0<len(item['path'])<=512 or any(not isinstance(item[k],str) or not re.fullmatch('[0-9a-f]{64}',item[k]) for k in ('sha256','payload_sha256')):raise ValueError('Invalid saved evidence')
            structured=review['structured']
            if not isinstance(structured,dict) or set(structured)!={'status','findings'} or structured['status'] not in ('valid','invalid','truncated','too_large','not_available') or not isinstance(structured['findings'],list):raise ValueError('Invalid saved findings')
            if (status=='completed')==(structured['status']=='not_available'):raise ValueError('Saved review status does not match findings')
            findings=structured['findings']
            if structured['status']=='valid':
                if any(not isinstance(item,dict) or item.get('id')!='finding-'+str(index) for index,item in enumerate(findings,1)):raise ValueError('Invalid finding id')
                raw=[{k:v for k,v in item.items() if k!='id'} for item in findings]
                if parse_structured_findings(json.dumps({'version':1,'findings':raw},ensure_ascii=False))!=structured:raise ValueError('Invalid saved findings')
            elif findings:raise ValueError('Invalid saved findings')
            dispositions=review['dispositions'];valid_ids={item['id'] for item in findings}
            if not isinstance(dispositions,dict) or set(dispositions)-valid_ids:raise ValueError('Invalid saved dispositions')
            for entry in dispositions.values():
                if not isinstance(entry,dict) or set(entry)!={'status','rationale'} or entry['status'] not in ('unresolved','accepted','contested','deferred') or not isinstance(entry['rationale'],str) or len(entry['rationale'])>500:raise ValueError('Invalid saved disposition')
    return copy.deepcopy(history)


def parse_structured_findings(text, *, truncated=False):
    """Validate saved structured findings without accepting partial records."""
    if type(truncated) is not bool or not isinstance(text, str):
        raise ValueError('Invalid structured review response')
    if truncated:
        return {'status': 'truncated', 'findings': []}
    try:
        if len(text.encode('utf-8')) > MAX_FINDINGS_RESPONSE_BYTES:
            return {'status': 'too_large', 'findings': []}
        def unique_object(pairs):
            obj = {}
            for key, value in pairs:
                if key in obj: raise ValueError('Duplicate JSON key')
                obj[key] = value
            return obj
        data = json.loads(text, object_pairs_hook=unique_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid JSON constant')))
        if not isinstance(data, dict) or set(data) != {'version', 'findings'} or type(data['version']) is not int or data['version'] != FINDINGS_VERSION:
            raise ValueError('Invalid response version')
        findings = data['findings']
        if not isinstance(findings, list) or len(findings) > MAX_FINDINGS:
            raise ValueError('Invalid findings')
        result = []
        fields = {'severity', 'title', 'rationale', 'location', 'assumptions', 'verification'}
        limits = {'title': 160, 'rationale': 2000, 'location': 500, 'assumptions': 1000, 'verification': 1000}
        for index, item in enumerate(findings, 1):
            if not isinstance(item, dict) or set(item) != fields or item['severity'] not in ('high', 'medium', 'low', 'unknown'):
                raise ValueError('Invalid finding')
            for field, limit in limits.items():
                value = item[field]
                if not isinstance(value, str) or len(value) > limit or (field in ('title', 'rationale') and not value.strip()):
                    raise ValueError('Invalid finding text')
            result.append({'id': 'finding-'+str(index), **item})
        return {'status': 'valid', 'findings': result}
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return {'status': 'invalid', 'findings': []}




def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()




def sources_unchanged(files, sources):
    try:
        return all(digest(files.read(path, remember=False, max_bytes=MAX_SOURCE_BYTES)) == expected for path, expected in sources)
    except (OSError, ValueError, UnicodeError):
        return False
