"""Render research UI with explicitly simulated model/search results; never calls an endpoint."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QFont,QFontDatabase
from PySide6.QtWidgets import QApplication
from agentnik import core,research
from agentnik.storage import Store
from agentnik.tools import Source,utc_now
from agentnik.ui import Window
from agentnik.research_ui import ResearchDetails


class DemoBackend:
    def search(self,query,runtime):
        return [Source('','Ollama API documentation','https://docs.ollama.com/capabilities/web-search',
                       'Simulated source record for interface review. No page was retrieved.',utc_now(),backend='offline-demo')]
    def fetch(self,url,runtime): raise AssertionError('This demo does not fetch pages')


class Response(io.BytesIO):
    def __init__(self,message):
        super().__init__((json.dumps({'message':message,'done':True})+'\n').encode())
        self.headers={'Content-Type':'application/x-ndjson'}


def main():
    app=QApplication([]); app.setStyle('Fusion')
    fonts=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
    for name in ('segoeui.ttf','segoeuib.ttf','seguisym.ttf'):
        if (fonts/name).exists(): QFontDatabase.addApplicationFont(str(fonts/name))
    app.setFont(QFont('Segoe UI',9))
    c={'url':'http://127.0.0.1:11434/v1','protocol':'chat','model':'offline-demo'}
    responses=[Response({'role':'assistant','content':'','tool_calls':[{'function':{'index':0,'name':'web_search','arguments':{'query':'Agentnik research interface demonstration'}}}]}),
               Response({'role':'assistant','content':'This offline demo shows how Agentnik records tool activity and sources. The source below is simulated for interface review [S1].\n\nExpand **Research** to inspect the recorded activity, source link, and saved excerpt.'})]
    with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]),patch.object(core,'open_request',side_effect=responses),patch.object(research,'OllamaWeb',return_value=DemoBackend()):
        store=Store(root); store.save_web_key('offline-demo-key',plaintext=True); research.set_capability(store.config,c,'configured','Offline demo')
        w=Window(store); w.resize(1440,1000); w.connections={'Offline demo':c}; w.new_session('chat','Offline demo'); w.show(); app.processEvents()
        try:
            tab=w.tabs.currentWidget(); tab.web_access.setChecked(True); tab.composer.setPlainText('Show the managed research interface using simulated evidence.'); tab.submit()
            deadline=time.monotonic()+3
            while tab.job and time.monotonic()<deadline: app.processEvents(); time.sleep(.005)
            if tab.job: raise RuntimeError('Demo did not finish')
            details=tab.findChildren(ResearchDetails)[-1]; details.toggle.setChecked(True)
            tab.info.setText('Offline demo · Simulated model and tool responses · No network requests')
            for theme in ('Light','Dark'):
                w.theme.setCurrentText(theme)
                for _ in range(30): app.processEvents()
                out=Path(__file__).resolve().parents[1]/'assets'/f'agentnik-research-{theme.lower()}.png'
                if not w.grab().save(str(out)): raise RuntimeError('Cannot save screenshot')
        finally: w.close(); app.processEvents(); store.db.close()


if __name__=='__main__': main()
