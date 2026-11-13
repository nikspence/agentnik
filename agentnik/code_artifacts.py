"""Bounded coding notes and temporary tool-output artifacts."""
import re

MAX_NOTES = 32
MAX_NOTE_CHARS = 4000
MAX_ARTIFACTS = 32
MAX_ARTIFACT_CHARS = 200_000


def validate_notes(notes):
    if not isinstance(notes, dict) or len(notes) > MAX_NOTES:
        raise ValueError('Invalid working notes')
    for name, text in notes.items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_. -]{1,80}', name) or not name.strip():
            raise ValueError('Invalid working note name')
        if not isinstance(text, str) or len(text) > MAX_NOTE_CHARS:
            raise ValueError('Invalid working note text')
    return dict(notes)


class Artifacts:
    def __init__(self):
        self.items = {}
        self.next_id = 1

    def add(self, text, kind):
        if not isinstance(text, str) or len(text) > MAX_ARTIFACT_CHARS or len(self.items) >= MAX_ARTIFACTS:
            raise ValueError('Artifact storage limit reached')
        ident = 'A' + str(self.next_id); self.next_id += 1
        self.items[ident] = {'text':text, 'kind':kind}
        return {'id':ident, 'kind':kind, 'characters':len(text), 'preview':text[:500]}

    def read(self, ident, start, length):
        if ident not in self.items or not start.isdecimal() or not length.isdecimal():
            raise ValueError('Invalid artifact reference or range')
        start, length = int(start), int(length)
        if start < 0 or not 1 <= length <= 8000:
            raise ValueError('Artifact range must use a nonnegative offset and length 1–8000')
        text = self.items[ident]['text']
        return {'id':ident, 'offset':start, 'text':text[start:start+length], 'next_offset':min(len(text), start+length), 'characters':len(text)}

    def search(self, ident, query):
        if ident not in self.items or not query or len(query) > 200:
            raise ValueError('Invalid artifact reference or query')
        text=self.items[ident]['text'];matches=[];offset=0
        while len(matches)<20:
            index=text.find(query,offset)
            if index<0:break
            matches.append({'offset':index,'excerpt':text[max(0,index-80):min(len(text),index+len(query)+80)]})
            offset=index+len(query)
        return {'id':ident,'matches':matches,'more':text.find(query,offset)>=0}
