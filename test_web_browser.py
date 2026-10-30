"""Optional browser tests using installed Chrome/Edge and websocket-client. No npm or browser installation."""
import base64,json,os,subprocess,tempfile,time,unittest,urllib.request,importlib.util
from pathlib import Path
from test_web import WebFixture

BROWSERS=[Path('C:/Program Files/Google/Chrome/Application/chrome.exe'),Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')]

class Browser:
    def __init__(self):
        import websocket
        self.profile=tempfile.TemporaryDirectory(prefix='chestcount-browser-');self.counter=0;self.messages=[]
        binary=next((p for p in BROWSERS if p.exists()),None)
        if binary is None:raise RuntimeError('No installed Chrome/Edge')
        self.log=Path('validation-web/browser.log').open('a',encoding='utf-8')
        self.process=subprocess.Popen([str(binary),'--headless=new','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-component-update','--disable-extensions','--disable-sync','--remote-debugging-address=127.0.0.1','--remote-debugging-port=0','--user-data-dir='+self.profile.name,'--window-size=1440,1100','about:blank'],stdout=self.log,stderr=self.log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        portfile=Path(self.profile.name)/'DevToolsActivePort'
        deadline=time.monotonic()+15
        while not portfile.exists():
            if self.process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Browser failed to start; see browser.log')
            time.sleep(.05)
        port=portfile.read_text().splitlines()[0]
        with urllib.request.urlopen('http://127.0.0.1:'+port+'/json',timeout=5) as response:pages=json.load(response)
        self.ws=websocket.create_connection(next(p['webSocketDebuggerUrl'] for p in pages if p['type']=='page'),timeout=20,suppress_origin=True)
        for method in ['Page.enable','Runtime.enable','Network.enable']:self.call(method)
        self.call('Page.addScriptToEvaluateOnNewDocument',{'source':"try { localStorage.clear(); localStorage.setItem('chestcount.viewer.v1', JSON.stringify({automatic:false})); } catch (_) {}"})
    def call(self,method,params=None):
        self.counter+=1;request=self.counter;self.ws.send(json.dumps({'id':request,'method':method,'params':params or {}}))
        while True:
            message=json.loads(self.ws.recv())
            if message.get('id')==request:
                if 'error' in message:raise AssertionError(message['error'])
                return message.get('result',{})
            self.messages.append(message)
    def evaluate(self,expression):
        result=self.call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
        if 'exceptionDetails' in result:raise AssertionError(result['exceptionDetails'])
        return result.get('result',{}).get('value')
    def wait(self,expression,timeout=10):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if self.evaluate(expression):return
            time.sleep(.03)
        raise AssertionError('Browser condition timed out: '+expression)
    def navigate(self,url):
        self.call('Page.navigate',{'url':url});self.wait("typeof ChestCount !== 'undefined' && document.getElementById('refresh').getAttribute('aria-busy') === 'false'")
    def viewport(self,width,height):self.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':width<720})
    def screenshot(self,path):
        size=self.call('Page.getLayoutMetrics')['cssContentSize']
        data=self.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':{'x':0,'y':0,'width':size['width'],'height':size['height'],'scale':1}})['data']
        Path(path).write_bytes(base64.b64decode(data))
    def close(self):
        try:self.call('Browser.close')
        except Exception:pass
        self.ws.close()
        try:self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=5)
        self.log.close()
        for attempt in range(20):
            try:self.profile.cleanup();break
            except PermissionError:time.sleep(.1)

@unittest.skipUnless(any(p.exists() for p in BROWSERS) and importlib.util.find_spec('websocket'),'Needs installed Chrome/Edge and optional websocket-client')
class WebBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):Path('validation-web').mkdir(exist_ok=True);cls.browser=Browser()
    @classmethod
    def tearDownClass(cls):cls.browser.close()
    def setUp(self):
        self.fixture=WebFixture();self.browser.viewport(1440,1100);self.browser.navigate(self.fixture.base+'/');self.browser.messages.clear()
    def tearDown(self):
        self.browser.evaluate('window.chestCountApp?.destroy()');self.fixture.close()
    def js(self,expression):return self.browser.evaluate(expression)
    def click_chest(self,id):
        self.js("[...document.querySelectorAll('[data-chest-id]')].find(e=>e.dataset.chestId==="+json.dumps(id)+").click()")
        self.browser.wait("document.getElementById('chest-id').textContent==="+json.dumps(id)+" && document.getElementById('refresh').getAttribute('aria-busy')==='false'")
    def test_single_slots_real_positions_icons_and_details(self):
        self.assertEqual(27,self.js("document.querySelectorAll('.slot').length"))
        self.assertEqual('32',self.js("document.querySelector('[data-slot=\"0\"] .stack-count').textContent"))
        self.assertEqual('64',self.js("document.querySelector('[data-slot=\"13\"] .stack-count').textContent"))
        self.assertIsNone(self.js("document.querySelector('[data-slot=\"1\"] img')"))
        self.js("document.querySelector('[data-slot=\"13\"]').click()")
        self.assertEqual('minecraft:iron_ingot',self.js("document.getElementById('detail-id').textContent"));self.assertEqual('13',self.js("document.getElementById('detail-slot').textContent"))
        self.assertTrue(self.js("document.querySelector('[data-slot=\"13\"]').classList.contains('selected')"))
        self.assertEqual('pixelated',self.js("getComputedStyle(document.querySelector('.slot img')).imageRendering"))
        self.browser.wait("document.querySelector('.slot img').complete && document.querySelector('.slot img').naturalWidth>0");self.assertTrue(self.js("document.querySelector('.slot img').src.startsWith('https://blocksitems.com/')"))
        self.browser.screenshot('validation-web/fixture-desktop.png')
    def test_double_slots_and_mobile_layout(self):
        self.click_chest(self.fixture.double['id']);self.assertEqual(54,self.js("document.querySelectorAll('.slot').length"))
        self.assertIn('netherite_sword',self.js("document.querySelector('[data-slot=\"53\"] img').alt"));self.assertEqual('1',self.js("document.querySelector('[data-slot=\"53\"] .stack-count').textContent"))
        self.browser.viewport(375,1100);self.assertTrue(self.js('document.documentElement.scrollWidth <= document.documentElement.clientWidth'))
        self.browser.screenshot('validation-web/fixture-mobile.png')
    def test_empty_slots_tombstones_and_empty_world(self):
        self.click_chest(self.fixture.empty['id']);self.assertEqual(27,self.js("document.querySelectorAll('.slot').length"));self.assertEqual(0,self.js("document.querySelectorAll('.slot img').length"))
        self.js("document.querySelector('[data-slot=\"0\"]').click()");self.assertEqual('Slot vazio',self.js("document.getElementById('detail-name').textContent"))
        self.assertEqual(3,self.js("document.querySelectorAll('[data-chest-id]').length"));self.js("document.getElementById('show-deleted').click()")
        self.click_chest(self.fixture.deleted['id']);self.assertIn('histórico',self.js("document.getElementById('chest-notice').textContent"))
        self.js("document.getElementById('world-select').value="+json.dumps(self.fixture.empty_world)+";document.getElementById('world-select').dispatchEvent(new Event('change'))")
        self.browser.wait("document.getElementById('refresh').getAttribute('aria-busy')==='false'");self.assertFalse(self.js("document.getElementById('welcome').hidden"));self.assertIn('Nenhum baú sincronizado',self.js("document.getElementById('list-empty').textContent"))
    def test_refresh_keeps_world_chest_slot_and_updates_stack(self):
        self.js("document.querySelector('[data-slot=\"13\"]').click()")
        record=self.fixture.single;record['items'][1]['count']=48;self.fixture.apply(record,base=1)
        self.js('window.chestCountApp.refresh()')
        self.assertEqual(self.fixture.world,self.js("document.getElementById('world-select').value"));self.assertEqual(record['id'],self.js("document.getElementById('chest-id').textContent"))
        self.assertEqual('48',self.js("document.getElementById('detail-count').textContent"));self.assertEqual('13',self.js("document.getElementById('detail-slot').textContent"));self.assertEqual('Revisão #2',self.js("document.getElementById('server-revision').textContent"))
        requests=[m['params']['request'] for m in self.browser.messages if m.get('method')=='Network.requestWillBeSent' and m['params']['request']['url'].startswith(self.fixture.base+'/api/')]
        self.assertTrue(requests);self.assertTrue(all(r['method']=='GET' for r in requests))
    def test_selected_chest_becoming_tombstone_keeps_selection_and_history(self):
        self.js("document.querySelector('[data-slot=\"13\"]').click()")
        self.fixture.apply(self.fixture.single,'delete',1);self.js('window.chestCountApp.refresh()')
        self.assertEqual(self.fixture.single['id'],self.js("document.getElementById('chest-id').textContent"));self.assertEqual('13',self.js("document.getElementById('detail-slot').textContent"))
        self.assertIn('histórico',self.js("document.getElementById('chest-notice').textContent"));self.assertEqual('64',self.js("document.getElementById('detail-count').textContent"))
    def test_network_failure_preserves_last_snapshot_and_recovers(self):
        self.js("""(async()=>{ window.chestCountApp.destroy(); window.networkFailed=false;
            window.chestCountApp=ChestCount.createApp(document,{fetcher:(...args)=>window.networkFailed?Promise.reject(new TypeError('offline')):fetch(...args)});await window.chestCountApp.start();
            document.querySelector('[data-slot="13"]').click();window.networkFailed=true;await window.chestCountApp.refresh(); })()""")
        self.assertFalse(self.js("document.getElementById('error').hidden"));self.assertEqual('Servidor indisponível',self.js("document.getElementById('connection').textContent"));self.assertEqual('64',self.js("document.getElementById('detail-count').textContent"))
        self.js('window.networkFailed=false;window.chestCountApp.refresh()');self.assertTrue(self.js("document.getElementById('error').hidden"))
    def test_no_worlds_and_unknown_size(self):
        self.js("""(async()=>{window.chestCountApp.destroy();window.chestCountApp=ChestCount.createApp(document,{fetcher:async(url,opts)=>url==='/api/v1/worlds'?new Response(JSON.stringify({worlds:[]}),{status:200}):fetch(url,opts)});await window.chestCountApp.start();})()""")
        self.assertTrue(self.js("document.getElementById('world-select').disabled"));self.assertIn('Nenhum baú sincronizado',self.js("document.getElementById('welcome-text').textContent"))
        self.assertIsNone(self.js("ChestCount.inventorySize({items:[{slot:53,item_id:'minecraft:diamond',count:1}]})"))
        self.js("""(async()=>{window.chestCountApp.destroy();window.chestCountApp=ChestCount.createApp(document,{fetcher:async(url,opts)=>{const r=await fetch(url,opts);const value=await r.json();if(value.identity)value.identity.blocks=[];return new Response(JSON.stringify(value),{status:r.status});}});await window.chestCountApp.start();})()""")
        self.assertFalse(self.js("document.getElementById('unknown-size').hidden"));self.assertEqual(0,self.js("document.querySelectorAll('.slot').length"))
    def test_safe_icon_urls_and_actual_404_fallback(self):
        url=self.js("ChestCount.iconUrl('minecraft:diamond')");self.assertEqual('https://blocksitems.com/api/2026.1.2/icon/minecraft%3Adiamond.png?size=64&placeholder=404',url)
        for id in ['https://evil.example/image.png','minecraft:diamond?x=1','<img src=x onerror=alert(1)>']:self.assertEqual('/placeholder.svg',self.js('ChestCount.iconUrl('+json.dumps(id)+')'))
        self.js("""(async()=>{window.chestCountApp.destroy();window.chestCountApp=ChestCount.createApp(document,{fetcher:async(url,opts)=>{const r=await fetch(url,opts);const value=await r.json();if(value.items)value.items[0].item_id='chestcount:missing_test_icon';return new Response(JSON.stringify(value),{status:r.status});}});await window.chestCountApp.start();})()""")
        self.browser.wait("document.querySelector('[data-slot=\"0\"] img').getAttribute('src')==='/placeholder.svg'",timeout=15)
        self.assertEqual('32',self.js("document.querySelector('[data-slot=\"0\"] .stack-count').textContent"));self.js("document.querySelector('[data-slot=\"0\"]').click()")
        self.assertEqual('chestcount:missing_test_icon',self.js("document.getElementById('detail-id').textContent"));self.assertEqual('/placeholder.svg',self.js("document.querySelector('#detail-preview img').getAttribute('src')"))
    def test_untrusted_names_are_text_not_html(self):
        self.js("""(async()=>{window.chestCountApp.destroy();const bad='<img src=x onerror="window.xssExecuted=1">';window.chestCountApp=ChestCount.createApp(document,{fetcher:async(url,opts)=>{const r=await fetch(url,opts);const v=await r.json();if(v.chests)v.chests.forEach(c=>c.name=bad);if(v.identity)v.name=bad;return new Response(JSON.stringify(v),{status:r.status});}});await window.chestCountApp.start();})()""")
        self.assertIn('<img',self.js("document.getElementById('chest-name').textContent"));self.assertEqual(0,self.js("document.querySelectorAll('#chest-name img, .list-name img').length"));self.assertIsNone(self.js('window.xssExecuted'))
    def test_polling_has_no_overlaps_and_can_be_disabled(self):
        self.js("""(async()=>{window.chestCountApp.destroy();window.activeFetches=0;window.maxFetches=0;window.calls=0;window.chestCountApp=ChestCount.createApp(document,{intervalMs:60,fetcher:async(...args)=>{window.calls++;window.activeFetches++;window.maxFetches=Math.max(window.maxFetches,window.activeFetches);try{await new Promise(r=>setTimeout(r,120));return await fetch(...args);}finally{window.activeFetches--;}}});document.getElementById('auto-refresh').checked=true;await window.chestCountApp.start();})()""")
        time.sleep(.7);self.js("document.getElementById('auto-refresh').click()");time.sleep(.6);count=self.js('window.calls');time.sleep(.25)
        self.assertEqual(count,self.js('window.calls'));self.assertLessEqual(self.js('window.maxFetches'),2)
    def test_selection_refresh_avoids_repeated_detail_or_metadata_requests(self):
        self.js('window.chestCountApp.refresh()')
        urls=[m['params']['request']['url'] for m in self.browser.messages if m.get('method')=='Network.requestWillBeSent']
        self.assertFalse(any('/chests/'+self.fixture.single['id'] in u for u in urls));self.assertFalse(any('/lookup/' in u for u in urls))

if __name__=='__main__':unittest.main(verbosity=2)
