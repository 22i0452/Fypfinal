import asyncio
import sys
import json
import traceback
from llm_diarizer import LLMDiarizer
class MockLLMDiarizer(LLMDiarizer):
    async def _request_diarization(self, transcript):
        return [{"speaker": "Patient", "text": transcript}]
async def main():
    transcript = (
        "اسلام علیکم دکٹر صاحب کیسا ہے؟ Hello doctor, how are you? "
        "ہاں علیکم اسلام علیکم، میں ٹھیک ہوں، میں بھائی چلتا ہوں، کیسا ہوں آپ کا؟ Hello doctor, how are you? I am fine, how are you? "
        "ڈاکٹر صاحب اسی میں میں چل رہا تھا، چلتے چلتے، ایک دم میرا پاؤں پیری طرح مر گیا۔ ڈاکٹر صاحب اسی میں میں چل رہا تھا، چلتے چلتے، ایک دم میرا پاؤن پیری طرح مر گیا۔ My leg was completely injured. "
        "مریض اپنی تکالیف بیان کر رہا ہے جیسے بخار، کمر درد، پیٹ درد، کمر درد، کمر درد۔ "
        "اچھا سب سے پہلے تو یہ ہے کہ آپ کو میں کچھ پینک لگز لکھ رہا ہوں۔ I am giving you some pain killers. "
        "آپ کا جو اللہ تعالیٰ و عبادتی تو اس پر ٹھین گئے۔ Your other pain killers are fine. "
        "دوسری چیز جو میں آپ کو کر رہا ہوں، کافی زیادہ اعتراض کرتا ہے۔ The second thing that I am telling you is that you have to take a lot of care. "
        "آپ کے پرلی کافی نوزلز وطارہ تو یہ مزید خراب ہو سکتی ہے۔ Your back can be damaged if you take too much care. "
        "اس کے علاوہ آپ اور بھی اپنا اعتراض کر سکتے ہیں۔ Apart from that, you can take more care. "
        "اور جتنا بھی ہو سکتا ہے آپ بس چلنے سے فریض کریں۔ And as much as possible, you just have to stop walking. "
        "اور پھر اس کے علاوہ آپ کو میں کچھ ایکسلی ریپورٹ لکھ کے دے رہا ہوں And then, I am giving you some Excel reports. "
        "اور ایم ار آئی اور سی ٹی سکين لکھ کے دے رہا ہوں And I am giving you MRI and CT Scan. "
        "اس ایم ار آئی آپ نے آئی پنٹراسٹ کے ساتھ کروانے ہے۔ You have to get this MRI done with eye contrast. "
        "انشاء اللہ جب آپ اگلی بار آئیں گے ریپورٹ کے ساتھ So, God willing, when you come next time with the report "
        "اگر آپ کو ایک بہترین حالت پر بات کرتے ہیں تو میں آپ کو بتا سکتا ہوں کہ یہ ایک ایسا محبت ہے۔ If you have a better idea, I will tell you that it is a good idea."
    )
    try:
        diarizer = MockLLMDiarizer(api_key="mock-key")
        result = await diarizer.diarize(transcript)
        speakers = [turn['speaker'] for turn in result]
        print(f"Speakers: {speakers}")
        for i, turn in enumerate(result):
            text = turn['text']
            preview = text[:120] + ("..." if len(text) > 120 else "")
            print(f"Turn {i+1} ({turn['speaker']}): {preview}")
    except Exception:
        traceback.print_exc()
if __name__ == '__main__':
    asyncio.run(main())