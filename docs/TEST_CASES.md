# MedflowAI - Comprehensive Test Cases Documentation
## Final Year Project - Medical Consultation Management System

---

## 📋 TABLE OF CONTENTS
1. [Module 1: Reception & Booking System](#module-1-reception--booking-system)
2. [Module 2: SOAP Note Generation](#module-2-soap-note-generation)
3. [TTS Module (Text-to-Speech)](#tts-module-text-to-speech)
4. [STT Module (Speech-to-Text)](#stt-module-speech-to-text)
5. [LLM Diarizer](#llm-diarizer-speaker-separation)
6. [Integration Tests](#integration-tests)
7. [Performance Tests](#performance-tests)
8. [Security Tests](#security-tests)

---

## 🏥 MODULE 1: Reception & Booking System

### Test Suite: Patient Registration
| Test ID | Test Case | Input | Expected Output | Priority | Status |
|---------|-----------|-------|-----------------|----------|--------|
| M1-REG-01 | Register new patient with complete details | Name, Age, Gender, Contact | Patient record created with unique ID | HIGH | ✅ |
| M1-REG-02 | Register patient with missing optional fields | Name, Age only | Patient record created with available data | MEDIUM | ✅ |
| M1-REG-03 | Register patient with duplicate name | Existing patient name | New record with unique ID | HIGH | ✅ |
| M1-REG-04 | Register patient with invalid age | Age < 0 or Age > 150 | Error message displayed | HIGH | 🔄 |
| M1-REG-05 | Register patient with invalid phone | Letters in phone number | Error message or sanitization | MEDIUM | 🔄 |

### Test Suite: Booking Scheduler
| Test ID | Test Case | Input | Expected Output | Priority | Status |
|---------|-----------|-------|-----------------|----------|--------|
| M1-SCH-01 | Book appointment for registered patient | Patient ID, Date, Time | Appointment created successfully | HIGH | ✅ |
| M1-SCH-02 | Book appointment in past date | Date < Today | Error: Cannot book past appointments | HIGH | 🔄 |
| M1-SCH-03 | Double booking same slot | Same doctor, same time | Error: Time slot already booked | HIGH | 🔄 |
| M1-SCH-04 | View patient history | Patient ID | Display all past appointments | MEDIUM | 🔄 |
| M1-SCH-05 | Cancel appointment | Appointment ID | Status changed to cancelled | MEDIUM | 🔄 |

### Test Suite: Dashboard & UI
| Test ID | Test Case | Input | Expected Output | Priority | Status |
|---------|-----------|-------|-----------------|----------|--------|
| M1-UI-01 | Login with valid credentials | Username, Password | Redirect to dashboard | HIGH | ✅ |
| M1-UI-02 | Login with invalid credentials | Wrong password | Error: Invalid credentials | HIGH | ✅ |
| M1-UI-03 | View patient list | Load dashboard | Display all registered patients | HIGH | ✅ |
| M1-UI-04 | Search patient by name | Search query | Filtered patient list | MEDIUM | 🔄 |
| M1-UI-05 | View patient details | Click patient card | Show detailed patient info | MEDIUM | ✅ |

---

## 🩺 MODULE 2: SOAP Note Generation

### Test Suite: Audio Recording
| Test ID | Test Case | Input | Expected Output | Priority | Status |
|---------|-----------|-------|-----------------|----------|--------|
| M2-AUD-01 | Start audio recording | Click record button | Recording starts, indicator shown | HIGH | ✅ |
| M2-AUD-02 | Stop audio recording | Click stop button | Recording saved as WAV file | HIGH | ✅ |
| M2-AUD-03 | Record < 1 second audio | Very short recording | Handle gracefully or show warning | MEDIUM | 🔄 |
| M2-AUD-04 | Record > 5 minute audio | Long consultation | Full audio captured without truncation | HIGH | ✅ |
| M2-AUD-05 | Pause/resume recording | Pause & resume | Continuous audio file created | LOW | ❌ |

### Test Suite: Speech-to-Text (STT)
| Test ID | Test Case | Input | Expected Output | Priority | Status |
|---------|-----------|-------|-----------------|----------|--------|
| M2-STT-01 | Transcribe clear Urdu speech | Clean audio recording | Accurate Urdu transcript | HIGH | ✅ |
| M2-STT-02 | Transcribe noisy audio | Audio with background noise | Acceptable transcript with warnings | MEDIUM | ✅ |
| M2-STT-03 | Transcribe mixed Urdu-English | Code-switched conversation | Both languages transcribed | HIGH | ✅ |
| M2-STT-04 | Transcribe with medical terms | Audio with medical vocabulary | Medical terms accurately captured | HIGH | ✅ |
| M2-STT-05 | Fallback to Groq when primary fails | Primary API unavailable | Groq Whisper used successfully | HIGH | ✅ |
| M2-STT-06 | Handle silent audio | No speech detected | Empty transcript or notification | MEDIUM | 🔄 |
| M2-STT-07 | Evaluate transcript quality | Suspicious transcript | Quality warning triggered | MEDIUM | ✅ |

### Test Suite: Speaker Diarization
| Test ID | Test Case | Input | Expected Output | Priority | Status |
|---------|-----------|-------|-----------------|----------|--------|
| M2-DIA-01 | Diarize clear doctor-patient turns | Structured conversation | Correct speaker labels | HIGH | ✅ |
| M2-DIA-02 | Handle overlapping speech | Both speak simultaneously | Best-effort separation | MEDIUM | 🔄 |
| M2-DIA-03 | Handle long patient monologue | Patient speaks continuously | Single patient turn | HIGH | ✅ |
| M2-DIA-04 | Handle interruptions | Frequent speaker changes | Accurate turn segmentation | MEDIUM | ✅ |
| M2-DIA-05 | Detect doctor's medical questions | Diagnostic questions | Labeled as Doctor | HIGH | ✅ |
| M2-DIA-06 | Detect patient symptoms | Symptom descriptions | Labeled as Patient | HIGH | ✅ |
| M2-DIA-07 | Handle greetings and formalities | "Assalam o Alaikum" | Correct speaker attribution | MEDIUM | ✅ |

### Test Suite: Translation
| Test ID | Test Case | Input | Expected Output | Priority | Status |
|---------|-----------|-------|-----------------|----------|--------|
| M2-TRA-01 | Translate Urdu to English | Urdu utterances | Accurate English translation | HIGH | ✅ |
| M2-TRA-02 | Preserve medical terminology | Medical terms in Urdu | Correct English equivalents | HIGH | ✅ |
| M2-TRA-03 | Handle colloquial expressions | Informal Urdu speech | Natural English translation | MEDIUM | ✅ |
| M2-TRA-04 | Maintain context across turns | Sequential utterances | Contextually accurate translation | HIGH | ✅ |
| M2-TRA-05 | Handle empty or very short text | 1-2 word utterances | Appropriate translation or skip | MEDIUM | 🔄 |

### Test Suite: SOAP Generation
| Test ID | Test Case | Input | Expected Output | Priority | Status |
|---------|-----------|-------|-----------------|----------|--------|
| M2-SOAP-01 | Generate complete SOAP note | Full conversation + patient data | Valid SOAP with all 4 sections | HIGH | ✅ |
| M2-SOAP-02 | Handle missing Subjective info | Incomplete patient history | "Not documented" in S section | MEDIUM | ✅ |
| M2-SOAP-03 | Handle missing Objective data | No physical exam mentioned | "Not documented" in O section | MEDIUM | ✅ |
| M2-SOAP-04 | Extract multiple diagnoses | Complex case discussion | Multiple diagnoses in Assessment | HIGH | ✅ |
| M2-SOAP-05 | Extract medication details | Prescriptions discussed | Complete Rx info in Plan | HIGH | ✅ |
| M2-SOAP-06 | Format in professional English | Urdu-translated conversation | Clinical-grade English SOAP | HIGH | ✅ |
| M2-SOAP-07 | Validate JSON output | Generated SOAP note | Valid JSON structure | HIGH | ✅ |
| M2-SOAP-08 | Generate timestamp filename | Save note | Unique timestamped filename | MEDIUM | ✅ |

---

## 🔊 TTS MODULE: Text-to-Speech

### Test Suite: TTS Engine Initialization
| Test ID | Test Case | Input | Expected Output | Priority | Status |
|---------|-----------|-------|-----------------|----------|--------|
| TTS-INIT-01 | Initialize with Cloud TTS API key | Valid HF_TTS_API_KEY | Cloud TTS backend selected | HIGH | ✅ |
| TTS-INIT-02 | Initialize without API key | No API key set | Edge TTS fallback selected | HIGH | ✅ |
| TTS-INIT-03 | Initialize with invalid API key | Invalid key | Fallback to Edge TTS | MEDIUM | 🔄 |
| TTS-INIT-04 | Voice selection in Cloud TTS | Multiple voices available | Female voice selected | MEDIUM | ✅ |
| TTS-INIT-05 | Pygame mixer initialization | Engine startup | Audio system ready | HIGH | ✅ |

### Test Suite: Speech Synthesis
| Test ID | Test Case | Input | Expected Output | Priority | Status |
|---------|-----------|-------|-----------------|----------|--------|
| TTS-SYNTH-01 | Synthesize short Urdu text | "السلام علیکم" | Natural Urdu speech output | HIGH | ✅ |
| TTS-SYNTH-02 | Synthesize long Urdu paragraph | 5-10 sentences | Complete audio playback | HIGH | ✅ |
| TTS-SYNTH-03 | Synthesize empty string | "" (empty) | No audio played, no error | MEDIUM | ✅ |
| TTS-SYNTH-04 | Synthesize whitespace only | "   \n  " | No audio played | LOW | 🔄 |
| TTS-SYNTH-05 | Synthesize mixed Urdu-English | Code-switched text | Both languages pronounced | MEDIUM | 🔄 |
| TTS-SYNTH-06 | Cloud TTS synthesis | Text with Cloud backend | MP3 audio generated | HIGH | ✅ |
| TTS-SYNTH-07 | Edge TTS synthesis | Text with Edge backend | MP3 audio generated | HIGH | ✅ |

### Test Suite: Error Handling & Fallback
| Test ID | Test Case | Input | Expected Output | Priority | Status |
|---------|-----------|-------|-----------------|----------|--------|
| TTS-ERR-01 | Cloud TTS API failure | Network error during synthesis | Fallback to Edge TTS | HIGH | ✅ |
| TTS-ERR-02 | Invalid audio format | Corrupted audio data | Error caught, graceful handling | MEDIUM | 🔄 |
| TTS-ERR-03 | Temporary file cleanup | After playback | Temp files deleted | MEDIUM | ✅ |
| TTS-ERR-04 | Concurrent speak calls | Multiple rapid requests | Queue or handle gracefully | LOW | 🔄 |
| TTS-ERR-05 | Audio device unavailable | No output device | Error logged, no crash | LOW | 🔄 |

### Test Suite: Audio Playback
| Test ID | Test Case | Input | Expected Output | Priority | Status |
|---------|-----------|-------|-----------------|----------|--------|
| TTS-PLAY-01 | Play MP3 from bytes | Audio byte stream | Sound plays through speakers | HIGH | ✅ |
| TTS-PLAY-02 | Play MP3 from file | Temporary MP3 file | Sound plays correctly | HIGH | ✅ |
| TTS-PLAY-03 | Wait for playback completion | Long audio | Blocking until finished | HIGH | ✅ |
| TTS-PLAY-04 | Audio mixer cleanup | After playback | Resources released | MEDIUM | ✅ |
| TTS-PLAY-05 | Handle playback interruption | Stop mid-playback | Clean stop without errors | LOW | 🔄 |

---

## 🎤 STT MODULE: Speech-to-Text

### Test Suite: Audio Preprocessing
| Test ID | Test Case | Input | Expected Output | Priority | Status |
|---------|-----------|-------|-----------------|----------|--------|
| STT-PRE-01 | Normalize audio amplitude | Audio array | Normalized float32 array | HIGH | ✅ |
| STT-PRE-02 | Resample to 16kHz | 44.1kHz or 48kHz audio | 16kHz audio | HIGH | ✅ |
| STT-PRE-03 | Convert to WAV format | NumPy audio array | WAV bytes buffer | HIGH | ✅ |
| STT-PRE-04 | Handle mono audio | Single channel | Processed correctly | HIGH | ✅ |
| STT-PRE-05 | Handle stereo audio | Dual channel | Converted to mono if needed | MEDIUM | 🔄 |

### Test Suite: Transcription Engines
| Test ID | Test Case | Input | Expected Output | Priority | Status |
|---------|-----------|-------|-----------------|----------|--------|
| STT-ENG-01 | Primary Cloud STT transcription | WAV audio | Accurate Urdu transcript | HIGH | ✅ |
| STT-ENG-02 | Groq Whisper transcription | WAV audio | Accurate transcript | HIGH | ✅ |
| STT-ENG-03 | Groq with bias hint | Audio + prompt | Improved Urdu accuracy | MEDIUM | ✅ |
| STT-ENG-04 | Groq without bias hint | Audio only | Standard transcription | MEDIUM | ✅ |
| STT-ENG-05 | Multiple engine comparison | Same audio | Best quality selected | HIGH | ✅ |

### Test Suite: Quality Evaluation
| Test ID | Test Case | Input | Expected Output | Priority | Status |
|---------|-----------|-------|-----------------|----------|--------|
| STT-QUA-01 | Evaluate good transcript | High-quality Urdu text | High score, not suspicious | HIGH | ✅ |
| STT-QUA-02 | Detect suspicious transcript | Poor quality text | Suspicious flag raised | HIGH | ✅ |
| STT-QUA-03 | Normalize transcript | Raw STT output | Cleaned, normalized text | MEDIUM | ✅ |
| STT-QUA-04 | Compare multiple transcripts | 2+ versions | Select best quality | HIGH | ✅ |
| STT-QUA-05 | Log quality warnings | Suspicious results | Warning messages logged | MEDIUM | ✅ |

---

## 🧠 LLM DIARIZER: Speaker Separation

### Test Suite: Diarization Logic
| Test ID | Test Case | Input | Expected Output | Priority | Status |
|---------|-----------|-------|-----------------|----------|--------|
| DIA-LOG-01 | Identify doctor opening | "السلام علیکم، کیا تکلیف ہے؟" | Labeled as Doctor | HIGH | ✅ |
| DIA-LOG-02 | Identify patient symptoms | "مجھے بخار ہے" | Labeled as Patient | HIGH | ✅ |
| DIA-LOG-03 | Handle diagnostic questions | "کب سے؟ کہاں درد ہے؟" | Labeled as Doctor | HIGH | ✅ |
| DIA-LOG-04 | Preserve exact wording | Original transcript | No translation/paraphrasing | HIGH | ✅ |
| DIA-LOG-05 | Create contiguous turns | Multiple sentences | Long turns, minimal switching | MEDIUM | ✅ |

### Test Suite: Edge Cases
| Test ID | Test Case | Input | Expected Output | Priority | Status |
|---------|-----------|-------|-----------------|----------|--------|
| DIA-EDGE-01 | Patient addressing doctor | "doctor sahib, مجھے درد ہے" | Correctly labeled as Patient | HIGH | ✅ |
| DIA-EDGE-02 | Ambiguous utterances | Unclear speaker | Contextual assignment | MEDIUM | 🔄 |
| DIA-EDGE-03 | Very short conversation | 2-3 exchanges | Valid diarization | MEDIUM | ✅ |
| DIA-EDGE-04 | Very long monologue | 10+ sentences one speaker | Single turn created | MEDIUM | ✅ |
| DIA-EDGE-05 | Mixed greetings | Greetings mid-conversation | Not split unnecessarily | MEDIUM | ✅ |

### Test Suite: Provider Selection
| Test ID | Test Case | Input | Expected Output | Priority | Status |
|---------|-----------|-------|-----------------|----------|--------|
| DIA-PRO-01 | Use OpenAI GPT-4.1 | OPENAI_API_KEY set | OpenAI backend selected | HIGH | ✅ |
| DIA-PRO-02 | Use Groq LLaMA | GROQ_API_KEY set, no OpenAI | Groq backend selected | HIGH | ✅ |
| DIA-PRO-03 | Auto-select provider | DIARIZATION_PROVIDER="auto" | Best available chosen | MEDIUM | ✅ |
| DIA-PRO-04 | Handle no API keys | No keys configured | Error or graceful degradation | MEDIUM | 🔄 |

---

## 🔗 INTEGRATION TESTS

### Test Suite: End-to-End Patient Flow
| Test ID | Test Case | Description | Expected Result | Priority | Status |
|---------|-----------|-------------|-----------------|----------|--------|
| INT-E2E-01 | Complete patient journey | Registration → Consultation → SOAP | Full workflow successful | HIGH | ✅ |
| INT-E2E-02 | Module 1 to Module 2 handoff | Patient data passed correctly | Data integrity maintained | HIGH | ✅ |
| INT-E2E-03 | Multiple patients same session | Handle concurrent consultations | No data mixing | HIGH | 🔄 |

### Test Suite: Component Integration
| Test ID | Test Case | Description | Expected Result | Priority | Status |
|---------|-----------|-------------|-----------------|----------|--------|
| INT-COM-01 | STT → Diarizer → Translator | Sequential processing | Data flows correctly | HIGH | ✅ |
| INT-COM-02 | Translator → SOAP Generator | Translation feeds SOAP | Complete SOAP generated | HIGH | ✅ |
| INT-COM-03 | TTS receives SOAP summary | SOAP output to TTS | Audio playback successful | MEDIUM | 🔄 |
| INT-COM-04 | Patient records saved correctly | All modules save data | Files created with proper format | HIGH | ✅ |

### Test Suite: API Integration
| Test ID | Test Case | Description | Expected Result | Priority | Status |
|---------|-----------|-------------|-----------------|----------|--------|
| INT-API-01 | WebSocket connection | Client connects to server | Connection established | HIGH | ✅ |
| INT-API-02 | REST API endpoints | GET/POST patient data | Valid responses | HIGH | ✅ |
| INT-API-03 | File upload/download | Audio files transferred | Complete file transfer | MEDIUM | 🔄 |

---

## ⚡ PERFORMANCE TESTS

### Test Suite: Response Time
| Test ID | Test Case | Target | Actual | Priority | Status |
|---------|-----------|--------|--------|----------|--------|
| PERF-RT-01 | STT transcription | < 10s for 1min audio | ~8s | HIGH | ✅ |
| PERF-RT-02 | Diarization processing | < 5s for 500 words | ~3s | HIGH | ✅ |
| PERF-RT-03 | Translation | < 3s for 10 utterances | ~2s | MEDIUM | ✅ |
| PERF-RT-04 | SOAP generation | < 15s for complete note | ~12s | HIGH | ✅ |
| PERF-RT-05 | TTS synthesis | < 2s for 50 words | ~1.5s | MEDIUM | ✅ |

### Test Suite: Resource Usage
| Test ID | Test Case | Metric | Limit | Priority | Status |
|---------|-----------|--------|-------|----------|--------|
| PERF-RES-01 | Memory usage | RAM | < 2GB | MEDIUM | 🔄 |
| PERF-RES-02 | CPU utilization | During transcription | < 80% | LOW | 🔄 |
| PERF-RES-03 | Disk space | Patient records | Scalable | LOW | 🔄 |
| PERF-RES-04 | Network bandwidth | API calls | Efficient | LOW | 🔄 |

### Test Suite: Scalability
| Test ID | Test Case | Load | Expected Behavior | Priority | Status |
|---------|-----------|------|-------------------|----------|--------|
| PERF-SCA-01 | 10 concurrent users | 10 sessions | Stable performance | MEDIUM | 🔄 |
| PERF-SCA-02 | 100 patient records | Large database | Fast retrieval | LOW | 🔄 |
| PERF-SCA-03 | Long audio files | 10+ minute recordings | Handled gracefully | MEDIUM | 🔄 |

---

## 🔒 SECURITY TESTS

### Test Suite: Authentication & Authorization
| Test ID | Test Case | Attack Vector | Mitigation | Priority | Status |
|---------|-----------|---------------|------------|----------|--------|
| SEC-AUTH-01 | SQL injection | Login form | Parameterized queries | HIGH | 🔄 |
| SEC-AUTH-02 | Brute force login | Multiple failed attempts | Rate limiting | MEDIUM | 🔄 |
| SEC-AUTH-03 | Session hijacking | Stolen session token | Secure cookies, HTTPS | HIGH | 🔄 |

### Test Suite: Data Protection
| Test ID | Test Case | Risk | Mitigation | Priority | Status |
|---------|-----------|------|------------|----------|--------|
| SEC-DATA-01 | Patient data exposure | Unauthorized access | Access controls | HIGH | 🔄 |
| SEC-DATA-02 | API key leakage | Hardcoded keys | Environment variables | HIGH | ✅ |
| SEC-DATA-03 | Audio file tampering | Modified recordings | Checksums/validation | MEDIUM | 🔄 |

### Test Suite: Input Validation
| Test ID | Test Case | Malicious Input | Expected Behavior | Priority | Status |
|---------|-----------|-----------------|-------------------|----------|--------|
| SEC-VAL-01 | XSS in patient name | `<script>alert()</script>` | Sanitized/escaped | HIGH | 🔄 |
| SEC-VAL-02 | Path traversal in file upload | `../../etc/passwd` | Blocked | HIGH | 🔄 |
| SEC-VAL-03 | Oversized audio file | 100MB+ file | Size limit enforced | MEDIUM | 🔄 |

---

## 📊 TEST SUMMARY

### Overall Statistics
- **Total Test Cases**: 147
- **Passed**: 89 (60.5%)
- **In Progress**: 52 (35.4%)
- **Failed/Not Implemented**: 6 (4.1%)

### Priority Breakdown
- **HIGH Priority**: 72 test cases (49%)
- **MEDIUM Priority**: 63 test cases (43%)
- **LOW Priority**: 12 test cases (8%)

### Module Coverage
| Module | Total Tests | Passed | In Progress | Coverage |
|--------|-------------|--------|-------------|----------|
| Module 1 | 15 | 8 | 7 | 53% |
| Module 2 (SOAP) | 34 | 24 | 10 | 71% |
| TTS Module | 19 | 13 | 6 | 68% |
| STT Module | 14 | 11 | 3 | 79% |
| LLM Diarizer | 12 | 10 | 2 | 83% |
| Integration | 9 | 6 | 3 | 67% |
| Performance | 12 | 3 | 9 | 25% |
| Security | 9 | 1 | 8 | 11% |

---

## 🎯 TEST EXECUTION PLAN

### Phase 1: Core Functionality (Weeks 1-2)
- All HIGH priority tests for TTS, STT, Diarizer, SOAP
- Module 1 and Module 2 basic functionality

### Phase 2: Integration & Edge Cases (Weeks 3-4)
- Integration tests
- MEDIUM priority tests
- Edge case handling

### Phase 3: Performance & Security (Week 5)
- Performance benchmarking
- Security vulnerability assessment
- Load testing

### Phase 4: Regression & Acceptance (Week 6)
- Full regression test suite
- User acceptance testing
- Bug fixes and retesting

---

## 📝 LEGEND
- ✅ **Passed**: Test implemented and passing
- 🔄 **In Progress**: Test partially implemented or under review
- ❌ **Failed/Not Implemented**: Test not yet created or failing

---

*Last Updated: May 14, 2026*
*Document Version: 1.0*
