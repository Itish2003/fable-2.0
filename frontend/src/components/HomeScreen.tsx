import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { BookOpen, MapPin, Sparkles, Plus, Clock, ChevronRight, Loader2, Wind, Trash2 } from 'lucide-react';

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8001';

type StoryCard = {
  session_id: string;
  chapter: number;
  location: string;
  mood: string;
  story_premise: string;
  setup_complete: boolean;
  power_debt_level: number;
  last_update: string | null;
};

interface HomeScreenProps {
  onNewStory: () => Promise<void>;
  onContinue: (sessionId: string) => void;
}

export default function HomeScreen({ onNewStory, onContinue }: HomeScreenProps) {
  const [stories, setStories] = useState<StoryCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deletingInFlight, setDeletingInFlight] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/stories/local_tester`)
      .then(r => r.json())
      .then(data => {
        setStories(data.stories || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const handleNew = async () => {
    setStarting(true);
    try {
      await onNewStory();
    } catch {
      setStarting(false);
    }
  };

  const handleDelete = async (sessionId: string) => {
    setDeletingInFlight(true);
    try {
      await fetch(`${API_BASE}/stories/local_tester/${sessionId}`, { method: 'DELETE' });
      setStories(prev => prev.filter(s => s.session_id !== sessionId));
    } catch {
      // silent — leave card in place so user can retry
    } finally {
      setDeletingId(null);
      setDeletingInFlight(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center p-4 sm:p-8">
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="text-center mb-8 sm:mb-12"
      >
        <div className="flex items-center justify-center gap-3 mb-3">
          <Wind className="w-6 h-6 sm:w-8 sm:h-8 text-indigo-400" />
          <h1 className="text-3xl sm:text-5xl font-serif tracking-[0.3em] sm:tracking-[0.4em] text-slate-100 uppercase">Fable</h1>
        </div>
        <p className="text-slate-600 tracking-widest text-xs uppercase">AI Narrative Simulation Engine</p>
      </motion.div>

      <div className="w-full max-w-xl space-y-3">
        {/* New Story */}
        <motion.button
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          onClick={handleNew}
          disabled={starting}
          className="w-full flex items-center justify-between p-4 sm:p-5 bg-indigo-600/15 hover:bg-indigo-600/25 border border-indigo-500/40 hover:border-indigo-500/70 rounded-2xl transition-all group disabled:opacity-60"
        >
          <div className="flex items-center gap-4">
            <div className="w-11 h-11 rounded-xl bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center shrink-0">
              {starting
                ? <Loader2 className="w-5 h-5 text-indigo-400 animate-spin" />
                : <Plus className="w-5 h-5 text-indigo-400" />}
            </div>
            <div className="text-left">
              <div className="text-slate-100 font-semibold">New Story</div>
              <div className="text-slate-500 text-sm">Begin a new narrative in any universe</div>
            </div>
          </div>
          <ChevronRight className="w-5 h-5 text-slate-600 group-hover:text-indigo-400 transition-colors" />
        </motion.button>

        {/* Existing stories */}
        {loading ? (
          <div className="text-center py-10 text-slate-700">
            <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2" />
            <span className="text-xs uppercase tracking-widest">Loading...</span>
          </div>
        ) : stories.length > 0 ? (
          <>
            <p className="text-xs text-slate-700 uppercase tracking-widest font-semibold px-1 pt-4 pb-1">
              Continue
            </p>
            <AnimatePresence>
              {stories.map((s, i) => (
                <motion.div
                  key={s.session_id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, x: -20 }}
                  transition={{ delay: i * 0.06 }}
                  className="group flex items-stretch bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden hover:border-slate-700 transition-colors"
                >
                  {/* Main continue button */}
                  <button
                    onClick={() => onContinue(s.session_id)}
                    disabled={deletingId === s.session_id}
                    className="flex-1 min-w-0 flex items-center gap-3 sm:gap-4 p-4 sm:p-5 text-left disabled:opacity-40 transition-opacity"
                  >
                    <div className="w-11 h-11 rounded-xl bg-slate-800 border border-slate-700 flex items-center justify-center shrink-0">
                      <BookOpen className="w-5 h-5 text-slate-500" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2 mb-1.5">
                        {s.setup_complete ? (
                          <span className="text-xs px-2 py-0.5 bg-emerald-500/10 text-emerald-400 border border-emerald-500/25 rounded-full">
                            Ch. {s.chapter}
                          </span>
                        ) : (
                          <span className="text-xs px-2 py-0.5 bg-amber-500/10 text-amber-400 border border-amber-500/25 rounded-full">
                            Setup in progress
                          </span>
                        )}
                        {s.setup_complete && s.location !== 'Unknown' && (
                          <span className="text-xs text-slate-500 flex items-center gap-1">
                            <MapPin className="w-3 h-3" />{s.location}
                          </span>
                        )}
                        {s.setup_complete && s.mood !== 'Neutral' && (
                          <span className="text-xs text-slate-500 flex items-center gap-1">
                            <Sparkles className="w-3 h-3" />{s.mood}
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-slate-400 truncate">{s.story_premise}</p>
                      {s.last_update && (
                        <p className="text-xs text-slate-700 mt-1.5 flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {new Date(s.last_update).toLocaleDateString(undefined, {
                            month: 'short', day: 'numeric', year: 'numeric',
                          })}
                        </p>
                      )}
                    </div>
                  </button>

                  {/* Right action column: delete or confirm */}
                  <AnimatePresence mode="wait">
                    {deletingId === s.session_id ? (
                      <motion.div
                        key="confirm"
                        initial={{ opacity: 0, width: 0 }}
                        animate={{ opacity: 1, width: 'auto' }}
                        exit={{ opacity: 0, width: 0 }}
                        className="flex items-center gap-2 px-4 border-l border-rose-800/40 bg-rose-950/30 shrink-0"
                      >
                        <span className="text-xs text-rose-300 whitespace-nowrap">Delete?</span>
                        <button
                          onClick={() => setDeletingId(null)}
                          className="text-xs px-2.5 py-1 rounded-lg bg-slate-700 text-slate-300 hover:bg-slate-600 transition-colors whitespace-nowrap"
                        >
                          Cancel
                        </button>
                        <button
                          onClick={() => handleDelete(s.session_id)}
                          disabled={deletingInFlight}
                          className="text-xs px-2.5 py-1 rounded-lg bg-rose-600 text-white hover:bg-rose-500 disabled:opacity-50 transition-colors whitespace-nowrap"
                        >
                          {deletingInFlight ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Delete'}
                        </button>
                      </motion.div>
                    ) : (
                      <motion.div
                        key="actions"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="flex flex-col items-center justify-between py-3 px-2 sm:px-3 border-l border-slate-800 shrink-0 gap-1"
                      >
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setDeletingId(s.session_id);
                          }}
                          className="p-3 sm:p-1.5 rounded-lg text-slate-400 sm:text-slate-700 hover:text-rose-400 hover:bg-rose-900/20 transition-colors sm:opacity-0 sm:group-hover:opacity-100"
                          title="Delete story"
                          aria-label="Delete story"
                        >
                          <Trash2 className="w-5 h-5 sm:w-3.5 sm:h-3.5" />
                        </button>
                        <ChevronRight className="hidden sm:block w-4 h-4 text-slate-700 group-hover:text-slate-400 transition-colors" />
                      </motion.div>
                    )}
                  </AnimatePresence>
                </motion.div>
              ))}
            </AnimatePresence>
          </>
        ) : null}
      </div>
    </div>
  );
}
