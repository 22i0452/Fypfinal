# MedflowAI - Test Case Architecture & Graphs

## 🏗️ Test Suite Architecture

```mermaid
graph TB
    subgraph "MedflowAI Test Suite"
        Root[Test Root<br/>147 Total Tests]
        
        Root --> M1[Module 1: Reception & Booking<br/>15 Tests | 53% Coverage]
        Root --> M2[Module 2: SOAP Generation<br/>34 Tests | 71% Coverage]
        Root --> TTS[TTS Module<br/>19 Tests | 68% Coverage]
        Root --> STT[STT Module<br/>14 Tests | 79% Coverage]
        Root --> DIA[LLM Diarizer<br/>12 Tests | 83% Coverage]
        Root --> INT[Integration Tests<br/>9 Tests | 67% Coverage]
        Root --> PERF[Performance Tests<br/>12 Tests | 25% Coverage]
        Root --> SEC[Security Tests<br/>9 Tests | 11% Coverage]
        
        M1 --> M1REG[Patient Registration<br/>5 Tests]
        M1 --> M1SCH[Booking Scheduler<br/>5 Tests]
        M1 --> M1UI[Dashboard & UI<br/>5 Tests]
        
        M2 --> M2AUD[Audio Recording<br/>5 Tests]
        M2 --> M2STT[Speech-to-Text<br/>7 Tests]
        M2 --> M2DIA[Speaker Diarization<br/>7 Tests]
        M2 --> M2TRA[Translation<br/>5 Tests]
        M2 --> M2SOAP[SOAP Generation<br/>8 Tests]
        
        TTS --> TTSINIT[Engine Init<br/>5 Tests]
        TTS --> TTSSYNTH[Synthesis<br/>7 Tests]
        TTS --> TTSERR[Error Handling<br/>5 Tests]
        TTS --> TTSPLAY[Playback<br/>5 Tests]
        
        STT --> STTPRE[Preprocessing<br/>5 Tests]
        STT --> STTENG[Transcription<br/>5 Tests]
        STT --> STTQUA[Quality Eval<br/>4 Tests]
        
        DIA --> DIALOG[Diarization Logic<br/>5 Tests]
        DIA --> DIAEDGE[Edge Cases<br/>5 Tests]
        DIA --> DIAPRO[Provider Selection<br/>4 Tests]
        
        INT --> INTE2E[End-to-End<br/>3 Tests]
        INT --> INTCOM[Component Integration<br/>4 Tests]
        INT --> INTAPI[API Integration<br/>3 Tests]
        
        PERF --> PERFRT[Response Time<br/>5 Tests]
        PERF --> PERFRES[Resource Usage<br/>4 Tests]
        PERF --> PERFSCA[Scalability<br/>3 Tests]
        
        SEC --> SECAUTH[Authentication<br/>3 Tests]
        SEC --> SECDATA[Data Protection<br/>3 Tests]
        SEC --> SECVAL[Input Validation<br/>3 Tests]
    end
    
    style Root fill:#e1f5ff,stroke:#01579b,stroke-width:3px
    style M1 fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style M2 fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style TTS fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px
    style STT fill:#e0f2f1,stroke:#00695c,stroke-width:2px
    style DIA fill:#fce4ec,stroke:#c2185b,stroke-width:2px
    style INT fill:#fff9c4,stroke:#f57f17,stroke-width:2px
    style PERF fill:#ffebee,stroke:#c62828,stroke-width:2px
    style SEC fill:#efebe9,stroke:#4e342e,stroke-width:2px
```

---

## 📊 Test Coverage by Module

```mermaid
%%{init: {'theme':'base'}}%%
pie title Test Coverage Distribution
    "Module 1 (10%)" : 15
    "Module 2 (23%)" : 34
    "TTS Module (13%)" : 19
    "STT Module (10%)" : 14
    "LLM Diarizer (8%)" : 12
    "Integration (6%)" : 9
    "Performance (8%)" : 12
    "Security (6%)" : 9
```

---

## 📈 Test Status Overview

```mermaid
%%{init: {'theme':'base'}}%%
pie title Test Execution Status
    "Passed (60.5%)" : 89
    "In Progress (35.4%)" : 52
    "Failed/Not Implemented (4.1%)" : 6
```

---

## 🎯 Priority Distribution

```mermaid
%%{init: {'theme':'base'}}%%
pie title Test Priority Breakdown
    "HIGH Priority (49%)" : 72
    "MEDIUM Priority (43%)" : 63
    "LOW Priority (8%)" : 12
```

---

## 🔄 Module 2 SOAP Workflow Test Flow

```mermaid
sequenceDiagram
    participant User
    participant UI as Web UI
    participant Audio as Audio Recorder
    participant STT as STT Engine
    participant Dia as LLM Diarizer
    participant Trans as Translator
    participant SOAP as SOAP Generator
    participant DB as Database
    
    User->>UI: Click "Start Recording"
    activate Audio
    Note over Audio: TEST: M2-AUD-01
    Audio-->>UI: Recording indicator shown
    
    User->>UI: Click "Stop Recording"
    Audio->>STT: Audio data (WAV)
    deactivate Audio
    Note over STT: TEST: M2-STT-01 to M2-STT-07
    
    STT->>STT: Normalize & Preprocess
    Note over STT: TEST: STT-PRE-01 to STT-PRE-05
    
    STT->>STT: Try Primary Cloud STT
    alt Primary Success
        STT->>STT: Evaluate Quality
        Note over STT: TEST: STT-QUA-01 to STT-QUA-05
    else Primary Fails
        STT->>STT: Fallback to Groq
        Note over STT: TEST: M2-STT-05
    end
    
    STT->>Dia: Urdu Transcript
    Note over Dia: TEST: M2-DIA-01 to M2-DIA-07
    
    Dia->>Dia: LLM Diarization
    Note over Dia: TEST: DIA-LOG-01 to DIA-EDGE-05
    
    Dia->>Trans: Doctor/Patient Turns
    Note over Trans: TEST: M2-TRA-01 to M2-TRA-05
    
    Trans->>SOAP: English Conversation
    Note over SOAP: TEST: M2-SOAP-01 to M2-SOAP-08
    
    SOAP->>SOAP: Generate SOAP Note
    SOAP->>DB: Save JSON File
    SOAP-->>UI: Display SOAP Note
    UI-->>User: Show completed note
    
    Note over User,DB: TEST: INT-E2E-01 (Full Flow)
```

---

## 🧪 TTS Module Test Flow

```mermaid
flowchart TD
    Start([TTS Module Start]) --> Init{Initialize TTS Engine}
    
    Init --> |API Key Valid| CloudInit[Cloud TTS Init]
    Init --> |No API Key| EdgeInit[Edge TTS Fallback]
    Init --> |Invalid Key| EdgeInit
    
    CloudInit --> SelectVoice[Select Female Voice]
    SelectVoice --> Ready1[✅ Engine Ready]
    EdgeInit --> Ready2[✅ Engine Ready - Edge]
    
    Ready1 --> Speak{Speak Text}
    Ready2 --> Speak
    
    Speak --> |Empty Text| SkipA[Skip - No Action]
    Speak --> |Valid Text| Synth[Synthesize Audio]
    
    Synth --> |Cloud Backend| CloudSynth[Cloud TTS API Call]
    Synth --> |Edge Backend| EdgeSynth[Edge TTS Async]
    
    CloudSynth --> |Success| GenMP3A[Generate MP3 Bytes]
    CloudSynth --> |Failure| FallbackEdge[Fallback to Edge]
    FallbackEdge --> EdgeSynth
    
    EdgeSynth --> GenMP3B[Generate MP3 File]
    
    GenMP3A --> TempFile[Create Temp File]
    GenMP3B --> TempFile
    
    TempFile --> LoadPygame[Load in Pygame Mixer]
    LoadPygame --> Play[Play Audio]
    Play --> Wait[Wait for Completion]
    
    Wait --> Cleanup[Cleanup Temp Files]
    Cleanup --> End([TTS Complete])
    
    SkipA --> End
    
    style Start fill:#4caf50,color:#fff
    style End fill:#2196f3,color:#fff
    style CloudInit fill:#9c27b0,color:#fff
    style EdgeInit fill:#ff9800,color:#fff
    style Play fill:#00bcd4,color:#fff
    style Cleanup fill:#8bc34a,color:#fff
```

---

## 🎤 STT Module Test Flow

```mermaid
flowchart TD
    Start([Audio Input]) --> Normalize[Normalize Audio]
    
    Normalize --> Resample[Resample to 16kHz]
    Resample --> ToWAV[Convert to WAV Bytes]
    
    ToWAV --> Primary{Primary STT<br/>Available?}
    
    Primary --> |Yes| CloudSTT[Cloud Scribe v1]
    Primary --> |No| GroqSTT[Groq Whisper]
    
    CloudSTT --> EvalCloud{Evaluate Quality}
    EvalCloud --> |Good Quality| ReturnCloud[✅ Return Transcript]
    EvalCloud --> |Suspicious| TryGroq1[Warn & Try Groq]
    
    TryGroq1 --> GroqSTT
    
    GroqSTT --> BiasHint[Groq with Urdu Bias]
    BiasHint --> EvalBias{Quality Check}
    
    EvalBias --> |Good| ReturnBias[✅ Return Transcript]
    EvalBias --> |Suspicious| TryPlain[Try Without Bias]
    
    TryPlain --> GroqPlain[Groq Plain]
    GroqPlain --> EvalPlain{Quality Check}
    
    EvalPlain --> |Best Available| WarnReturn[⚠️ Return Best with Warning]
    EvalPlain --> |All Failed| EmptyReturn[Return Empty]
    
    ReturnCloud --> End([STT Complete])
    ReturnBias --> End
    WarnReturn --> End
    EmptyReturn --> End
    
    style Start fill:#4caf50,color:#fff
    style End fill:#2196f3,color:#fff
    style CloudSTT fill:#9c27b0,color:#fff
    style GroqSTT fill:#ff9800,color:#fff
    style ReturnCloud fill:#00c853,color:#fff
    style WarnReturn fill:#ff6f00,color:#fff
    style EmptyReturn fill:#d32f2f,color:#fff
```

---

## 🧠 Diarization Test Flow

```mermaid
flowchart TD
    Start([Raw Transcript]) --> Provider{Select Provider}
    
    Provider --> |OpenAI Key| GPT[GPT-4.1 Diarizer]
    Provider --> |Groq Key| Llama[LLaMA 3.3-70B]
    Provider --> |Auto| Best[Best Available]
    
    GPT --> Prompt[Apply Diarization Prompt]
    Llama --> Prompt
    Best --> Prompt
    
    Prompt --> LLM[LLM Processing]
    
    LLM --> Parse{Parse JSON Response}
    
    Parse --> |Valid| Extract[Extract Turns]
    Parse --> |Invalid| Retry[Retry Once]
    
    Retry --> |Success| Extract
    Retry --> |Failed| Error[❌ Diarization Failed]
    
    Extract --> Validate[Validate Turns]
    
    Validate --> Check1{Check: Exact Wording<br/>Preserved?}
    Check1 --> |Yes| Check2{Check: Speakers<br/>Doctor/Patient Only?}
    Check1 --> |No| Error2[❌ Text Modified]
    
    Check2 --> |Yes| Check3{Check: Contiguous<br/>Turns?}
    Check2 --> |No| Error3[❌ Invalid Speaker]
    
    Check3 --> |Yes| Success[✅ Valid Diarization]
    Check3 --> |Warning| WarnSuccess[⚠️ Too Many Switches]
    
    Success --> End([Return Turns])
    WarnSuccess --> End
    Error --> End
    Error2 --> End
    Error3 --> End
    
    style Start fill:#4caf50,color:#fff
    style End fill:#2196f3,color:#fff
    style GPT fill:#10a37f,color:#fff
    style Llama fill:#ff6b6b,color:#fff
    style Success fill:#00c853,color:#fff
    style Error fill:#d32f2f,color:#fff
```

---

## 📋 Integration Test Coverage Map

```mermaid
graph LR
    subgraph "Module 1: Reception"
        A1[Patient Registration] --> A2[Booking Scheduler]
        A2 --> A3[Dashboard UI]
    end
    
    subgraph "Module 2: SOAP"
        B1[Audio Recording] --> B2[STT Engine]
        B2 --> B3[LLM Diarizer]
        B3 --> B4[Translator]
        B4 --> B5[SOAP Generator]
    end
    
    subgraph "Cross-Module"
        C1[Patient Data Transfer]
        C2[WebSocket Communication]
        C3[File Storage]
    end
    
    A3 -.->|Patient ID| C1
    C1 -.->|Context| B1
    
    B5 --> C3
    A2 --> C3
    
    A3 <--> C2
    B5 <--> C2
    
    style A1 fill:#ffecb3,stroke:#f57f17
    style A2 fill:#ffecb3,stroke:#f57f17
    style A3 fill:#ffecb3,stroke:#f57f17
    style B1 fill:#c8e6c9,stroke:#388e3c
    style B2 fill:#c8e6c9,stroke:#388e3c
    style B3 fill:#c8e6c9,stroke:#388e3c
    style B4 fill:#c8e6c9,stroke:#388e3c
    style B5 fill:#c8e6c9,stroke:#388e3c
    style C1 fill:#e1bee7,stroke:#7b1fa2
    style C2 fill:#e1bee7,stroke:#7b1fa2
    style C3 fill:#e1bee7,stroke:#7b1fa2
```

---

## 📊 Module Performance Benchmarks

```mermaid
gantt
    title Module 2 SOAP Generation Timeline (Target vs Actual)
    dateFormat ss
    axisFormat %S s
    
    section Audio Capture
    Recording (60s)           :done, a1, 00, 60s
    
    section STT Processing
    Audio Preprocessing       :done, b1, 60, 2s
    Cloud STT (Target)        :crit, b2, 62, 8s
    Cloud STT (Actual)        :done, b2a, 62, 7s
    Quality Evaluation        :done, b3, 69, 1s
    
    section Diarization
    LLM Diarization (Target)  :crit, c1, 70, 5s
    LLM Diarization (Actual)  :done, c1a, 70, 3s
    
    section Translation
    Translation (Target)      :crit, d1, 75, 3s
    Translation (Actual)      :done, d1a, 75, 2s
    
    section SOAP Generation
    SOAP Note Gen (Target)    :crit, e1, 77, 15s
    SOAP Note Gen (Actual)    :done, e1a, 77, 12s
    File Save                 :done, e2, 89, 1s
    
    section Total Time
    Target Total              :milestone, 92, 0s
    Actual Total              :milestone, 90, 0s
```

---

## 🏆 Test Maturity Model

```mermaid
flowchart LR
    Level1[Level 1<br/>Basic Unit Tests<br/>✅ 60% Complete] --> Level2[Level 2<br/>Integration Tests<br/>🔄 35% Complete]
    
    Level2 --> Level3[Level 3<br/>System Tests<br/>🔄 40% Complete]
    
    Level3 --> Level4[Level 4<br/>Performance Tests<br/>⚠️ 25% Complete]
    
    Level4 --> Level5[Level 5<br/>Security & Load Tests<br/>❌ 11% Complete]
    
    Level5 --> Target[Target<br/>Full Coverage<br/>🎯 Goal: 90%+]
    
    style Level1 fill:#4caf50,color:#fff
    style Level2 fill:#8bc34a,color:#fff
    style Level3 fill:#ffc107,color:#000
    style Level4 fill:#ff9800,color:#fff
    style Level5 fill:#f44336,color:#fff
    style Target fill:#2196f3,color:#fff
```

---

## 🎯 Test Execution Roadmap

```mermaid
gantt
    title Test Execution Plan (6 Weeks)
    dateFormat YYYY-MM-DD
    
    section Phase 1: Core
    TTS Module Tests          :done, p1a, 2026-05-01, 4d
    STT Module Tests          :done, p1b, 2026-05-01, 4d
    Diarizer Tests            :done, p1c, 2026-05-05, 3d
    SOAP Generator Tests      :done, p1d, 2026-05-05, 3d
    Module 1 Basic Tests      :done, p1e, 2026-05-08, 3d
    
    section Phase 2: Integration
    STT→Diarizer→Translator   :active, p2a, 2026-05-15, 5d
    Translator→SOAP           :active, p2b, 2026-05-15, 5d
    Module 1↔Module 2         :p2c, 2026-05-20, 5d
    Edge Cases                :p2d, 2026-05-22, 4d
    
    section Phase 3: Performance
    Response Time Tests       :p3a, 2026-05-29, 3d
    Resource Usage Tests      :p3b, 2026-05-29, 3d
    Scalability Tests         :p3c, 2026-06-01, 4d
    
    section Phase 4: Security
    Authentication Tests      :p4a, 2026-06-05, 3d
    Data Protection Tests     :p4b, 2026-06-05, 3d
    Input Validation Tests    :p4c, 2026-06-08, 2d
    
    section Phase 5: Final
    Regression Testing        :p5a, 2026-06-10, 3d
    User Acceptance Testing   :p5b, 2026-06-13, 2d
    Bug Fixes                 :p5c, 2026-06-15, 5d
    
    Final Delivery            :milestone, 2026-06-20, 0d
```

---

## 📈 Code Coverage Goals

```mermaid
graph TD
    subgraph "Coverage Targets"
        Total[Overall Target: 85%]
        
        Total --> Critical[Critical Paths: 95%]
        Total --> Core[Core Modules: 85%]
        Total --> Support[Support Functions: 75%]
        Total --> Edge[Edge Cases: 60%]
    end
    
    subgraph "Current Status"
        CurrTotal[Current: 68%]
        
        CurrTotal --> CurrCrit[Critical: 89%]
        CurrTotal --> CurrCore[Core: 73%]
        CurrTotal --> CurrSupp[Support: 58%]
        CurrTotal --> CurrEdge[Edge: 42%]
    end
    
    Critical -.->|Gap: 6%| CurrCrit
    Core -.->|Gap: 12%| CurrCore
    Support -.->|Gap: 17%| CurrSupp
    Edge -.->|Gap: 18%| CurrEdge
    
    style Total fill:#2196f3,color:#fff
    style CurrTotal fill:#ff9800,color:#fff
    style Critical fill:#4caf50,color:#fff
    style CurrCrit fill:#8bc34a,color:#fff
    style Core fill:#4caf50,color:#fff
    style CurrCore fill:#ffc107,color:#000
    style Support fill:#4caf50,color:#fff
    style CurrSupp fill:#ff9800,color:#fff
    style Edge fill:#4caf50,color:#fff
    style CurrEdge fill:#f44336,color:#fff
```

---

*Generated: May 14, 2026*
*Version: 1.0*
