"""Build fresh browser fixtures from an actual isolated workflow run. No API keys."""
import argparse
import contextlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch


def prepare(output):
    from app.testing.worker import bootstrap
    with contextlib.redirect_stdout(sys.stderr),tempfile.TemporaryDirectory(prefix='medflow-evaluation-browser-') as directory:
        root=Path(directory);bootstrap(root,'synthetic')
        from tests.support import test_settings
        from app.main import create_app
        from fastapi.testclient import TestClient
        from app.services.pdf_reports import testing_pdf
        with patch('app.services.inbound_call_service.FastUrduTTS.warmup',return_value=None),TestClient(create_app(test_settings(root))) as client:
            c=client.app.state.container
            user=c.auth_repository.create_doctor('Dr. Fictional QA','browser-qa@example.test','SyntheticQA123!')
            s=c.demo_report_service;run=s.start(user.user_id,'synthetic')
            for thread in s._threads:thread.join(45)
            report=s.get(run['run_id'],user.user_id)
            if report['status']=='RUNNING':raise RuntimeError('Isolated fixture run did not finish')
            output.mkdir(parents=True,exist_ok=True)
            (output/'observed-report.json').write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
            (output/'configuration.json').write_text(json.dumps(s.capabilities(),ensure_ascii=False),encoding='utf-8')
            (output/'evaluation-report.pdf').write_bytes(testing_pdf(report))
    return {'status':report['status'],'totals':report['totals'],'checks':report['scores']['checks']}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('/tmp/medflow-evaluation-qa'))
    print(json.dumps(prepare(parser.parse_args().output)))
