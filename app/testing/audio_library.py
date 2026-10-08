"""Small owned, durable synthetic recording library; strict PCM input limits."""
import base64
import io
import json
import uuid
import wave
from app.testing.references import script
from app.testing.evaluation import digest

MAX_BYTES=3_000_000
MAX_CLIPS=20


def validate_wav(data):
    if not data or len(data)>MAX_BYTES:raise ValueError('Use a PCM WAV smaller than 3 MB.')
    try:
        with wave.open(io.BytesIO(data),'rb') as wav:
            rate=wav.getframerate();channels=wav.getnchannels();width=wav.getsampwidth();frames=wav.getnframes()
            if wav.getcomptype()!='NONE' or width!=2 or channels!=1 or rate not in {16000,22050,24000,44100,48000}:
                raise ValueError('Use mono, 16-bit PCM WAV at 16–48 kHz.')
            duration=frames/rate
            if not 1<=duration<=90:raise ValueError('Record 1–90 seconds.')
            if len(wav.readframes(frames))!=frames*channels*width:raise ValueError('The WAV is truncated.')
    except (wave.Error,EOFError) as exc:raise ValueError('This file is not a readable PCM WAV.') from exc
    return {'duration_ms':round(duration*1000,2),'sample_rate':rate,'channels':channels,'sample_width':width}


class AudioLibrary:
    def __init__(self,database):self.database=database
    def initialize(self):
        with self.database.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS demo_audio_clips (clip_id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS demo_audio_owner ON demo_audio_clips(owner_id,created_at)')
    def add(self,owner_id,script_id,data,attested):
        from app.services.demo_report_service import DemoReportError,now
        reference=script(script_id)
        if not reference:raise DemoReportError('INVALID_SCRIPT','Choose a fixed fictional recording script.')
        if not attested:raise DemoReportError('REFERENCE_REQUIRED','Listen to the recording and confirm it matches the script. Use fictional data only.')
        try:info=validate_wav(data)
        except ValueError as exc:raise DemoReportError('INVALID_AUDIO',str(exc)) from exc
        row={'clip_id':'CLIP-'+uuid.uuid4().hex,'created_at':now(),'script':reference,
             'audio_sha256':__import__('hashlib').sha256(data).hexdigest(),'reference_sha256':digest(reference),
             'reference_attestation':'Uploader listened and confirmed exact fictional script; not independent annotation.',
             **info,'wav_base64':base64.b64encode(data).decode()}
        with self.database.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT COUNT(*) FROM demo_audio_clips WHERE owner_id=?',(owner_id,)).fetchone()[0]>=MAX_CLIPS:
                raise DemoReportError('LIBRARY_FULL','The library holds 20 clips. Delete an unused clip first.')
            db.execute('INSERT INTO demo_audio_clips VALUES (?,?,?,?)',(row['clip_id'],owner_id,row['created_at'],json.dumps(row,ensure_ascii=False)))
        return self.public(row)
    @staticmethod
    def public(row):return {k:v for k,v in row.items() if k!='wav_base64'}
    def list(self,owner_id):
        with self.database.connection() as db:
            rows=db.execute('SELECT payload FROM demo_audio_clips WHERE owner_id=? ORDER BY created_at DESC',(owner_id,)).fetchall()
        return [self.public(json.loads(r[0])) for r in rows]
    def get(self,owner_id,clip_id):
        from app.services.demo_report_service import DemoReportError
        with self.database.connection() as db:
            row=db.execute('SELECT payload FROM demo_audio_clips WHERE owner_id=? AND clip_id=?',(owner_id,clip_id)).fetchone()
        if not row:raise DemoReportError('AUDIO_NOT_FOUND','Recording not found.')
        return json.loads(row[0])
    def delete(self,owner_id,clip_id):
        self.get(owner_id,clip_id)
        with self.database.connection() as db:db.execute('DELETE FROM demo_audio_clips WHERE owner_id=? AND clip_id=?',(owner_id,clip_id))
        return {'deleted':True}


def audio_catalog(clips):
    return [{'id':c['clip_id'],'title':c['script']['title'],'category':'Recorded audio',
        'input':c['script']['reference'],'expected':'Measure raw ASR errors, medicine names, translation instruction preservation and text role agreement.',
        'scope':'Uploaded PCM recording through real transcription/role/translation pipeline. No microphone capture, acoustic DER or clinical accuracy claim.',
        'reference':AudioLibrary.public(c)} for c in clips]
