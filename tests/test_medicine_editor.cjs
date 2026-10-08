// Synthetic UI checks: execute the real editor markup without audio or networking.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const escape = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
  '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
}[ch]));
const context = {
  window: {}, document: {addEventListener() {}},
  renderTranscript() {}, renderClinicFlow() {}, renderSoapNote() {},
  escHtml: escape, escAttr: escape, visitLocked: () => false,
  studioIcon: () => '',
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../scribe/assets/medicines.js'), 'utf8'), context);
const turn = {
  medicine_checks: {mentions: [{source:'مورتیدیوم', name:'مورتیدیوم',
    status:'unknown_name', start:0, suggested_english:'Motilium'}]},
};
const proposed = context.window.medicineEditorFields(turn);
assert.match(proposed, /value="Motilium"/);
assert.doesNotMatch(proposed, /data-medicines-reviewed\s+checked/);
const confirmed = context.window.medicineEditorFields({...turn, medicines_reviewed:true,
  medicine_review:{spellings:{'مورتیدیوم':'Doctor-selected spelling'}}});
assert.match(confirmed, /value="Doctor-selected spelling"/);
assert.match(confirmed, /data-medicines-reviewed checked/);
assert.equal(context.window.medicineEditorFields({medicine_checks:{mentions:[]}}), '');
console.log('Medicine editor: automatic spelling, explicit confirmation, doctor override and empty state passed.');
