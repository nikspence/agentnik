"""Isolated subagent artifacts, published only after a successful child run."""
from pathlib import Path
from .code_limits import FULL_TEXT_BYTES

MAX_FILES = 64
MAX_TOTAL = 32_000_000

class StagedOutputs:
    def __init__(self, files, output_dir, images=()):
        self.files=files
        self.output_dir=output_dir
        self.root=files.path(output_dir)
        if self.root==files.root:raise ValueError('Choose a subdirectory for child outputs')
        if self.root.exists() and not self.root.is_dir():raise ValueError('Output directory is not a directory')
        self.images={path:data for path,data,_ in images}
        self.entries={}

    def _path(self, relative):
        if not isinstance(relative,str) or not relative or Path(relative).is_absolute() or '..' in Path(relative).parts:raise ValueError('Use a relative path within the assigned output directory')
        target=self.files.path(str(Path(self.output_dir)/relative))
        if target==self.root:raise ValueError('Choose an output file')
        try:target.relative_to(self.root)
        except ValueError:raise ValueError('Output path is outside the assigned directory') from None
        if target.name.casefold()=='agents.md':raise ValueError('Subagents cannot write project instructions')
        return target

    def _stage(self, relative, data):
        target=self._path(relative)
        if target.exists():raise ValueError('Output already exists; choose a new path')
        key=target.relative_to(self.root).as_posix()
        if key not in self.entries and len(self.entries)>=MAX_FILES:raise ValueError('Too many output files')
        if sum(len(value) for name,value in self.entries.items() if name!=key)+len(data)>MAX_TOTAL:raise ValueError('Staged output is too large')
        self.entries[key]=data
        return {'path':target.relative_to(self.files.root).as_posix(),'bytes':len(data),'staged':True}

    def write(self, relative, content):
        if not isinstance(content,str) or '\x00' in content or len(content.encode('utf-8'))>FULL_TEXT_BYTES:raise ValueError('Output must be UTF-8 text within the file limit')
        return self._stage(relative,content.encode('utf-8'))

    def copy_image(self, source, relative):
        if source not in self.images:raise ValueError('Image is not an approved snapshot')
        return self._stage(relative,self.images[source])

    def crop_image(self, source, relative, x, y, width, height):
        if source not in self.images:raise ValueError('Image is not an approved snapshot')
        if Path(relative).suffix.lower()!='.png':raise ValueError('Cropped visual assets must use PNG')
        try: x,y,width,height=(int(value) for value in (x,y,width,height))
        except (ValueError,TypeError):raise ValueError('Crop coordinates must be integers') from None
        from PySide6.QtGui import QImage
        from PySide6.QtCore import QByteArray,QBuffer,QIODevice
        image=QImage.fromData(self.images[source])
        if image.isNull() or x<0 or y<0 or width<=0 or height<=0 or x+width>image.width() or y+height>image.height():raise ValueError('Crop must fit inside the approved image')
        data=QByteArray();buffer=QBuffer(data);buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.copy(x,y,width,height).save(buffer,'PNG'):raise ValueError('Could not encode cropped image')
        buffer.close()
        return self._stage(relative,bytes(data))

    def publish(self, check):
        from .code_agent import _EDIT_LOCK
        applied=[]
        with _EDIT_LOCK:
            # Validate all targets before creating anything.
            for name in self.entries:
                target=self._path(name)
                if target.exists():raise ValueError('A staged output already exists: '+name)
            try:
                for name,data in self.entries.items():
                    check();target=self._path(name)
                    missing=[];parent=target.parent
                    while not parent.exists():missing.append(parent);parent=parent.parent
                    if not parent.is_dir():raise ValueError('Output parent is unavailable')
                    for directory in reversed(missing):
                        check();self.files.path(str(directory.relative_to(self.files.root))).mkdir()
                    check();target=self._path(name)
                    with target.open('xb') as stream:
                        applied.append(target.relative_to(self.files.root).as_posix())
                        if stream.write(data)!=len(data):raise OSError('Incomplete output write')
            except Exception as exc:
                raise RuntimeError('Output publication stopped; files already created: '+(', '.join(applied) or 'none')+'. '+str(exc)) from exc
        return applied
