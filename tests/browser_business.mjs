// Explicit local browser acceptance, not a production task or a network collector.
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve,extname,sep} from 'node:path';
import assert from 'node:assert/strict';
const root=resolve('review/phase5/site'), out=resolve('docs/phase5-release-2026-11-27');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const server=createServer(async(req,res)=>{
  try{
    const file=resolve(root,'.'+decodeURIComponent(new URL(req.url,'http://localhost').pathname));
    if(file!==root&&!file.startsWith(root+sep))throw Error('path');
    const body=await readFile(file===root?resolve(root,'index.html'):file);
    res.setHeader('Content-Type',({'.html':'text/html; charset=utf-8','.js':'application/javascript','.json':'application/json','.css':'text/css'})[extname(file)]||'application/octet-stream');
    res.end(body);
  }catch{res.statusCode=404;res.end('missing');}
});
await new Promise(r=>server.listen(8875,'127.0.0.1',r));
const browser=spawn(process.env.BROWSER_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',[
  '--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=9336',
  '--user-data-dir='+resolve('review/phase5/chrome-profile'),'about:blank'
],{windowsHide:true,stdio:'ignore'});
let ws; const report={cities:[],errors:[],legacy:{},screenshots:[]};
try{
  let target;
  for(let i=0;i<100;i++){
    try{target=(await(await fetch('http://127.0.0.1:9336/json/list')).json()).find(t=>t.type==='page');if(target)break;}catch{}
    await delay(100);
  }
  assert(target,'Headless browser did not start');
  ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
  let next=1;const pending=new Map();let requests=[];
  ws.onmessage=e=>{
    const m=JSON.parse(e.data);
    if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result);}}
    if(m.method==='Network.requestWillBeSent')requests.push(m.params.request.url);
    if(m.method==='Runtime.exceptionThrown')report.errors.push(m.params.exceptionDetails.text);
  };
  function call(method,params={}){return new Promise((resolve,reject)=>{let id=next++;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));setTimeout(()=>{if(pending.has(id)){pending.delete(id);reject(Error('timeout '+method));}},15000).unref();});}
  async function evaluate(expression){const result=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw Error(JSON.stringify(result.exceptionDetails));return result.result.value;}
  async function ready(expression){for(let i=0;i<100;i++){if(await evaluate(expression))return;await delay(100);}throw Error('page not ready: '+expression);}
  await call('Page.enable');await call('Runtime.enable');await call('Network.enable');
  await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await mkdir(out,{recursive:true});
  async function screenshot(name){const image=await call('Page.captureScreenshot',{format:'png'});await writeFile(resolve(out,name),Buffer.from(image.data,'base64'));report.screenshots.push(name);}
  for(const [slug,city,expected] of [['xian','西安市','那英'],['jinan','济南市','徐良'],['tianjin','天津市','老狼']]){
    requests=[];
    await call('Page.navigate',{url:'http://127.0.0.1:8875/index.html?city='+encodeURIComponent(city)});
    await ready("document.getElementById('businessCount').textContent.includes('条')");
    const text=await evaluate("document.getElementById('businessList').textContent");
    assert(text.includes(expected),city+' real candidate missing');
    assert(text.includes('待核验候选'));
    assert(!requests.some(url=>/\/api\/v[12]\//.test(url)),'Default page downloaded historical v1/v2 data');
    report.cities.push({city,expected_visible:expected,count:await evaluate("document.getElementById('businessCount').textContent"),default_api_requests:requests.filter(u=>u.includes('/api/'))});
    await screenshot('page-'+slug+'.png');
    if(slug==='xian'){
      await evaluate("document.querySelector('[data-feed=intelligence]').click()");
      await ready("document.getElementById('businessList').textContent.includes('西电6113')");
      await screenshot('page-intelligence.png');
      await evaluate("document.querySelector('[data-feed=calendar]').click();document.getElementById('businessDays').value='365';document.getElementById('businessDays').dispatchEvent(new Event('change'))");
      await ready("document.getElementById('businessList').textContent.includes('ICCLL')");
      report.horizon_365_and_undated_signal=true;
    }
  }
  await evaluate("document.querySelector('[data-feed=changes]').click()");
  await ready("document.getElementById('businessList').textContent.includes('观察时间')");
  await screenshot('page-changes.png');
  await evaluate("document.getElementById('openLegacy').click()");
  await ready("document.getElementById('openLegacy').textContent.includes('已展开')");
  await ready("document.getElementById('resultCount').textContent !== '0 条'");
  report.legacy={loaded_on_demand:requests.some(u=>u.includes('/api/v1/hotspots.json')),result:await evaluate("document.getElementById('resultCount').textContent")};
  assert(report.legacy.loaded_on_demand);assert.equal(report.errors.length,0);
  // Failure/stale injection only in the ignored local copy, restored before exit.
  const focusPath=resolve(root,'api/business/focus.json'), saved=await readFile(focusPath);
  try{
    const failed=JSON.parse(saved);failed.meta.collection_ok=false;failed.meta.last_observed_at='2026-01-01T00:00:00Z';
    await writeFile(focusPath,JSON.stringify(failed));
    await call('Page.navigate',{url:'http://127.0.0.1:8875/index.html?city='+encodeURIComponent('天津市')});
    await ready("document.getElementById('businessFreshness').textContent.includes('数据已过期') && document.getElementById('businessFreshness').textContent.includes('保留上次有效数据')");
    assert((await evaluate("document.getElementById('businessList').textContent")).includes('老狼'));
    report.stale_failure_preserves_real_candidates=true;
  }finally{await writeFile(focusPath,saved);}
  await writeFile(resolve(out,'browser-validation.json'),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report));
}finally{if(ws)ws.close();browser.kill();server.close();}
