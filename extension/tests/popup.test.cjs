const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
async function popup({token='session', url='https://example.com/article', result={ok:true,memory:{title:'A good article'}}}={}) {
  const elements = {};
  const element = () => ({textContent:'',value:'',dataset:{},disabled:false,append(){},setAttribute(){},replaceChildren(){},remove(){}});
  const document = {getElementById(id){return elements[id] ||= element();},createElement:element};
  const calls = {options:0,capture:0};
  const chrome = {
    storage:{local:{async get(){return {token,contextEnabled:false};}},session:{async get(){return {};}}},
    tabs:{async query(){return [{url,title:'A good article',incognito:false}];},async create(){}},
    runtime:{async openOptionsPage(){calls.options++;},async sendMessage(message){if(message.type==='capture')calls.capture++;return result;}},
    permissions:{async request(){return true;}},
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../popup.js'),'utf8'),{document,chrome,URL});
  await new Promise(resolve=>setImmediate(resolve));
  return {elements,calls};
}
test('signed-out popup offers sign-in instead of a failing capture',async()=>{
  const {elements,calls}=await popup({token:''});
  assert.equal(elements.remember.disabled,false);
  assert.match(elements.remember.textContent,/Sign in/);
  await elements.remember.onclick();
  assert.equal(calls.options,1);
  assert.equal(calls.capture,0);
});
test('restricted Chrome page cannot be saved',async()=>{
  const {elements}=await popup({url:'chrome://extensions'});
  assert.equal(elements.remember.disabled,true);
  assert.equal(elements['page-title'].textContent,'Open a webpage to save');
});
test('valid capture displays page preview and success',async()=>{
  const {elements,calls}=await popup();
  assert.equal(elements['page-domain'].textContent,'example.com');
  assert.equal(elements['page-title'].textContent,'A good article');
  await elements.remember.onclick();
  assert.equal(calls.capture,1);
  assert.equal(elements.status.dataset.state,'success');
  assert.equal(elements.remember.textContent,'Saved to Re:Me ✓');
});
test('expired session offers reauthentication',async()=>{
  const {elements,calls}=await popup({result:{ok:false,error:'Your session expired. Sign in again.'}});
  await elements.remember.onclick();
  assert.equal(elements.status.dataset.state,'error');
  assert.equal(elements.remember.textContent,'Sign in again ↗');
  await elements.remember.onclick();
  assert.equal(calls.options,1);
  assert.equal(calls.capture,1);
});


test('a missing worker response explains recovery instead of suggesting blind retries', async () => {
  const {elements, calls} = await popup({result: null});
  await elements.remember.onclick();
  assert.equal(elements.status.dataset.state, 'error');
  assert.match(elements.status.textContent, /did not confirm the save/);
  assert.match(elements.status.textContent, /chrome:\/\/extensions/);
  assert.equal(calls.capture, 1);
});
