"""Synthetic medicine workflow fixture; never loaded by the production app."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests.evidence_fixture import app,c,qa_gateway
from app.services.documentation_service import TranscribedText
from medflow.domain.models import TranscriptUtterance
from medflow.domain.enums import Speaker

source='میں آپ کو پیناڈول دے رہا ہوں۔ فکسج دوائی لیں۔'
def transcribe(*args,**kwargs):return TranscribedText(source,source)
def diarize(text,*,patient,transcript_id):
    return [TranscriptUtterance(utterance_id='U1',transcript_id=transcript_id,speaker=Speaker.DOCTOR,original_text='میں آپ کو پیناڈول دے رہا ہوں۔'),
            TranscriptUtterance(utterance_id='U2',transcript_id=transcript_id,speaker=Speaker.DOCTOR,original_text='فکسج دوائی لیں۔')]
c.documentation_service.transcribe=transcribe
c.documentation_service.diarize=diarize
qa_gateway._adapter('mock').set_response('translation',{'conversation':[{'utterance_id':'U1','text':'Take painkillers.'},{'utterance_id':'U2','text':'Take fixed medicine.'}]})
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8765,log_level='warning')
