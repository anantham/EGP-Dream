import { useState, useEffect, useRef, useCallback } from 'react';
import { Mic, Pause, Settings as SettingsIcon, X, List, Activity, Clock, Download, FolderOpen, DollarSign, ChevronLeft, ChevronRight } from 'lucide-react';

const SAMPLE_RATE = 16000;

const AUDIO_MODELS = [
  { id: "local_whisper", name: "Local Whisper (TheWhisper) - Streaming (low latency)" },
  { id: "gemini_flash_audio", name: "Gemini 2.5 Flash (Native) - Batched ~4-6s (overlap)" },
  { id: "openai_realtime_4o", name: "GPT-4o Realtime (WebSocket) - Streaming (lowest latency)" },
  { id: "openai_realtime_mini", name: "GPT-4o Mini Realtime (WebSocket) - Streaming (low latency, cheaper)" },
  { id: "openai_rest_whisper", name: "Whisper V1 (REST) - Batched ~4-6s (slower)" }
];

const QUESTION_MODELS = [
    { id: "gemini-2.5-flash", name: "Gemini 2.5 Flash (Native)" },
    { id: "google/gemini-2.5-flash-lite-preview-09-2025", name: "Gemini 2.5 Flash Lite Preview (OpenRouter)" },
    { id: "google/gemini-2.5-flash-lite", name: "Gemini 2.5 Flash Lite (OpenRouter)" },
    { id: "google/gemini-2.5-flash", name: "Gemini 2.5 Flash (OpenRouter)" },
    { id: "openai/gpt-4o-mini", name: "GPT-4o Mini (OpenRouter)" },
    { id: "meta-llama/llama-3.2-3b-instruct", name: "Llama 3.2 3B (OpenRouter)" }
];

const IMAGE_MODELS = [
  { id: "google/gemini-2.5-flash-image", name: "Gemini 2.5 Flash Image" },
  { id: "google/gemini-2.5-flash-image-preview", name: "Gemini 2.5 Flash Image Preview" },
  { id: "google/gemini-3-pro-image-preview", name: "Gemini 3 Pro Image (NanoPro)" },
  { id: "openai/gpt-5-image-mini", name: "GPT-5 Image Mini (OpenRouter)" },
  { id: "stabilityai/stable-diffusion-3-medium", name: "SD3 Medium (OpenRouter)" }
];

interface HistoryItem {
  question: string;
  url: string;
  timestamp: string;
}

export default function App() {
  const [isRecording, setIsRecording] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showQuestions, setShowQuestions] = useState(false);
  const [showDebug, setShowDebug] = useState(false);
  const [micStatus, setMicStatus] = useState<'unknown' | 'granted' | 'denied'>('unknown');
  const [wsStatus, setWsStatus] = useState<'connecting' | 'open' | 'closed'>('connecting');
  const [imageStatus, setImageStatus] = useState<'idle' | 'generating'>('idle');
  
  // Config
  const [geminiKey, setGeminiKey] = useState(localStorage.getItem('gemini_api_key') || '');
  const [openRouterKey, setOpenRouterKey] = useState(localStorage.getItem('openrouter_api_key') || '');
  const [openaiKey, setOpenaiKey] = useState(localStorage.getItem('openai_api_key') || '');
  const [audioModel, setAudioModel] = useState('local_whisper');
  const [questionModel, setQuestionModel] = useState('gemini-2.5-flash');
  const [imageModel, setImageModel] = useState('google/gemini-2.5-flash-image');
  const [minDisplayTime, setMinDisplayTime] = useState(6);
  const [sessionName, setSessionName] = useState(`Session_${new Date().toLocaleDateString().replace(/\//g, '-')}`);

  // App State
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [viewIndex, setViewIndex] = useState<number>(-1); // -1 means "Live/Latest"
  
  const [liveImage, setLiveImage] = useState<string | null>(null);
  const [livePrompt, setLivePrompt] = useState<string>('');
  
  const [status, setStatus] = useState<string>('');
  const [metrics, setMetrics] = useState<Record<string, any>>({});
  const [cost, setCost] = useState<Record<string, any>>({ total: 0, breakdown: {} });
  const [debugText, setDebugText] = useState<string[]>([]);
  
  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);

  // Current Display Logic
  const isLive = viewIndex === -1 || viewIndex >= history.length;
  const displayImage = isLive ? liveImage : history[viewIndex]?.url;
  const displayPrompt = isLive ? livePrompt : history[viewIndex]?.question;

  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/ws');
    ws.onopen = () => {
      setWsStatus('open');
      setStatus('Connected');
      sendConfig(ws);
      setInterval(() => { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'get_metrics' })); }, 5000);
    };
    ws.onerror = () => setWsStatus('closed');
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'image') {
        setLiveImage(data.url);
        setLivePrompt(data.prompt);
        setImageStatus('idle');
      } 
      else if (data.type === 'history_update') {
        setHistory(prev => [...prev, data.item]);
      }
      else if (data.type === 'status') setStatus(data.message);
      else if (data.type === 'debug_text') {
        setDebugText(prev => [...prev.slice(-10), data.text || '']);
      }
      else if (data.type === 'metrics') {
        setMetrics(data.data.latency || {});
        setCost(data.data.cost || { total: 0, breakdown: {} });
      }
    };
    ws.onclose = () => { setStatus('Disconnected'); setWsStatus('closed'); };
    wsRef.current = ws;
    return () => ws.close();
  }, []);

  // Keyboard Navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (history.length === 0) return;
      
      if (e.key === 'ArrowLeft') {
        setViewIndex(prev => {
          if (prev === -1) return history.length - 1; // Start from end
          return Math.max(0, prev - 1);
        });
      } else if (e.key === 'ArrowRight') {
        setViewIndex(prev => {
          if (prev === -1) return -1; // Already live
          if (prev >= history.length - 1) return -1; // Go back to live
          return prev + 1;
        });
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [history.length]);

  const sendConfig = (wsInstance: WebSocket | null = wsRef.current) => {
    if (wsInstance && wsInstance.readyState === WebSocket.OPEN) {
      wsInstance.send(JSON.stringify({
        type: 'config',
        geminiApiKey: geminiKey,
        openRouterApiKey: openRouterKey,
        openaiApiKey: openaiKey,
        debug: showDebug,
        audioModel, questionModel, imageModel, minDisplayTime, sessionName
      }));
    }
  };

  // Metrics-aware labeling
  const formatLatencyLabel = (seconds: any) => {
    if (seconds === undefined || seconds === null) return '';
    const ms = Math.round(Number(seconds) * 1000);
    return `• ${ms} ms avg`;
  };

  const audioMetricMap: Record<string, string> = {
    local_whisper: "Phase A:local_whisper",
    gemini_flash_audio: "Phase A+B:gemini_native",
    openai_rest_whisper: "Phase A:openai_whisper_rest",
    openai_realtime_4o: "Phase A:openai_realtime",
    openai_realtime_mini: "Phase A:openai_realtime",
  };

  const decorateAudioName = (id: string, name: string) => {
    const key = audioMetricMap[id];
    return key ? `${name} ${formatLatencyLabel(metrics[key])}` : name;
  };

const decorateQuestionName = (id: string, name: string) => {
  const key = `Phase B:${id}`;
  return `${name} ${formatLatencyLabel(metrics[key])}`.trim();
};

const decorateImageName = (id: string, name: string) => {
  const key = `Phase C:${id}`;
  return `${name} ${formatLatencyLabel(metrics[key])}`.trim();
};

const statusDot = (state: 'ok' | 'warn' | 'err') => {
  const color = state === 'ok' ? 'bg-green-400' : state === 'warn' ? 'bg-yellow-400' : 'bg-red-500';
  return <span className={`inline-block w-2.5 h-2.5 rounded-full ${color}`} />;
};

  const handleSaveSettings = () => {
    localStorage.setItem('gemini_api_key', geminiKey);
    localStorage.setItem('openrouter_api_key', openRouterKey);
    localStorage.setItem('openai_api_key', openaiKey);
    sendConfig();
    setShowSettings(false);
  };

const handleExport = () => window.open('http://localhost:8000/api/export', '_blank');

const startRecording = async () => {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    setMicStatus('granted');
    streamRef.current = stream;
    const audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });
    audioContextRef.current = audioContext;
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;
      processor.onaudioprocess = (e) => {
        if (!isRecording) return;
        const bytes = new Uint8Array(e.inputBuffer.getChannelData(0).buffer);
        let binary = '';
        for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'audio', data: window.btoa(binary) }));
        }
      };
    source.connect(processor);
    processor.connect(audioContext.destination);
    setIsRecording(true);
    setStatus('Listening...');
  } catch (err) { console.error(err); setStatus('Mic Error'); setMicStatus('denied'); }
};

  const stopRecording = () => {
    if (processorRef.current) { processorRef.current.disconnect(); processorRef.current = null; }
    if (audioContextRef.current) { audioContextRef.current.close(); audioContextRef.current = null; }
    if (streamRef.current) { streamRef.current.getTracks().forEach(track => track.stop()); streamRef.current = null; }
    setIsRecording(false);
    setStatus('Paused');
  };

  const toggleRecording = () => isRecording ? stopRecording() : startRecording();

  return (
    <div className="relative w-full h-screen bg-black overflow-hidden text-white font-light select-none">
      {/* Main Visual */}
      {displayImage ? (
        <div className="absolute inset-0 animate-fade-in">
           <img src={displayImage} alt="Art" className="w-full h-full object-cover" />
           
           {/* Enhanced Question Overlay */}
           <div className="absolute bottom-0 left-0 w-full bg-gradient-to-t from-black/90 via-black/50 to-transparent p-12 pb-32 flex flex-col items-center text-center">
              <p className="text-2xl md:text-4xl font-light leading-relaxed max-w-4xl drop-shadow-lg font-serif tracking-wide">
                "{displayPrompt}"
              </p>
              {!isLive && (
                <div className="mt-4 text-xs uppercase tracking-[0.2em] text-white/50 bg-white/10 px-3 py-1 rounded-full">
                  History Mode ({viewIndex + 1} / {history.length})
                </div>
              )}
           </div>
        </div>
      ) : (
        <div className="w-full h-full flex items-center justify-center text-white/20">
           <p className="text-2xl font-light tracking-widest">WAITING FOR INSPIRATION</p>
        </div>
      )}

      {/* Navigation Hints (Left/Right hover areas) */}
      <div className="absolute inset-y-0 left-0 w-24 hover:bg-white/5 transition-colors flex items-center justify-center group opacity-0 hover:opacity-100 cursor-pointer" onClick={() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))}>
         <ChevronLeft size={48} className="text-white/50 group-hover:text-white" />
      </div>
      <div className="absolute inset-y-0 right-0 w-24 hover:bg-white/5 transition-colors flex items-center justify-center group opacity-0 hover:opacity-100 cursor-pointer" onClick={() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))}>
         <ChevronRight size={48} className="text-white/50 group-hover:text-white" />
      </div>

      <div className="absolute top-8 left-0 w-full text-center pointer-events-none z-10">
        <p className="text-white/50 text-sm font-mono tracking-wider uppercase">{status}</p>
      </div>

      <div className="absolute bottom-8 left-8 z-50">
        <button onClick={toggleRecording} className={`p-4 rounded-full backdrop-blur-md border border-white/10 transition-all ${isRecording ? 'bg-red-500/20 text-red-200' : 'bg-white/10'} hover:opacity-100 opacity-40 hover:scale-105`}>
          {isRecording ? <Pause size={32} /> : <Mic size={32} />}
        </button>
      </div>

      <div className="absolute bottom-8 right-8 z-50 flex gap-4">
        <button onClick={() => setShowQuestions(!showQuestions)} className="p-4 rounded-full bg-white/10 backdrop-blur-md border border-white/10 hover:opacity-100 opacity-40 hover:scale-105"><List size={32} /></button>
        <button onClick={() => setShowSettings(true)} className="p-4 rounded-full bg-white/10 backdrop-blur-md border border-white/10 hover:opacity-100 opacity-40 hover:scale-105"><SettingsIcon size={32} /></button>
      </div>

      {/* Questions History Sidebar */}
      {showQuestions && (
        <div className="absolute top-20 right-8 w-80 max-h-[60vh] bg-black/80 backdrop-blur-md border border-white/10 rounded-xl p-4 overflow-y-auto z-40">
           <h3 className="text-lg mb-4 border-b border-white/10 pb-2 font-serif italic">Question Log</h3>
           <ul className="space-y-4">
             {history.map((item, i) => (
               <li key={i} className={`text-sm border-l-2 pl-3 py-1 cursor-pointer transition-colors ${viewIndex === i ? 'border-purple-500 text-white' : 'border-transparent text-white/60 hover:text-white hover:border-white/30'}`} onClick={() => setViewIndex(i)}>
                 "{item.question}"
               </li>
             ))}
             {history.length === 0 && <li className="text-white/30">No questions yet.</li>}
           </ul>
        </div>
      )}

      {showDebug && (
        <div className="absolute top-20 left-8 w-96 max-h-[50vh] bg-black/80 backdrop-blur-md border border-purple-500/30 rounded-xl p-4 overflow-y-auto z-40">
          <h3 className="text-sm mb-2 border-b border-white/10 pb-1 font-mono text-purple-300 flex items-center gap-2"><Activity size={14}/> Debug Transcript</h3>
          {debugText.length === 0 && <p className="text-xs text-white/40">No debug text received. Backend must emit 'debug_text' messages to populate this.</p>}
          <ul className="space-y-2 text-xs">
            {debugText.map((t, i) => (
              <li key={i} className="bg-white/5 border border-white/10 rounded p-2 text-white/80">{t}</li>
            ))}
          </ul>
        </div>
      )}

      {showSettings && (
        <div className="fixed inset-0 bg-black/90 backdrop-blur-md flex items-center justify-center z-50 p-4">
          <div className="bg-neutral-900 border border-white/10 rounded-2xl w-full max-w-3xl shadow-2xl flex flex-col max-h-[90vh]">
            <div className="flex justify-between items-center p-6 border-b border-white/10">
              <h2 className="text-xl tracking-wide">CONFIGURATION</h2>
              <button onClick={() => setShowSettings(false)}><X size={24} /></button>
            </div>
            
            <div className="p-6 overflow-y-auto space-y-8">
              <div className="flex items-center justify-between bg-white/5 p-4 rounded-lg">
                  <div>
                      <h3 className="text-sm font-bold text-white/70 mb-1 flex items-center gap-2"><FolderOpen size={16}/> SESSION MANAGEMENT</h3>
                      <p className="text-xs text-white/40">Images are saved to: {sessionName}</p>
                  </div>
                  <button onClick={handleExport} className="flex items-center gap-2 bg-green-600/20 hover:bg-green-600/40 text-green-200 px-4 py-2 rounded-lg transition-all text-sm"><Download size={16}/> EXPORT ZIP</button>
              </div>
              
              <div className="bg-white/5 p-4 rounded-lg">
                 <div className="flex justify-between mb-4">
                    <h3 className="flex items-center gap-2 text-sm font-bold text-purple-400"><Activity size={16}/> METRICS</h3>
                    <h3 className="flex items-center gap-2 text-sm font-bold text-green-400"><DollarSign size={16}/> ESTIMATED COST: ${cost.total?.toFixed(4)}</h3>
                 </div>
                 <div className="grid grid-cols-2 gap-6 text-xs font-mono">
                    <div>
                        <p className="text-white/50 border-b border-white/10 mb-2 pb-1">LATENCY (AVG)</p>
                        {Object.entries(metrics).map(([k, v]) => (
                            <div key={k} className="flex justify-between py-1"><span>{k}</span><span className="text-purple-300">{Number(v).toFixed(3)}s</span></div>
                        ))}
                    </div>
                    <div>
                        <p className="text-white/50 border-b border-white/10 mb-2 pb-1">COST BREAKDOWN</p>
                        {Object.entries(cost.breakdown || {}).map(([k, v]) => (
                            <div key={k} className="flex justify-between py-1"><span>{k}</span><span className="text-green-300">${Number(v).toFixed(4)}</span></div>
                        ))}
                    </div>
                 </div>
              </div>

              <div className="flex items-center justify-between bg-white/5 p-4 rounded-lg">
                <div>
                  <h3 className="text-sm font-bold text-white/70">DEBUG TRANSCRIPTS</h3>
                  <p className="text-xs text-white/40">When enabled, backend can emit raw transcript snippets to the Debug panel.</p>
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={showDebug} onChange={e => setShowDebug(e.target.checked)} />
                  <span className="text-white/80">Enable</span>
                </label>
              </div>

              <div className="space-y-4">
                <h3 className="text-sm font-bold text-white/70">API KEYS</h3>
                <input type="password" value={geminiKey} onChange={e => setGeminiKey(e.target.value)} placeholder="Gemini API Key" className="w-full bg-black/50 border border-white/10 rounded p-3" />
                <input type="password" value={openRouterKey} onChange={e => setOpenRouterKey(e.target.value)} placeholder="OpenRouter API Key" className="w-full bg-black/50 border border-white/10 rounded p-3" />
                <input type="password" value={openaiKey} onChange={e => setOpenaiKey(e.target.value)} placeholder="OpenAI API Key" className="w-full bg-black/50 border border-white/10 rounded p-3" />
              </div>

              <div className="grid grid-cols-1 gap-6">
                  <div className="space-y-2">
                    <h3 className="text-sm font-bold text-white/70">PHASE A: AUDIO PIPELINE</h3>
                    <select value={audioModel} onChange={e => setAudioModel(e.target.value)} className="w-full bg-black/50 border border-white/10 rounded p-3 text-sm">
                      {AUDIO_MODELS.map(m => <option key={m.id} value={m.id}>{decorateAudioName(m.id, m.name)}</option>)}
                    </select>
                  </div>
                  <div className="space-y-2">
                    <h3 className="text-sm font-bold text-white/70">PHASE B: QUESTION MODEL</h3>
                    <select value={questionModel} onChange={e => setQuestionModel(e.target.value)} className="w-full bg-black/50 border border-white/10 rounded p-3 text-sm">
                      {QUESTION_MODELS.map(m => <option key={m.id} value={m.id}>{decorateQuestionName(m.id, m.name)}</option>)}
                    </select>
                  </div>
                  <div className="space-y-2">
                    <h3 className="text-sm font-bold text-white/70">PHASE C: IMAGE GENERATOR</h3>
                    <select value={imageModel} onChange={e => setImageModel(e.target.value)} className="w-full bg-black/50 border border-white/10 rounded p-3 text-sm">
                      {IMAGE_MODELS.map(m => <option key={m.id} value={m.id}>{decorateImageName(m.id, m.name)}</option>)}
                    </select>
                  </div>
              </div>
              
              <div className="space-y-2">
                 <h3 className="text-sm font-bold text-white/70 flex items-center gap-2"><Clock size={16}/> MIN DISPLAY TIME: {minDisplayTime}s</h3>
                 <input type="range" min="3" max="60" value={minDisplayTime} onChange={e => setMinDisplayTime(Number(e.target.value))} className="w-full accent-purple-500" />
              </div>
            </div>
            
            <div className="p-6 border-t border-white/10">
              <button onClick={handleSaveSettings} className="w-full bg-purple-600/20 hover:bg-purple-600/40 text-purple-200 p-4 rounded-lg font-medium transition-all">APPLY SETTINGS</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
