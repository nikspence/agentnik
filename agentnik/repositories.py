"""Local project registry; removing entries never modifies project files."""
import os
import re
from pathlib import Path
import time
import uuid


def validate_git_author(author):
    if author is None:return None
    if not isinstance(author,dict) or set(author)!={'name','email'}:raise ValueError('Enter both a Git author name and email, or leave both blank')
    name,email=author['name'],author['email']
    if not isinstance(name,str) or not isinstance(email,str):raise ValueError('Invalid Git author')
    name=name.strip();email=email.strip()
    if not name and not email:return None
    if not name or not email or len(name)>200 or len(email)>254 or any(ord(c)<32 or ord(c)==127 or c in '<>' for c in name+email) or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+',email):
        raise ValueError('Enter both a valid Git author name and email, or leave both blank')
    return {'name':name,'email':email}


class RepositoryRegistry:
    def __init__(self,store):
        self.store=store
        store.db.execute('CREATE TABLE IF NOT EXISTS repositories (id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL, updated REAL NOT NULL)')
        store.db.execute('CREATE TABLE IF NOT EXISTS repository_git_authors (repository_id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL)')
        store.db.commit()

    @staticmethod
    def directory(path):
        resolved=Path(path).expanduser().resolve(strict=True)
        if not resolved.is_dir() or not os.access(resolved,os.R_OK): raise ValueError('Choose an accessible project directory')
        return str(resolved)

    def list(self):
        return [dict(id=ident,name=name,path=path,available=Path(path).is_dir()) for ident,name,path in self.store.db.execute('SELECT id,name,path FROM repositories ORDER BY name COLLATE NOCASE')]

    def get(self,ident):
        return next((row for row in self.list() if row['id']==ident),None)

    def put(self,path,name=None,ident=None):
        path=self.directory(path)
        name=(name if name is not None else Path(path).name or path).strip()
        if not name or len(name)>160: raise ValueError('Use a project name of 1–160 characters')
        if ident is not None and self.get(ident) is None: raise ValueError('Project entry no longer exists')
        for row in self.list():
            if row['id']!=ident and os.path.normcase(str(Path(row['path']).resolve()))==os.path.normcase(path):
                raise ValueError('This directory is already registered')
        ident=ident or uuid.uuid4().hex
        self.store.db.execute('INSERT OR REPLACE INTO repositories VALUES (?,?,?,?)',(ident,name,path,time.time()));self.store.db.commit()
        return ident

    def rename(self,ident,name):
        row=self.get(ident)
        if not row: raise ValueError('Project entry no longer exists')
        name=name.strip()
        if not name or len(name)>160: raise ValueError('Use a project name of 1–160 characters')
        self.store.db.execute('UPDATE repositories SET name=?,updated=? WHERE id=?',(name,time.time(),ident));self.store.db.commit()

    def git_author(self,ident):
        row=self.store.db.execute('SELECT name,email FROM repository_git_authors WHERE repository_id=?',(ident,)).fetchone()
        return validate_git_author({'name':row[0],'email':row[1]}) if row else None

    def set_git_author(self,ident,author):
        if self.get(ident) is None:raise ValueError('Project entry no longer exists')
        author=validate_git_author(author)
        if author:self.store.db.execute('INSERT OR REPLACE INTO repository_git_authors VALUES (?,?,?)',(ident,author['name'],author['email']))
        else:self.store.db.execute('DELETE FROM repository_git_authors WHERE repository_id=?',(ident,))
        self.store.db.commit()

    def remove(self,ident):
        self.store.db.execute('DELETE FROM repository_git_authors WHERE repository_id=?',(ident,))
        self.store.db.execute('DELETE FROM repositories WHERE id=?',(ident,));self.store.db.commit()

    def session(self,ident):
        row=self.get(ident)
        if not row: raise ValueError('Choose a registered project')
        path=self.directory(row['path'])
        session=self.store.new_session('code',row['name'],{})
        session.update(version=4,title='Code · '+row['name'],project_id=ident,path_snapshot=path,project_name=row['name'])
        return session
