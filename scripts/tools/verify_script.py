import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from receptionist.urdu_stt_utils import evaluate_urdu_transcript, resample_audio
# 1) Corrupted mixed Urdu/English sample
corrupted_text = "Hello doctor, how are you? Mere sar mein dard hai. I am a doctor."
suspicious1, reason1 = evaluate_urdu_transcript(corrupted_text)
print(f"Test 1 (Corrupted): Suspicious={suspicious1}, Reason={reason1}")
# 2) Normal Urdu medical sample
normal_text = "میرے سر میں بہت درد ہے اور مجھے بخار بھی محسوس ہو رہا ہے۔"
suspicious2, reason2 = evaluate_urdu_transcript(normal_text)
print(f"Test 2 (Normal): Suspicious={suspicious2}, Reason={reason2}")
# 3) resample_audio verify length reduction
original_len = 48000
dummy_audio = np.zeros(original_len)
resampled_audio = resample_audio(dummy_audio, 48000, 16000)
resampled_len = len(resampled_audio)
print(f"Test 3 (Resample): Original Length={original_len}, Resampled Length={resampled_len}, Ratio={resampled_len/original_len}")
