import json
import sys
from pathlib import Path

SCRIBE_DIR = Path(__file__).resolve().parents[1]
if str(SCRIBE_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIBE_DIR))

from llm_diarizer import LLMDiarizer
sample = """اسلام علیکم دکٹر صاحب کیسا ہے؟ Hello doctor, how are you? ہاں علیکم اسلام علیکم، میں ٹھیک ہوں، میں بھائی چلتا ہوں، کیسا ہوں آپ کا؟ Hello doctor, how are you? I am fine, how are you? ڈاکٹر صاحب اسی میں میں چل رہا تھا، چلتے چلتے، ایک دم میرا پاؤں پیری طرح مر گیا۔ ڈاکٹر صاحب اسی میں میں چل رہا تھا، چلتے چلتے، ایک دم میرا پاؤں پیری طرح مر گیا۔ My leg was completely injured. مریض اپنی تکالیف بیان کر رہا ہے جیسے بخار، کمر درد، پیٹ درد، کمر درد، کمر درد۔ اچھا سب سے پہلے تو یہ ہے کہ آپ کو میں کچھ پینک لگز لکھ رہا ہوں۔ I am giving you some pain killers. آپ کا جو اللہ تعالیٰ و عبادتی تو اس پر ٹھین گئے۔ Your other pain killers are fine. دوسری چیز جو میں آپ کو کر رہا ہوں، کافی زیادہ اعتراض کرتا ہے۔ The second thing that I am telling you is that you have to take a lot of care. آپ کے پرلی کافی نوزلز وطارہ تو یہ مزید خراب ہو سکتی ہے۔ Your back can be damaged if you take too much care. اس کے علاوہ آپ اور بھی اپنا اعتراض کر سکتے ہیں۔ Apart from that, you can take more care. اور جتنا بھی ہو سکتا ہے آپ بس چلنے سے فریض کریں۔ And as much as possible, you just have to stop walking. اور پھر اس کے علاوہ آپ کو میں کچھ ایکسلی ریپورٹ لکھ کے دے رہا ہوں And then, I am giving you some Excel reports. اور ایم ار آئی اور سی ٹی سکين لکھ کے دے رہا ہوں And I am giving you MRI and CT Scan. اس ایم ار آئی آپ نے آئی پنٹراسٹ کے ساتھ کروانے ہے۔ You have to get this MRI done with eye contrast. انشاء اللہ جب آپ اگلی بار آئیں گے ریپورٹ کے ساتھ So, God willing, when you come next time with the report اگر آپ کو ایک بہترین حالت پر بات کرتے ہیں تو میں آپ کو بتا سکتا ہوں کہ یہ ایک ایسا محبت ہے۔ If you have a better idea, I will tell you that it is a good idea."""
class ProbeDiarizer(LLMDiarizer):
    def __init__(self):
        pass
    def _request_diarization(self, user_message: str) -> str:
        return json.dumps({"conversation": [{"speaker": "Patient", "text": sample}]})
diarizer = ProbeDiarizer()
normalized = diarizer._normalize_text(sample)
chunks = diarizer._build_candidate_chunks(normalized)
heuristic = diarizer._cue_based_diarize(normalized)
result = diarizer.diarize_transcript(sample)
Path("probe_result.json").write_text(
    json.dumps(
        {
            "normalized": normalized,
            "chunk_count": len(chunks),
            "chunk_lengths": [len(chunk) for chunk in chunks],
            "heuristic_speakers": [entry["speaker"] for entry in heuristic],
            "heuristic_text": [entry["text"][:120] for entry in heuristic],
            "result_speakers": [entry["speaker"] for entry in result],
            "result_text": [entry["text"][:120] for entry in result],
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
