import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  BookOpen, Sparkles, SlidersHorizontal, ArrowRight,
  ShieldAlert, Cpu, Search, CheckCircle2, Check,
} from 'lucide-react';
import type { LoreStatus, RequestInputData } from '../hooks/useStory';

interface SetupWizardProps {
  pendingInput: RequestInputData | null;
  submitInput: (text: string) => void;
  isConnected: boolean;
  isResearching: boolean;
  loreUpdates: LoreStatus[];
}

// ─── Step Indicator ───────────────────────────────────────────────────────────
function StepIndicator({ current }: { current: 1 | 2 | 3 }) {
  const steps = ['Premise', 'Research', 'Review'] as const;
  return (
    <div className="flex items-center justify-center gap-2 py-4 px-6 border-b border-slate-800">
      {steps.map((label, idx) => {
        const step = idx + 1;
        const done = step < current;
        const active = step === current;
        return (
          <div key={label} className="flex items-center gap-2">
            <div className="flex flex-col items-center gap-1">
              <div
                className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-all ${
                  done
                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                    : active
                    ? 'bg-indigo-500/30 text-indigo-300 border border-indigo-500 ring-2 ring-indigo-500/20'
                    : 'bg-slate-800 text-slate-600 border border-slate-700'
                }`}
              >
                {done ? <Check className="w-3.5 h-3.5" /> : step}
              </div>
              <span
                className={`text-[10px] tracking-wide ${
                  active ? 'text-indigo-400' : done ? 'text-emerald-500/70' : 'text-slate-700'
                }`}
              >
                {label}
              </span>
            </div>
            {step < 3 && (
              <div
                className={`w-12 h-px mb-4 transition-colors ${
                  done ? 'bg-emerald-500/40' : 'bg-slate-800'
                }`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Live Research Feed ───────────────────────────────────────────────────────
function ResearchFeed({ updates }: { updates: LoreStatus[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [updates.length]);

  if (updates.length === 0) {
    return (
      <p className="text-xs text-slate-600 text-center py-4 animate-pulse">
        Awaiting swarm signal...
      </p>
    );
  }

  return (
    <div className="max-h-44 overflow-y-auto space-y-1 pr-1">
      <AnimatePresence initial={false}>
        {updates.slice(0, 40).map(u => (
          <motion.div
            key={u.id}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            className="flex items-start gap-2 text-xs py-1"
          >
            <span className="text-slate-700 shrink-0 tabular-nums">{u.timestamp}</span>
            <span className="text-emerald-400/80">{u.message}</span>
          </motion.div>
        ))}
      </AnimatePresence>
      <div ref={bottomRef} />
    </div>
  );
}

export default function SetupWizard({
  pendingInput,
  submitInput,
  isConnected,
  isResearching,
  loreUpdates,
}: SetupWizardProps) {
  const [loreDump, setLoreDump] = useState('');
  const [powerLevel, setPowerLevel] = useState('city');
  const [storyTone, setStoryTone] = useState('balanced');
  const [isolatePowerset, setIsolatePowerset] = useState(true);

  const isLoreDump = pendingInput?.interrupt_id === 'setup_lore_dump';
  const isConfig = pendingInput?.interrupt_id === 'setup_configuration';
  const isPrimer = pendingInput?.interrupt_id === 'setup_world_primer';

  const currentStep: 1 | 2 | 3 = isPrimer ? 3 : isResearching ? 2 : 1;

  const handleSubmitLore = () => {
    if (!loreDump.trim()) return;
    submitInput(loreDump);
  };

  const handleSubmitConfig = () => {
    submitInput(JSON.stringify({
      power_level: powerLevel,
      story_tone: storyTone,
      isolate_powerset: isolatePowerset,
    }));
  };

  const handleApprovePrimer = () => submitInput('Approved.');

  // ─── Research Phase ─────────────────────────────────────────────────────────
  if (isResearching) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-950 p-6">
        <motion.div
          key="researching"
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden"
        >
          <StepIndicator current={2} />

          <div className="flex flex-col items-center gap-4 py-8 px-6">
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ repeat: Infinity, duration: 4, ease: 'linear' }}
              className="w-16 h-16 border-t-2 border-l-2 border-emerald-500 rounded-full flex items-center justify-center relative shrink-0"
            >
              <Search className="w-6 h-6 text-emerald-400 absolute" />
            </motion.div>
            <div className="text-center">
              <h2 className="text-xl font-serif text-slate-100">Swarm Deployed</h2>
              <p className="text-slate-500 text-sm mt-1">Hunting lore across wikis and source text...</p>
            </div>
          </div>

          <div className="px-6 pb-6">
            <div className="bg-slate-950 border border-slate-800 rounded-xl p-3">
              <p className="text-[10px] text-slate-600 uppercase tracking-widest mb-2">Live Feed</p>
              <ResearchFeed updates={loreUpdates} />
            </div>
          </div>
        </motion.div>
      </div>
    );
  }

  // ─── Connecting / initial state ─────────────────────────────────────────────
  if (!pendingInput) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-950">
        <motion.div
          animate={{ opacity: [0.4, 1, 0.4] }}
          transition={{ repeat: Infinity, duration: 2 }}
          className="flex flex-col items-center gap-4 text-slate-600"
        >
          <Cpu className="w-10 h-10" />
          <h2 className="text-base font-serif tracking-widest uppercase">Connecting to Weave</h2>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 p-6">
      <AnimatePresence mode="wait">

        {/* ── LORE DUMP ── */}
        {isLoreDump && (
          <motion.div
            key="lore_dump"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, x: -50 }}
            className="w-full max-w-3xl bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden"
          >
            <StepIndicator current={1} />
            <div className="bg-slate-950/50 p-6 border-b border-slate-800">
              <h1 className="text-3xl font-serif text-slate-100 flex items-center gap-3">
                <BookOpen className="w-8 h-8 text-indigo-400" />
                <span>Create Your Story</span>
              </h1>
              <p className="mt-2 text-slate-400">{pendingInput.message}</p>
            </div>
            <div className="p-6 space-y-6">
              <textarea
                value={loreDump}
                onChange={e => setLoreDump(e.target.value)}
                placeholder="E.g., I am a gravity user in the Mahouka universe. My core ability allows me to invert the gravitational pull of specific objects..."
                className="w-full h-44 md:h-64 bg-slate-950 border border-slate-700 rounded-xl p-4 text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 resize-none font-serif leading-relaxed"
              />
              <div className="flex justify-end">
                <button
                  onClick={handleSubmitLore}
                  disabled={!loreDump.trim() || !isConnected}
                  className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white px-6 py-3 rounded-lg font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <span>Start Setup</span>
                  <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          </motion.div>
        )}

        {/* ── CONFIGURATION ── */}
        {isConfig && (
          <motion.div
            key="config"
            initial={{ opacity: 0, x: 50 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="w-full max-w-2xl bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden"
          >
            <StepIndicator current={1} />
            <div className="bg-slate-950/50 p-6 border-b border-slate-800">
              <h1 className="text-3xl font-serif text-slate-100 flex items-center gap-3">
                <SlidersHorizontal className="w-8 h-8 text-emerald-400" />
                <span>Simulation Parameters</span>
              </h1>
              <p className="mt-2 text-slate-400">Tune the physics and tone of the narrative engine.</p>
            </div>
            <div className="p-6 space-y-8">
              <div className="space-y-3">
                <label className="text-sm font-semibold tracking-wider text-slate-300 uppercase">Power Level</label>
                <div className="grid grid-cols-3 gap-3">
                  {(['street', 'city', 'continental'] as const).map(lvl => (
                    <button
                      key={lvl}
                      onClick={() => setPowerLevel(lvl)}
                      className={`p-3 rounded-lg border text-sm font-medium capitalize transition-all ${
                        powerLevel === lvl
                          ? 'bg-indigo-500/20 border-indigo-500 text-indigo-300'
                          : 'bg-slate-950 border-slate-800 text-slate-500 hover:border-slate-600'
                      }`}
                    >
                      {lvl}
                    </button>
                  ))}
                </div>
              </div>
              <div className="space-y-3">
                <label className="text-sm font-semibold tracking-wider text-slate-300 uppercase">Narrative Tone</label>
                <div className="grid grid-cols-3 gap-3">
                  {(['dark', 'balanced', 'heroic'] as const).map(tone => (
                    <button
                      key={tone}
                      onClick={() => setStoryTone(tone)}
                      className={`p-3 rounded-lg border text-sm font-medium capitalize transition-all ${
                        storyTone === tone
                          ? 'bg-emerald-500/20 border-emerald-500 text-emerald-300'
                          : 'bg-slate-950 border-slate-800 text-slate-500 hover:border-slate-600'
                      }`}
                    >
                      {tone}
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex items-center justify-between p-4 bg-slate-950 border border-slate-800 rounded-xl">
                <div className="flex items-center gap-3">
                  <ShieldAlert className={`w-5 h-5 ${isolatePowerset ? 'text-rose-400' : 'text-slate-500'}`} />
                  <div>
                    <h3 className="text-slate-200 font-medium">Isolate Powerset</h3>
                    <p className="text-xs text-slate-500">Prevent native magic systems from interacting with your anomaly.</p>
                  </div>
                </div>
                <button
                  onClick={() => setIsolatePowerset(v => !v)}
                  className={`w-12 h-6 rounded-full transition-colors relative ${isolatePowerset ? 'bg-rose-500' : 'bg-slate-700'}`}
                >
                  <motion.div
                    layout
                    className="w-4 h-4 bg-white rounded-full absolute top-1 left-1"
                    animate={{ x: isolatePowerset ? 24 : 0 }}
                  />
                </button>
              </div>
              <div className="flex justify-end pt-4">
                <button
                  onClick={handleSubmitConfig}
                  disabled={!isConnected}
                  className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-500 text-white px-6 py-3 rounded-lg font-medium transition-all disabled:opacity-50"
                >
                  <Sparkles className="w-4 h-4" />
                  <span>Execute Research Swarm</span>
                </button>
              </div>
            </div>
          </motion.div>
        )}

        {/* ── WORLD PRIMER ── */}
        {isPrimer && (
          <motion.div
            key="primer"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95 }}
            className="w-full max-w-4xl max-h-[92vh] sm:max-h-[85vh] flex flex-col bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden"
          >
            <StepIndicator current={3} />
            <div className="bg-slate-950/50 p-6 border-b border-slate-800 shrink-0">
              <h1 className="text-3xl font-serif text-slate-100 flex items-center gap-3">
                <CheckCircle2 className="w-8 h-8 text-indigo-400" />
                <span>World Primer</span>
              </h1>
              <p className="mt-2 text-slate-400">Swarm synthesis complete. Review the extracted rules before igniting the engine.</p>
            </div>
            <div className="p-6 overflow-y-auto flex-1">
              <pre className="whitespace-pre-wrap bg-slate-950 p-4 rounded-xl border border-slate-800 font-mono text-sm text-slate-300">
                {pendingInput.message}
              </pre>
            </div>
            <div className="p-6 border-t border-slate-800 bg-slate-900 shrink-0 flex justify-end">
              <button
                onClick={handleApprovePrimer}
                disabled={!isConnected}
                className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white px-8 py-3 rounded-lg font-medium transition-all shadow-[0_0_20px_rgba(79,70,229,0.3)] disabled:opacity-50"
              >
                <Sparkles className="w-5 h-5" />
                <span>Ignite Storyteller</span>
              </button>
            </div>
          </motion.div>
        )}

      </AnimatePresence>
    </div>
  );
}
