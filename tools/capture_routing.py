"""Render hosted and fallback UI with simulated Responses only; no endpoint requests."""
import io,json,os,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QFont,QFontDatabase
from PySide6.QtWidgets import QApplication
from agentnik import core,research
from agentnik.storage import Store
from agentnik.ui import Window
from agentnik.research_ui import ResearchDetails,WebSettings
from capture_research import DemoBackend


class Wire(io.BytesIO):
    def __init__(self,output):
        super().__init__(json.dumps({'id':'offline-response','status':'completed','output':output}).encode())
        self.headers={'Content-Type':'application/json'}


def message(text,annotations=None):
    return {'type':'message','id':'offline-message','role':'assistant','status':'completed',
            'content':[{'type':'output_text','text':text,'annotations':annotations or []}]}


def main():
    app=QApplication([]); app.setStyle('Fusion')
    fonts=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
    for name in ('segoeui.ttf','segoeuib.ttf','seguisym.ttf'):
        if (fonts/name).exists(): QFontDatabase.addApplicationFont(str(fonts/name))
    app.setFont(QFont('Segoe UI',9))
    out=Path(__file__).resolve().parents[1]/'assets'
    c={'url':'https://api.openai.com/v1','protocol':'responses','model':'offline-demo','stream':False}
    for scenario in ('hosted','fallback'):
        if scenario=='hosted':
            text='This is a simulated hosted-search answer with an inline citation. SOURCE'
            start=text.index('SOURCE'); url='https://developers.openai.com/api/docs/guides/tools-web-search'
            output=[{'type':'web_search_call','id':'offline-search','status':'completed','action':{'type':'search','sources':[{'type':'url','url':url}]}},
                    message(text,[{'type':'url_citation','start_index':start,'end_index':start+6,'title':'OpenAI web search documentation','url':url}])]
            replies=[Wire(output)]
        else:
            replies=[core.EndpointError(400,json.dumps({'error':{'message':'web_search is not supported by this model','param':'tools','code':'unsupported_value'}})),
                     Wire([{'type':'function_call','id':'offline-function','call_id':'offline-call','name':'web_search','arguments':json.dumps({'query':'Agentnik routing demonstration'})}]),
                     Wire([message('The simulated hosted request was explicitly rejected. Agentnik used the managed route with the same connection and model [S1].')])]
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]),patch.object(core,'open_request',side_effect=replies),patch('agentnik.web.OllamaWeb',return_value=DemoBackend()):
            store=Store(root); store.config['connections']={'Offline demo':c}; store.save_web_key('offline-key',plaintext=True)
            for field in ('managed_tools','hosted_search'): research.set_capability(store.config,c,'configured','Offline fixture only',field)
            w=Window(store); w.resize(1440,1000); w.new_session('chat','Offline demo'); w.show(); app.processEvents()
            try:
                tab=w.tabs.currentWidget(); tab.web_access.setChecked(True); tab.route_policy.setCurrentText('Provider only' if scenario=='hosted' else 'Provider first')
                tab.composer.setPlainText('Demonstrate '+scenario+' research with simulated responses.'); tab.submit()
                deadline=time.monotonic()+3
                while tab.job and time.monotonic()<deadline: app.processEvents(); time.sleep(.005)
                if tab.job or tab.session['messages'][-1]['status']!='ok': raise RuntimeError('Offline routing demo failed')
                tab.findChildren(ResearchDetails)[-1].toggle.setChecked(True)
                tab.info.setText('Offline demo · Simulated '+scenario+' responses · No network requests')
                for theme in ('Light','Dark'):
                    w.theme.setCurrentText(theme)
                    for _ in range(30): app.processEvents()
                    if not w.grab().save(str(out/f'agentnik-{scenario}-{theme.lower()}.png')): raise RuntimeError('Screenshot failed')
                if scenario=='hosted':
                    dlg=WebSettings(tab,c); dlg.show()
                    for _ in range(10): app.processEvents()
                    if not dlg.grab().save(str(out/'agentnik-web-settings.png')): raise RuntimeError('Settings screenshot failed')
                    dlg.close()
            finally: w.close(); app.processEvents(); store.db.close()


if __name__=='__main__': main()
