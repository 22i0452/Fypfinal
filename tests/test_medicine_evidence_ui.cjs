// Real evidence markup: saved source, dose/stop wording, links and dirty state.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const context={document:{addEventListener(){}},renderSoapNote(){},soapDraftTouched:false,
 soapSectionEditing:{},escHtml:escape,escAttr:escape,studioIcon:()=>''};
vm.createContext(context);vm.runInContext(fs.readFileSync('scribe/assets/medicine-evidence.js','utf8'),context);
const report={scope:'Source links only.',items:[{final_name:'Panadol',speaker:'Doctor',utterance_id:'U1',
 note_version:2,original:'پیناڈول',proposed_name:'Panadol',confirmed_name:'Panadol',catalogue:{name:'Panadol'},
 doctor_reviewed:true,source_instruction:'Take Panadol 500 mg. Do not take Motilium.',soap_links:[{section:'plan'}]}]};
let html=context.medicineEvidenceMarkup(report);
assert.match(html,/پیناڈول/);assert.match(html,/500 mg/);assert.match(html,/Do not take Motilium/);
assert.match(html,/data-medicine-evidence-source="U1"/);assert.match(html,/data-medicine-soap-section="plan"/);
assert.match(html,/Doctor wording review recorded/);assert.doesNotMatch(html,/ disabled/);
context.soapDraftTouched=true;html=context.medicineEvidenceMarkup(report);
assert.match(html,/Save your SOAP changes/);assert.match(html,/ disabled/);
assert.equal(context.medicineEvidenceMarkup({items:[]}),'');
report.items[0].original='<script>danger</script>';
assert.doesNotMatch(context.medicineEvidenceMarkup(report),/<script>/);
console.log('Medicine evidence markup: wording, links, review, dirty state and escaping passed.');
