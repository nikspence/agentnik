"""Bounded, project-scoped long-term memory in Agentnik's local database."""
from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
import json
import sqlite3
import uuid

MAX_ENTRIES = 100


def validate_entry(entry):
    if not isinstance(entry,dict) or set(entry)!={'title','text','source','stale'}:
        raise ValueError('Memory must have title, text, source, and stale fields')
    for key,limit in (('title',120),('text',4000),('source',500)):
        if not isinstance(entry[key],str) or len(entry[key])>limit or (key!='source' and not entry[key].strip()):
            raise ValueError('Invalid memory '+key)
    if type(entry['stale']) is not bool:raise ValueError('Invalid stale flag')
    return dict(entry)


def digest(entry):
    return hashlib.sha256(json.dumps(entry,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()


class ProjectMemory:
    def __init__(self, database, project_id):
        self.database=str(database);self.project_id=project_id
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS project_memory (project_id TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, updated TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(project_id,id))')
            if 'created' not in {row[1] for row in db.execute('PRAGMA table_info(project_memory)')}:
                db.execute("ALTER TABLE project_memory ADD COLUMN created TEXT NOT NULL DEFAULT ''")
                db.execute("UPDATE project_memory SET created=updated WHERE created=''")

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.database, timeout=5)
        try:
            with db:yield db
        finally:db.close()

    def list(self):
        with self.connect() as db:
            rows=db.execute('SELECT id,payload,updated,created FROM project_memory WHERE project_id=? ORDER BY updated DESC,id',(self.project_id,)).fetchall()
        return [{'id':ident,**validate_entry(json.loads(payload)),'updated':updated,'created':created} for ident,payload,updated,created in rows]

    def search(self, query):
        if not isinstance(query,str) or len(query)>200:raise ValueError('Invalid memory search')
        words=query.casefold().split()
        return [{'id':e['id'],'title':e['title'],'source':e['source'],'stale':e['stale'],'updated':e['updated'],'created':e['created']} for e in self.list() if all(word in (e['title']+' '+e['text']+' '+e['source']).casefold() for word in words)][:30]

    def read(self, ident):
        return next((entry for entry in self.list() if entry['id']==ident),None)

    def save(self, entry, ident=None, expected=None):
        entry=validate_entry(entry);ident=ident or uuid.uuid4().hex
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM repositories WHERE id=?',(self.project_id,)).fetchone():raise ValueError('Project is no longer registered')
            row=db.execute('SELECT payload,created FROM project_memory WHERE project_id=? AND id=?',(self.project_id,ident)).fetchone()
            if expected is not None and (not row or digest(validate_entry(json.loads(row[0])))!=expected):raise ValueError('Memory changed since review')
            if row is None and db.execute('SELECT COUNT(*) FROM project_memory WHERE project_id=?',(self.project_id,)).fetchone()[0]>=MAX_ENTRIES:raise ValueError('Project memory limit reached')
            timestamp=datetime.now(timezone.utc).isoformat()
            db.execute('INSERT OR REPLACE INTO project_memory (project_id,id,payload,updated,created) VALUES (?,?,?,?,?)',(self.project_id,ident,json.dumps(entry,ensure_ascii=False),timestamp,row[1] if row else timestamp))
        return self.read(ident)

    def delete(self, ident, expected=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT payload FROM project_memory WHERE project_id=? AND id=?',(self.project_id,ident)).fetchone()
            if not row:raise ValueError('Memory not found')
            if expected is not None and digest(validate_entry(json.loads(row[0])))!=expected:raise ValueError('Memory changed since review')
            db.execute('DELETE FROM project_memory WHERE project_id=? AND id=?',(self.project_id,ident))
