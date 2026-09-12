const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'../capture.js'),'utf8');
function capture(metadata) {
  const article = {cloneNode(){return {innerText:'Article text about Python.',querySelectorAll(){return [];}};},querySelectorAll(){return [{naturalWidth:800,naturalHeight:400,currentSrc:'https://example.com/article.jpg'}];}};
  const document = {title:'Article title',body:{innerText:'Navigation plus unrelated body'},
    querySelector(selector){if(selector==='article') return article; if(selector==='meta[property="og:image"]' && metadata) return {content:metadata}; return null;},
    querySelectorAll(){return [{innerText:'Python'}];}};
  return vm.runInNewContext(source,{document,location:{href:'https://example.com/story'},getSelection(){return null;},URL,Date});
}
test('captures article text and resolves the page preview image',()=>{
  const result=capture('/cover.jpg');
  assert.equal(result.visible_text,'Article text about Python.');
  assert.equal(result.image_url,'https://example.com/cover.jpg');
});
test('uses a large article image when metadata is absent',()=>{
  assert.equal(capture(null).image_url,'https://example.com/article.jpg');
});
test('ignores non-web image schemes',()=>{
  assert.equal(capture('javascript:alert(1)').image_url,null);
});
