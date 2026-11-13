"""Plan or build a non-overwriting Windows onedir archive. Never tags/publishes."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from agentnik import __version__
from tools.live_compat import revision
from tools.frozen_smoke import smoke

PINNED={'PyYAML':'6.0.3','PySide6':'6.12.0','keyring':'25.7.0','dulwich':'0.25.2','regex':'2026.9.29','tree-sitter':'0.26.1','tree-sitter-javascript':'0.25.0','tree-sitter-typescript':'0.23.2','tree-sitter-go':'0.25.0','tree-sitter-rust':'0.24.2','tree-sitter-c-sharp':'0.23.5','tree-sitter-java':'0.23.5','pyinstaller':'6.22.3','pyinstaller-hooks-contrib':'2026.9'}


def clean_environment():
    config=Path(sys.prefix)/'pyvenv.cfg'
    if sys.prefix==sys.base_prefix or not config.is_file():
        raise ValueError('Use a dedicated build virtual environment')
    settings={key.strip().lower():value.strip().lower() for key,value in (line.split('=',1) for line in config.read_text().splitlines() if '=' in line)}
    if settings.get('include-system-site-packages')!='false':
        raise ValueError('Build environment must disable system site packages')
    for package,version in PINNED.items():
        if importlib.metadata.version(package)!=version:
            raise ValueError('Install the versions in requirements-build.txt')


def package_bundle(bundle, archive, metadata):
    """Package only the explicit onedir tree; validate archive integrity/contents."""
    required=['Agentnik.exe','LICENSE','README.md','VALIDATION.md','RELEASE_NOTES.md','DISCLAIMER.md','BUILD-MANIFEST.json','THIRD_PARTY_LICENSES']
    for name in required:
        if not (bundle/name).exists(): raise ValueError('Missing bundle component: '+name)
    if archive.exists() or archive.with_suffix(archive.suffix+'.sha256').exists(): raise ValueError('Archive/checksum already exists')
    if json.loads((bundle/'BUILD-MANIFEST.json').read_text(encoding='utf-8'))!=metadata: raise ValueError('Build manifest mismatch')
    assets=bundle/'_internal'/'agentnik'/'assets'
    for asset in (ROOT/'agentnik'/'assets').iterdir():
        if asset.suffix in ('.svg','.png','.ico') and not (assets/asset.name).is_file(): raise ValueError('Missing packaged branding asset')
    catalogs=bundle/'_internal'/'agentnik'/'translations'
    for catalog in (ROOT/'agentnik'/'translations').glob('*.qm'):
        packaged=catalogs/catalog.name
        if not packaged.is_file() or packaged.read_bytes()!=catalog.read_bytes(): raise ValueError('Missing or mismatched packaged translation catalog: '+catalog.name)
    if not (bundle/'_internal'/'PySide6'/'plugins'/'platforms'/'qwindows.dll').is_file(): raise ValueError('Missing Qt Windows platform plugin')
    if not any((bundle/'_internal'/'regex').glob('_regex*.pyd')):raise ValueError('Missing regex native module')
    for package in ('tree_sitter','tree_sitter_javascript','tree_sitter_typescript','tree_sitter_go','tree_sitter_rust','tree_sitter_c_sharp','tree_sitter_java'):
        if not any((bundle/'_internal'/package).glob('_binding*.pyd')):raise ValueError('Missing parser native module: '+package)
    files=list(bundle.rglob('*'))
    if any(path.is_symlink() for path in files): raise ValueError('Symlink in release bundle')
    for path in files:
        if path.is_file() and (path.suffix in ('.sqlite3','.log') or path.name=='.env'):
            raise ValueError('Unexpected local data file in release bundle')
    with archive.open('xb') as stream:
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as output:
            for path in sorted(files):
                if path.is_file(): output.write(path,Path('Agentnik')/path.relative_to(bundle))
    with zipfile.ZipFile(archive) as result:
        if result.testzip() is not None: raise ValueError('Archive integrity check failed')
        for name in required[:-1]:
            if 'Agentnik/'+name not in result.namelist(): raise ValueError('Archive contents check failed')
    with archive.open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
    with archive.with_suffix(archive.suffix+'.sha256').open('x',encoding='utf-8') as output:
        output.write(digest+'  '+archive.name+'\n')
    return digest


def copy_notices(bundle):
    notices=bundle/'THIRD_PARTY_LICENSES';notices.mkdir()
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if not python_license.is_file(): raise ValueError('Python license not found')
    shutil.copy2(python_license,notices/'Python-LICENSE.txt')
    copied=[]
    for dist in importlib.metadata.distributions():
        name=re.sub(r'[^a-zA-Z0-9._-]','_',dist.metadata['Name'])
        for number,item in enumerate(dist.files or []):
            filename=Path(str(item)).name
            if not filename.lower().startswith(('license','copying','notice')): continue
            source=Path(dist.locate_file(item))
            if not source.is_file() or source.stat().st_size>2_000_000: continue
            destination=notices/name;destination.mkdir(exist_ok=True)
            target=destination/(str(number)+'-'+filename)
            shutil.copy2(source,target);copied.append(target.relative_to(bundle).as_posix())
    return copied


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--label',required=True,help='Unique artifact label, e.g. dev-d2; does not change the app version')
    p.add_argument('--build',action='store_true');p.add_argument('--smoke',action='store_true')
    p.add_argument('--allow-dirty',action='store_true',help='Explicitly allow a development build with uncommitted source')
    args=p.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}',args.label):p.error('Use a short filename-safe label')
    if args.smoke and not args.build:p.error('--smoke requires --build')
    run=ROOT/'dist'/('build-'+args.label)
    plan={'build':args.build,'application_version':__version__,'label':args.label,'output_directory':str(run),
          'format':'Windows x64 onedir ZIP + SHA-256','requires':'dedicated isolated virtual environment; requirements-build.txt',
          'smoke_requested':args.smoke,'tags_or_publishes':False,'overwrites_existing_output':False}
    print(json.dumps(plan,indent=2),flush=True)
    if not args.build:return 0
    try:
        if os.name!='nt' or platform.machine().lower() not in ('amd64','x86_64'):raise ValueError('This script currently targets Windows x64 only')
        if run.exists():raise ValueError('Build output already exists; choose a new label')
        clean_environment()
        source=revision()
        if source['commit']=='unknown':raise ValueError('Cannot identify source revision')
        if source['dirty'] and not args.allow_dirty:raise ValueError('Commit source or explicitly select --allow-dirty for a development artifact')
        run.mkdir(parents=True)
        subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--distpath',str(run/'dist'),'--workpath',str(run/'work'),str(ROOT/'Agentnik.spec')],cwd=ROOT,check=True)
        bundle=run/'dist'/'Agentnik'
        for name in ('LICENSE','README.md','DISCLAIMER.md','VALIDATION.md','RELEASE_NOTES.md','AGENTNIK_PLAN.md','DEVELOPMENT_VALIDATION.md','CODING_BACKEND_PLAN.md','TRACK_FORMAT.md','CODING_GUIDE.md','CODE_FEATURES.md','CHAT_AND_DECISIONS.md','RESEARCH_GUIDE.md','CONNECTIONS.md','FEATURES.md','SEARCH_PROVIDERS.md'):
            shutil.copy2(ROOT/name,bundle/name)
        # Keep the bundled README's relative image links usable.
        for asset_source,asset_target in ((ROOT/'assets',bundle/'assets'),(ROOT/'agentnik'/'assets',bundle/'agentnik'/'assets')):
            asset_target.mkdir(parents=True,exist_ok=True)
            for image in asset_source.iterdir():
                if image.suffix in ('.png','.svg','.ico'):shutil.copy2(image,asset_target/image.name)
        notices=copy_notices(bundle)
        manifest={'schema_version':1,'timestamp':datetime.now(timezone.utc).isoformat(),'application_version':__version__,'artifact_label':args.label,
                  'source':source,'python':sys.version,'os':platform.platform(),'architecture':platform.machine(),
                  'dependencies':dict(sorted((d.metadata['Name'],d.version) for d in importlib.metadata.distributions())),
                  'included_notice_files':notices,'signed':False,'license_audit':'Collected installed distribution notices; full bundled-library license audit remains required',
                  'smoke':'not run','clean_machine_validation':'not performed'}
        if args.smoke:
            smoke(bundle/'Agentnik.exe')
            manifest['smoke']='Qt window, isolated SQLite and graceful exit passed'
        (bundle/'BUILD-MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
        archive=run/('Agentnik-'+args.label+'-windows-x64.zip')
        digest=package_bundle(bundle,archive,manifest)
        print(json.dumps({'archive':str(archive),'sha256':digest,'smoke':manifest['smoke']}));return 0
    except (OSError,ValueError,subprocess.SubprocessError,importlib.metadata.PackageNotFoundError) as exc:
        print('Build stopped: '+str(exc),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
