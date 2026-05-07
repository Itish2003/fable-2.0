import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, Activity, Database, ServerCrash, Cpu, Edit3 } from 'lucide-react';

export type RequestInputData = {
  interrupt_id: string;
  message: string;
};

export type LoreStatus = {
  id: number;
  message: string;
  timestamp: string;
};

interface StoryViewProps {
  story: {
    isConnected: boolean;
    isTyping: boolean;
    prose: string;
    pendingInput: RequestInputData | null;
    choices: string[];
    loreUpdates: LoreStatus[];
    sendChoice: (msg: string) => void;
    submitInput: (txt: string) => void;
    undoTurn: () => void;
    rewriteTurn: (instruction: string) => void;
    canUndo: boolean;
  }
}

export default function StoryView({ story }: StoryViewProps) {
  const { isConnected, isTyping, prose, pendingInput, choices, loreUpdates, sendChoice, submitInput, undoTurn, rewriteTurn, canUndo } = story;
  const [inputText, setInputText] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom as prose streams in
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [prose, pendingInput]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputText.trim()) return;
    
    if (pendingInput) {
      submitInput(inputText.trim());
    } else {
      sendChoice(inputText.trim());
    }
    setInputText('');
  };

  const handleRewrite = () => {
    const instruction = window.prompt("What should change in the story?");
    if (instruction && instruction.trim()) {
      rewriteTurn(instruction.trim());
    }
  };

  return (
    <div className="flex h-screen w-full bg-slate-950 overflow-hidden text-slate-100">
      
      {/* LEFT SIDEBAR: World Bible / Lore Updates */}
      <aside className="w-80 bg-slate-900 border-r border-slate-800 flex flex-col hidden md:flex">
        <div className="p-4 border-b border-slate-800 flex items-center space-x-2">
          <Database className="w-5 h-5 text-indigo-400" />
          <h2 className="font-semibold tracking-wide text-slate-200">Lore Bible Sync</h2>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          <AnimatePresence>
            {loreUpdates.map((update) => (
              <motion.div 
                key={update.id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                className="text-xs bg-slate-800/50 p-3 rounded-md border border-slate-700/50 shadow-sm"
              >
                <div className="flex justify-between items-center mb-1 text-slate-400">
                  <span className="flex items-center space-x-1">
                    <Activity className="w-3 h-3" />
                    <span>Archivist</span>
                  </span>
                  <span>{update.timestamp}</span>
                </div>
                <p className="text-slate-300">{update.message}</p>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </aside>

      {/* MAIN CONTENT: Narrative Prose */}
      <main className="flex-1 flex flex-col relative">
        {/* Header Status */}
        <header className="absolute top-0 inset-x-0 h-14 bg-gradient-to-b from-slate-950 to-transparent flex items-center justify-end px-6 z-10 pointer-events-none">
          <div className="flex items-center space-x-2 text-sm bg-slate-900/80 px-3 py-1.5 rounded-full border border-slate-800 backdrop-blur-sm pointer-events-auto">
            {isConnected ? (
              <>
                <Cpu className={`w-4 h-4 ${isTyping ? 'text-emerald-400 animate-pulse' : 'text-slate-400'}`} />
                <span className={isTyping ? 'text-emerald-400' : 'text-slate-400'}>
                  {isTyping ? 'Engine Running...' : 'Engine Idle'}
                </span>
              </>
            ) : (
              <>
                <ServerCrash className="w-4 h-4 text-rose-500" />
                <span className="text-rose-500">Disconnected</span>
              </>
            )}
          </div>
        </header>

        {/* Prose Area */}
        <div className="flex-1 overflow-y-auto pt-20 pb-8 px-6 md:px-12 lg:px-24">
          <div className="max-w-3xl mx-auto prose prose-invert prose-slate prose-lg">
            {/* We use pre-wrap to respect the newlines streamed from the LLM */}
            <div className="whitespace-pre-wrap leading-relaxed tracking-wide text-slate-300 font-serif">
              {prose || "Connecting to the ADK Narrative Engine..."}
            </div>
            
            {/* Blinking cursor effect while typing */}
            {isTyping && !pendingInput && (
              <span className="inline-block w-2 h-5 ml-1 bg-slate-400 animate-pulse align-middle" />
            )}
            
            {/* Auto-scroll anchor */}
            <div ref={bottomRef} className="h-4" />
          </div>
        </div>

        {/* Input Area */}
        <div className="p-6 bg-gradient-to-t from-slate-950 via-slate-950 to-transparent">
          <div className="max-w-3xl mx-auto space-y-4">
            
            {/* Choices Area */}
            {choices && choices.length > 0 && !isTyping && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-4">
                {choices.map((choice, idx) => (
                  <button
                    key={idx}
                    onClick={() => {
                        if (pendingInput && pendingInput.interrupt_id === 'user_choice_selection') {
                            submitInput(choice);
                        } else {
                            sendChoice(choice);
                        }
                    }}
                    disabled={!isConnected}
                    className="p-3 text-sm text-left bg-slate-800/80 hover:bg-indigo-600/40 border border-slate-700 rounded-lg transition-colors text-slate-200"
                  >
                    {choice}
                  </button>
                ))}
              </div>
            )}

            <div className="flex items-center space-x-2">
              {canUndo && !isTyping && (
                <>
                  <button
                    onClick={undoTurn}
                    disabled={!isConnected}
                    className="p-4 rounded-xl bg-rose-900/30 text-rose-400 border border-rose-800/50 hover:bg-rose-900/50 hover:text-rose-300 transition-colors"
                    title="Undo Last Turn"
                  >
                    <ServerCrash className="w-5 h-5" />
                  </button>
                  <button
                    onClick={handleRewrite}
                    disabled={!isConnected}
                    className="p-4 rounded-xl bg-indigo-900/30 text-indigo-400 border border-indigo-800/50 hover:bg-indigo-900/50 hover:text-indigo-300 transition-colors"
                    title="Rewrite Last Turn"
                  >
                    <Edit3 className="w-5 h-5" />
                  </button>
                </>
              )}
              
              <form 
                onSubmit={handleSubmit}
                className={`relative flex-1 flex items-center bg-slate-900 border rounded-xl shadow-lg transition-colors duration-200 overflow-hidden ${pendingInput ? 'border-indigo-500 ring-1 ring-indigo-500/50' : 'border-slate-700 focus-within:border-slate-500'}`}
              >
                <input 
                  type="text"
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  disabled={!isConnected || (isTyping && !pendingInput)}
                  placeholder={pendingInput ? "Answer the prompt..." : "What do you do next?"}
                  className="flex-1 bg-transparent border-none py-4 pl-5 pr-12 text-slate-200 placeholder:text-slate-500 focus:outline-none focus:ring-0 disabled:opacity-50"
                />
                <button 
                  type="submit"
                  disabled={!inputText.trim() || !isConnected || (isTyping && !pendingInput)}
                  className="absolute right-3 p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 disabled:opacity-50 disabled:hover:bg-transparent transition-colors"
                >
                  <Send className="w-5 h-5" />
                </button>
              </form>
            </div>
          </div>
        </div>
      </main>
      
    </div>
  );
}