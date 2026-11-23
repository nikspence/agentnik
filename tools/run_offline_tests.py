"""Run the offline suite with an isolated profile and Python network guard."""
import os
import site
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    # Preserve only platform process-launch and locale variables. Do not inherit
    # provider keys, proxy settings, user Python configuration, or Git identity.
    keep = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'LANG',
            'LC_ALL', 'LC_CTYPE', 'TMP', 'TEMP', 'TMPDIR'}
    env = {key: value for key, value in os.environ.items() if key.upper() in keep}
    with tempfile.TemporaryDirectory(prefix='agentnik-offline-') as directory:
        home = Path(directory).resolve()
        audit = home / 'network-attempts.txt'
        # A venv configured with system site packages can depend on the user's
        # installed libraries; retain that package path while isolating profile data.
        import_paths = [str(ROOT / 'tools' / 'offline_guard'), str(ROOT)]
        if site.ENABLE_USER_SITE and Path(site.getusersitepackages()).is_dir():
            import_paths.append(site.getusersitepackages())
        env.update({
            'HOME': str(home), 'USERPROFILE': str(home), 'USER': 'agentnik-test',
            'USERNAME': 'agentnik-test', 'LOGNAME': 'agentnik-test', 'APPDATA': str(home / 'appdata'),
            'LOCALAPPDATA': str(home / 'localappdata'), 'XDG_CONFIG_HOME': str(home / 'config'),
            'XDG_DATA_HOME': str(home / 'data'), 'XDG_CACHE_HOME': str(home / 'cache'),
            'AGENTNIK_HOME': str(home / 'agentnik'), 'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': str(home / 'gitconfig'), 'QT_QPA_PLATFORM': 'offscreen',
            'PYTHONIOENCODING': 'utf-8',
            'PYTHONFAULTHANDLER': '1', 'PYTHONUNBUFFERED': '1',
            'PYTHONPATH': os.pathsep.join(import_paths),
            'AGENTNIK_OFFLINE_GUARD': '1', 'AGENTNIK_OFFLINE_AUDIT': str(audit),
        })
        result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=ROOT, env=env)
        if result.returncode:
            print(f'Offline test process exited with status {result.returncode}.', file=sys.stderr, flush=True)
        if audit.exists() and audit.stat().st_size:
            print('Offline guard blocked unexpected network operations:', file=sys.stderr)
            print(audit.read_text(encoding='utf-8'), file=sys.stderr)
            return 1
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
