"""Limits actual worker HTTP requests, including retries; never records bodies/keys."""
import json
import time
from urllib import request
from urllib.parse import urlsplit

class RequestBudget:
    def __init__(self,total=80,per_case=20):
        self.total=total;self.per_case=per_case;self.used=0;self.case_used=0;self.events=[]
    def reset_case(self):self.case_used=0;self.events=[]
    def install(self):
        original=request.urlopen
        def bounded(req,*args,**kwargs):
            url=req.full_url if hasattr(req,'full_url') else str(req)
            if urlsplit(url).hostname!='openrouter.ai':raise RuntimeError('Only configured OpenRouter requests are allowed in evaluation.')
            if self.used>=self.total or self.case_used>=self.per_case:raise RuntimeError('Evaluation provider request limit reached.')
            self.used+=1;self.case_used+=1
            model=None
            try:model=json.loads(req.data).get('model')
            except (TypeError,ValueError,AttributeError):pass
            row={'task':'http_request','provider':'openrouter','model':model,'status':'failed','timing_scope':'HTTP response headers; body read excluded'}
            started=time.perf_counter()
            try:
                # All production adapter requests use a keyword timeout.
                kwargs['timeout']=min(float(kwargs.get('timeout',20)),20)
                result=original(req,*args,**kwargs);row['status']='complete';return result
            finally:
                row['duration_ms']=round((time.perf_counter()-started)*1000,2);self.events.append(row)
        request.urlopen=bounded
