"""Load packaged Qt translations at startup, with English as the fallback."""
from pathlib import Path
from PySide6.QtCore import QLocale, QTranslator

CATALOGS = {'ko':'한국어 (미리보기)', 'es':'Español', 'de':'Deutsch', 'fr':'Français',
            'zh-Hans':'简体中文', 'zh-Hant':'繁體中文'}
CATALOG_DIR = Path(__file__).parent / 'translations'


def choices(directory=CATALOG_DIR):
    """Only expose locales with a packaged catalog; English needs no catalog."""
    return [('system','System default'),('en','English')]+[(code,name) for code,name in CATALOGS.items() if (directory/('agentnik_'+code+'.qm')).is_file()]


def locale_candidates(tag):
    parts=tag.replace('_','-').split('-');language=parts[0].lower()
    if language=='zh':
        hints={p.lower() for p in parts[1:]}
        return ['zh-Hant' if hints & {'hant','tw','hk','mo'} else 'zh-Hans']
    return [language] if language in CATALOGS else []


def install(app,selection='system',directory=CATALOG_DIR,system_languages=None):
    """Return an installed translator, or None when no usable catalog exists."""
    tags=(system_languages if system_languages is not None else QLocale.system().uiLanguages()) if selection=='system' else [selection]
    visited=set()
    for tag in tags:
        if tag.replace('_','-').split('-')[0].lower()=='en':return None
        for code in locale_candidates(tag):
            if code in visited:continue
            visited.add(code);path=directory/('agentnik_'+code+'.qm')
            if not path.is_file():continue
            translator=QTranslator(app)
            if translator.load(str(path)) and app.installTranslator(translator):return translator
    return None
