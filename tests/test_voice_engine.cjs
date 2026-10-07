const {test} = require('node:test');
const assert = require('node:assert/strict');
const {TurnDetector, Conversation} = require('../receptionist/web/voice-engine.js');
const frame = (amplitude=0, length=320) => Float32Array.from({length}, (_,i)=>Math.sin(i*.3)*amplitude);
function feed(detector, amplitude, ms) {
  const events=[];
  for(let t=0;t<ms;t+=20){const event=detector.feed(frame(amplitude));if(event)events.push(event);}
  return events;
}
test('silence and low background signal produce no submissions and a bounded prebuffer',()=>{
  const d=new TurnDetector();assert.deepEqual(feed(d,0,60000),[]);assert.deepEqual(feed(d,.003,30000),[]);
  assert.ok(d.preSamples<=16000*.34);assert.equal(d.chunks.length,0);
});
test('80ms reply retains its first sample and ends once, after silence',()=>{
  const d=new TurnDetector({silenceMs:850});feed(d,0,400);assert.equal(feed(d,.08,80)[0].started,true);
  const events=feed(d,0,900);assert.equal(events.length,1);assert.equal(events[0].reason,'silence');
  const all=Array.from(events[0].chunks).flatMap(x=>Array.from(x));assert.ok(all.some(x=>Math.abs(x)>.07));
  assert.deepEqual(feed(d,0,10000),[]);
});
test('phone number pauses stay in the same turn',()=>{
  const d=new TurnDetector({silenceMs:1600});feed(d,.1,300);assert.equal(feed(d,0,1200).length,0);
  feed(d,.1,300);const events=feed(d,0,1700);assert.equal(events.length,1);assert.ok(events[0].voicedMs>=600);
});
test('a cough-sized 20ms impulse does not start a turn',()=>{
  const d=new TurnDetector();assert.equal(feed(d,.5,20).length,0);assert.equal(feed(d,0,2000).length,0);
});
test('send now needs a started answer and clears its audio',()=>{
  const d=new TurnDetector();assert.equal(d.finish(),null);feed(d,.1,100);
  assert.equal(d.finish().reason,'manual');assert.equal(d.finish(),null);
});
test('long audio has a hard limit',()=>{
  const d=new TurnDetector({maxMs:1000});const events=feed(d,.1,1040);assert.equal(events.filter(e=>e.chunks).length,1);
  assert.equal(events.find(e=>e.chunks).reason,'limit');
});
test('reset discards unsubmitted audio',()=>{
  const d=new TurnDetector();feed(d,.1,200);d.reset();assert.equal(d.finish(),null);assert.deepEqual(feed(d,0,2000),[]);
});
test('constant DC is not treated as an answer',()=>{
  const d=new TurnDetector();for(let i=0;i<500;i++)assert.equal(d.feed(new Float32Array(320).fill(.2)),null);
});
function controller(options={}) {
  const c=new Conversation({onTurn:async()=>{},...options});c.active=true;c.phase='processing';c.lastFrameAt=performance.now();return c;
}
test('playback microphone signal is gated with automatic interruption off',()=>{
  let turns=0;const c=controller({onTurn:()=>turns++});c.hold('speaking');for(let i=0;i<150;i++)c.frame(frame(.2));
  assert.equal(c.detector.started,false);assert.equal(turns,0);c.stop();
});
test('explicit interruption preserves the capture when playback settles',()=>{
  let stopped=0;const c=controller({canInterrupt:()=>true,onInterrupt:()=>stopped++});c.hold('speaking');c.interrupt();
  c.frame(frame(.1));c.frame(frame(.1));assert.equal(c.phase,'capturing');c.ready();assert.equal(c.phase,'capturing');assert.equal(stopped,1);c.stop();
});
test('automatic interruption needs sustained signal and cannot interrupt final confirmation',()=>{
  let stopped=0;const c=controller({canInterrupt:()=>false,onInterrupt:()=>stopped++});c.autoInterrupt=true;c.hold('speaking');
  for(let i=0;i<30;i++)c.frame(frame(.1));assert.equal(stopped,0);
  c.cb.canInterrupt=()=>true;for(let i=0;i<3;i++)c.frame(frame(.1));assert.equal(stopped,0);
  for(let i=0;i<12;i++)c.frame(frame(.1));assert.equal(stopped,1);assert.equal(c.phase,'capturing');c.stop();
});
test('pause mutes tracks and collects no audio',()=>{
  const track={enabled:true,stop(){}};const c=controller();c.stream={getTracks:()=>[track]};c.ready();c.pause();
  assert.equal(track.enabled,false);for(let i=0;i<100;i++)c.frame(frame(.2));assert.equal(c.detector.chunks.length,0);c.stop();
});
test('uncertain answer pauses even if the user interrupted its response',()=>{
  const c=controller();c.phase='capturing';c.ready({review:true});assert.equal(c.paused,true);assert.equal(c.phase,'review');c.stop();
});
test('old pending turn cannot resume a stopped conversation',async()=>{
  let done;const c=controller({onTurn:()=>new Promise(r=>done=r)});c.phase='capturing';
  const submitted=c.submit({chunks:[frame(.1)],sampleRate:16000,reason:'manual'});c.stop();done();await submitted;
  assert.equal(c.phase,'ended');assert.equal(c.active,false);
});
test('long turn waits for explicit send and cannot create repeated automatic requests',async()=>{
  let turns=0;const c=controller({onTurn:async()=>turns++});c.phase='capturing';
  await c.submit({chunks:[frame(.1)],sampleRate:16000,reason:'limit'});assert.equal(c.paused,true);assert.equal(turns,0);
  await c.sendNow();assert.equal(turns,1);assert.equal(c.phase,'listening');c.stop();
});
test('stopping releases tracks and clears every buffered answer',()=>{
  let stopped=0;const c=controller();c.stream={getTracks:()=>[{stop(){stopped++}}]};c.pending={};c.stop();
  assert.equal(stopped,1);assert.equal(c.pending,null);assert.equal(c.stream,null);assert.equal(c.active,false);
});
test('a typed correction discards a pending long recording from the previous question',()=>{
  const c=controller();c.pending={chunks:[frame(.1)]};c.hold();assert.equal(c.pending,null);c.stop();
});
test('late microphone permission releases the granted stream after End',async()=>{
  let grant,stopped=0;
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{mediaDevices:{getUserMedia:()=>new Promise(r=>grant=r)}}});
  const c=new Conversation({onTurn:async()=>{}});const start=c.start();c.stop();
  grant({getTracks:()=>[{stop(){stopped++}}]});assert.equal(await start,false);assert.equal(stopped,1);assert.equal(c.active,false);
});
