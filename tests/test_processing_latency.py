"""Deterministic provider contracts and budgets; no live latency claims."""
import json
import unittest
from unittest.mock import patch, MagicMock

from security_guardrails import Actor, SecureLLMGateway
from security_guardrails.gateway import GatewaySecurityError
from security_guardrails.provider_adapters import OpenAIProviderAdapter, OpenRouterProviderAdapter, GroqProviderAdapter, ProviderAdapterError
from security_guardrails.telemetry import collect_provider_events


class ProcessingLatencyTests(unittest.TestCase):
    def test_configured_model_is_used_for_translation_and_soap(self):
        with patch.dict('os.environ', {'OPENROUTER_LLM_MODEL':'configured/model'}, clear=True):
            gateway = SecureLLMGateway(provider='openrouter')
            for task in ('translation','soap_generation','medicine_context','medicine_matching','conversation_relevance'):
                self.assertEqual(gateway._select_provider_model(task,None,None),('openrouter','configured/model'))
            self.assertEqual(gateway._select_provider_model('translation',None,'openai/gpt-4o'),('openrouter','openai/gpt-4o'))

    def test_fallbacks_share_timeout_and_record_attempt_duration(self):
        clock = [0.0]; received = []; live = []
        class Adapter:
            def __init__(self, fail):self.fail=fail
            def chat(self, **kwargs):
                received.append(kwargs['timeout_seconds']); clock[0]+=4
                if self.fail:raise ProviderAdapterError('synthetic failure')
                return '{}'
        gateway = SecureLLMGateway(provider='openrouter',adapters={'openrouter':Adapter(True),'openai':Adapter(False)})
        with patch('time.perf_counter',side_effect=lambda:clock[0]), collect_provider_events(lambda event,calls:live.append(event)) as calls:
            gateway.chat(task_type='translation',messages=[],actor=Actor(actor_id='test',role='translator'),timeout_seconds=35)
        self.assertEqual(received,[35,31])
        self.assertEqual([row['status'] for row in calls],['failed','complete'])
        self.assertEqual([row['duration_ms'] for row in calls],[4000,4000])
        self.assertEqual([row['status'] for row in live],['running','failed','running','complete'])
        self.assertTrue(calls[-1]['fallback'])
        self.assertNotIn('messages',json.dumps(calls))

    def test_exhausted_budget_does_not_start_more_requests(self):
        clock=[0.0];timeouts=[]
        class Adapter:
            def chat(self, **kwargs):
                timeouts.append(kwargs['timeout_seconds']);clock[0]+=4;return '{}'
        gateway=SecureLLMGateway(provider='mock',adapters={'mock':Adapter()})
        args=dict(task_type='translation',messages=[],actor=Actor(actor_id='test',role='translator'))
        with patch('time.perf_counter',side_effect=lambda:clock[0]), collect_provider_events(timeout_seconds=6) as calls:
            gateway.chat(**args)
            with self.assertRaisesRegex(GatewaySecurityError,'timed out'):gateway.chat(**args)
            with self.assertRaisesRegex(GatewaySecurityError,'budget exhausted'):gateway.chat(**args)
        self.assertEqual(timeouts,[6,2])
        self.assertEqual([row['status'] for row in calls],['complete','failed'])

    def test_http_adapters_receive_requested_timeout(self):
        args=dict(task_type='translation',model='synthetic',messages=[],temperature=0,max_tokens=20,timeout_seconds=7.5)
        response=MagicMock();response.__enter__.return_value=response
        response.read.return_value=b'{"choices":[{"message":{"content":"{}"}}]}'
        with patch('security_guardrails.provider_adapters.urllib_request.urlopen',return_value=response) as request:
            OpenAIProviderAdapter('synthetic').chat(**args)
        self.assertEqual(request.call_args.kwargs['timeout'],7.5)
        adapter=OpenRouterProviderAdapter('synthetic')
        with patch.object(adapter,'_post_json',return_value={'choices':[{'message':{'content':'{}'}}]}) as request:
            adapter.chat(**args)
        self.assertEqual(request.call_args.kwargs['timeout'],7.5)

    def test_groq_does_not_retry_outside_gateway_budget(self):
        with patch('groq.Groq') as client:
            client.return_value.chat.completions.create.return_value.choices[0].message.content='{}'
            adapter=GroqProviderAdapter('synthetic')
            adapter.chat(task_type='translation',model='synthetic',messages=[],temperature=0,max_tokens=20,timeout_seconds=9)
        self.assertEqual(client.call_args.kwargs['max_retries'],0)
        self.assertEqual(client.return_value.chat.completions.create.call_args.kwargs['timeout'],9)

    def test_nested_collectors_cannot_extend_deadline_and_isolate_receipts(self):
        clock=[0.0]
        from security_guardrails.telemetry import remaining_budget, provider_event
        with patch('time.perf_counter',side_effect=lambda:clock[0]), collect_provider_events(timeout_seconds=5) as outer:
            clock[0]=3
            with collect_provider_events(timeout_seconds=90) as inner:
                self.assertEqual(remaining_budget(45),2)
                provider_event('translation','mock','mock-chat','complete')
            self.assertEqual(remaining_budget(45),2)
        self.assertEqual(outer,[]);self.assertEqual(len(inner),1)
        self.assertEqual(remaining_budget(45),45)
