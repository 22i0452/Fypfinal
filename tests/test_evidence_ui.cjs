const {test}=require('node:test'),assert=require('node:assert/strict');
const ui=require('../scribe/assets/evidence.js');
test('Original words and keys are escaped inside inspectable marks',()=>{
  const html=ui.marks('Original <script> & unchanged',[{text:'<script>',key:'x" onclick="bad',status:'review'}]);
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('x&quot; onclick=&quot;bad'));
  assert.ok(!html.includes('<script>'));
  assert.ok(html.endsWith(' &amp; unchanged'));
});
test('Only exact existing spans are marked, without fabricated confidence',()=>{
  const html=ui.marks('knee pain remains',[{text:'Pain in knee',key:'none',status:'checked'},{text:'knee pain',key:'real',status:'review'}]);
  assert.equal((html.match(/<button/g)||[]).length,1);
  assert.ok(html.includes('ev-review'));
  assert.ok(!html.includes('data-evidence-key="none"'));
  assert.ok(!html.includes('%'));
});
test('Overlapping spans preserve all original text',()=>{
  const html=ui.marks('knee pain remains',[{text:'knee pain',key:'one'},{text:'pain',key:'two'}]);
  assert.equal(html.replace(/<[^>]*>/g,''),'knee pain remains');
  assert.equal((html.match(/<button/g)||[]).length,1);
});
test('Unknown states stay unassessed; checks state their actual scope',()=>{
  assert.ok(ui.badge('unknown').includes('ev-missing'));
  assert.ok(ui.checks([{label:'Source exists',code:'id_membership',status:'passed',detail:'Not clinical support'}]).includes('Not clinical support'));
  assert.ok(ui.legend().includes('not measured'));
});
