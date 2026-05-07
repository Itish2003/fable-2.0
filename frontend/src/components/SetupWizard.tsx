import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { BookOpen, Sparkles, SlidersHorizontal, ArrowRight, ShieldAlert, Cpu, Search, CheckCircle2 } from 'lucide-react';

type RequestInputData = {
  interrupt_id: string;
  message: string;
};

interface SetupWizardProps {
  pendingInput: RequestInputData | null;
  submitInput: (text: string) => void;
  isConnected: boolean;
  isResearching: boolean;
}

export default function SetupWizard({ pendingInput, submitInput, isConnected, isResearching }: SetupWizardProps) {
  // Step 1: Lore Dump
  const [loreDump, setLoreDump] = useState('');
  
  // Step 2: Configuration
  const [powerLevel, setPowerLevel] = useState('city');
  const [storyTone, setStoryTone] = useState('balanced');
  const [isolatePowerset, setIsolatePowerset] = useState(true);

  if (isResearching) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-950 p-6">
        <motion.div 
          key="researching"
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          className="flex flex-col items-center space-y-6 max-w-md text-center"
        >
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ repeat: Infinity, duration: 4, ease: "linear" }}
            className="w-24 h-24 border-t-2 border-l-2 border-emerald-500 rounded-full flex items-center justify-center relative"
          >
            <Search className="w-8 h-8 text-emerald-400 absolute" />
          </motion.div>
          <div className="space-y-2">
            <h2 className="text-2xl font-serif text-slate-100">Swarm Deployed</h2>
            <p className="text-slate-400">Lore Hunters are actively searching wikis and processing local source text to synthesize your crossover ruleset...</p>
          </div>
        </motion.div>
      </div>
    );
  }

  if (!pendingInput) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-950">
        <motion.div 
          animate={{ opacity: [0.5, 1, 0.5] }} 
          transition={{ repeat: Infinity, duration: 2 }}
          className="flex flex-col items-center space-y-4 text-emerald-400"
        >
          <Cpu className="w-12 h-12" />
          <h2 className="text-xl font-serif tracking-widest uppercase">Connecting to Weave...</h2>
        </motion.div>
      </div>
    );
  }

  const isLoreDump = pendingInput.interrupt_id === 'setup_lore_dump';
  const isConfig = pendingInput.interrupt_id === 'setup_configuration';
  const isPrimer = pendingInput.interrupt_id === 'setup_world_primer';

  const handleSubmitLore = () => {
    if (!loreDump.trim()) return;
    submitInput(loreDump);
  };

  const handleSubmitConfig = () => {
    const configData = JSON.stringify({
      power_level: powerLevel,
      story_tone: storyTone,
      isolate_powerset: isolatePowerset
    });
    submitInput(configData);
  };
  
  const handleApprovePrimer = () => {
    submitInput("Approved.");
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 p-6">
      <AnimatePresence mode="wait">
        
        {/* LORE DUMP STEP */}
        {isLoreDump && (
          <motion.div 
            key="lore_dump"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, x: -50 }}
            className="w-full max-w-3xl bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden"
          >
            <div className="bg-slate-950/50 p-6 border-b border-slate-800">
              <h1 className="text-3xl font-serif text-slate-100 flex items-center space-x-3">
                <BookOpen className="w-8 h-8 text-indigo-400" />
                <span>Create Your Story</span>
              </h1>
              <p className="mt-2 text-slate-400">{pendingInput.message}</p>
            </div>
            
            <div className="p-6 space-y-6">
              <textarea
                value={loreDump}
                onChange={(e) => setLoreDump(e.target.value)}
                placeholder="E.g., I am a gravity user in the Mahouka universe. My core ability allows me to invert the gravitational pull of specific objects..."
                className="w-full h-64 bg-slate-950 border border-slate-700 rounded-xl p-4 text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 resize-none font-serif leading-relaxed"
              />
              
              <div className="flex justify-end">
                <button
                  onClick={handleSubmitLore}
                  disabled={!loreDump.trim() || !isConnected}
                  className="flex items-center space-x-2 bg-indigo-600 hover:bg-indigo-500 text-white px-6 py-3 rounded-lg font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <span>Start Setup Conversation</span>
                  <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          </motion.div>
        )}

        {/* CONFIGURATION STEP */}
        {isConfig && (
          <motion.div 
            key="config"
            initial={{ opacity: 0, x: 50 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="w-full max-w-2xl bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden"
          >
            <div className="bg-slate-950/50 p-6 border-b border-slate-800">
              <h1 className="text-3xl font-serif text-slate-100 flex items-center space-x-3">
                <SlidersHorizontal className="w-8 h-8 text-emerald-400" />
                <span>Simulation Parameters</span>
              </h1>
              <p className="mt-2 text-slate-400">Tune the physics and tone of the narrative engine.</p>
            </div>
            
            <div className="p-6 space-y-8">
              
              {/* Power Level */}
              <div className="space-y-3">
                <label className="text-sm font-semibold tracking-wider text-slate-300 uppercase">Power Level</label>
                <div className="grid grid-cols-3 gap-3">
                  {['street', 'city', 'continental'].map(lvl => (
                    <button
                      key={lvl}
                      onClick={() => setPowerLevel(lvl)}
                      className={`p-3 rounded-lg border text-sm font-medium capitalize transition-all ${powerLevel === lvl ? 'bg-indigo-500/20 border-indigo-500 text-indigo-300' : 'bg-slate-950 border-slate-800 text-slate-500 hover:border-slate-600'}`}
                    >
                      {lvl}
                    </button>
                  ))}
                </div>
              </div>

              {/* Story Tone */}
              <div className="space-y-3">
                <label className="text-sm font-semibold tracking-wider text-slate-300 uppercase">Narrative Tone</label>
                <div className="grid grid-cols-3 gap-3">
                  {['dark', 'balanced', 'heroic'].map(tone => (
                    <button
                      key={tone}
                      onClick={() => setStoryTone(tone)}
                      className={`p-3 rounded-lg border text-sm font-medium capitalize transition-all ${storyTone === tone ? 'bg-emerald-500/20 border-emerald-500 text-emerald-300' : 'bg-slate-950 border-slate-800 text-slate-500 hover:border-slate-600'}`}
                    >
                      {tone}
                    </button>
                  ))}
                </div>
              </div>

              {/* Isolation Rule */}
              <div className="flex items-center justify-between p-4 bg-slate-950 border border-slate-800 rounded-xl">
                <div className="flex items-center space-x-3">
                  <ShieldAlert className={`w-5 h-5 ${isolatePowerset ? 'text-rose-400' : 'text-slate-500'}`} />
                  <div>
                    <h3 className="text-slate-200 font-medium">Isolate Powerset</h3>
                    <p className="text-xs text-slate-500">Prevent native magic systems from interacting with your anomaly.</p>
                  </div>
                </div>
                <button 
                  onClick={() => setIsolatePowerset(!isolatePowerset)}
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
                  className="flex items-center space-x-2 bg-emerald-600 hover:bg-emerald-500 text-white px-6 py-3 rounded-lg font-medium transition-all"
                >
                  <Sparkles className="w-4 h-4" />
                  <span>Execute Research Swarm</span>
                </button>
              </div>
              
            </div>
          </motion.div>
        )}
        
        {/* WORLD PRIMER STEP */}
        {isPrimer && (
          <motion.div 
            key="primer"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95 }}
            className="w-full max-w-4xl max-h-[85vh] flex flex-col bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden"
          >
            <div className="bg-slate-950/50 p-6 border-b border-slate-800 shrink-0">
              <h1 className="text-3xl font-serif text-slate-100 flex items-center space-x-3">
                <CheckCircle2 className="w-8 h-8 text-indigo-400" />
                <span>World Primer Synthesis</span>
              </h1>
              <p className="mt-2 text-slate-400">The Swarm has successfully compiled the crossover constraints. Please review the extracted rules before igniting the engine.</p>
            </div>
            
            <div className="p-6 overflow-y-auto space-y-4 font-mono text-sm text-slate-300">
                {/* Try to parse and format the JSON if possible, otherwise just pre */}
                <pre className="whitespace-pre-wrap bg-slate-950 p-4 rounded-xl border border-slate-800">
                    {pendingInput.message}
                </pre>
            </div>
            
            <div className="p-6 border-t border-slate-800 bg-slate-900 shrink-0 flex justify-end">
                <button
                  onClick={handleApprovePrimer}
                  disabled={!isConnected}
                  className="flex items-center space-x-2 bg-indigo-600 hover:bg-indigo-500 text-white px-8 py-3 rounded-lg font-medium transition-all shadow-[0_0_20px_rgba(79,70,229,0.3)]"
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