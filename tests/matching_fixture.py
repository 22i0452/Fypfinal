"""Automatic matching/repair and reference UI fixture. Synthetic providers only."""
from tests.evidence_fixture import app,c
from tests.test_medicine_matching import MatchingAdapter
from security_guardrails import SecureLLMGateway,set_gateway
from app.services.documentation_service import TranscribedText
from medflow.domain.models import TranscriptUtterance
from medflow.domain.enums import Speaker

sources=[('Doctor','Take mortiiduom 10 mg.'),('Patient','I have itching, skin rash and nodal skin eruptions.'),('Doctor','پیناڈول 500 mg لیں۔')]
source=' '.join(text for _,text in sources)
c.documentation_service.transcribe=lambda *args,**kwargs:TranscribedText(source,source)
def diarize(text,*,patient,transcript_id):
    return [TranscriptUtterance(utterance_id=f'U{index}',transcript_id=transcript_id,speaker=Speaker(role.upper()),original_text=text)
        for index,(role,text) in enumerate(sources,1)]
c.documentation_service.diarize=diarize
adapter=MatchingAdapter()
adapter.set_response('translation',{'conversation':[{'utterance_id':'U1','text':sources[0][1]},{'utterance_id':'U2','text':sources[1][1]},{'utterance_id':'U3','text':'Take painkillers 500 mg.'}]})
set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':adapter}))
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8765,log_level='warning')
