"""One server for HTML, APIs, audio and WebSockets. No Vite/Node proxy required."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    if '--published' in sys.argv or (os.environ.get('DATABASE_URL') and os.environ.get('DEMO_ACCESS_PASSWORD')):
        os.environ['APP_ENV'] = 'demo'
        os.environ['STORAGE_BACKEND'] = 'postgres'
        os.environ['MOCK_OTP_ENABLED'] = 'false'
        os.environ['SHOW_DEV_OTP'] = 'false'
        os.environ['DEMO_PROFILES_ENABLED'] = 'true'
        os.environ.setdefault('DEVELOPMENT_QUICK_START_ENABLED', 'true')
        os.environ.setdefault('DEMO_TESTING_ENABLED', 'true')
    import uvicorn
    uvicorn.run('app.main:app', host='0.0.0.0', port=int(os.environ.get('PORT', '8000')),
                workers=1, proxy_headers=True, forwarded_allow_ips='*')


if __name__ == '__main__':
    main()
