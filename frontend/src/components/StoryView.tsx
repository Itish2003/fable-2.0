import { useState, useRef, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Send,
  Activity,
  AlertTriangle,
  Database,
  Cpu,
  Edit3,
  Menu,
  Undo2,
  X,
  Sparkles,
  Users,
  GitBranch,
  CircleDot,
  ServerCrash,
  ChevronLeft,
} from 'lucide-react';

import type {
  ChapterQuestion,
  Choice,
  ChoiceTier,
  LoreStatus,
  ProseFragment,
  RequestInputData,
  StoryStateData,
} from '../hooks/useStory';

interface StoryViewProps {
  onBack: () => void;
  story: {
    isConnected: boolean;
    isTyping: boolean;
    prose: string;
    proseFragments: ProseFragment[];
    pendingInput: RequestInputData | null;
    choices: Choice[];
    choicePrompt: string;
    pendingQuestions: ChapterQuestion[];
    loreUpdates: LoreStatus[];
    storyState: StoryStateData | null;
    sendChoice: (msg: string, questionAnswers?: Record<string, string>) => void;
    submitInput: (
      payload: string | { choice: string; question_answers?: Record<string, string> },
    ) => void;
    undoTurn: () => void;
    rewriteTurn: (instruction: string) => void;
    canUndo: boolean;
  };
}

type SidebarTab = 'lore' | 'cast' | 'divergences';

// ─── Tier theming ────────────────────────────────────────────────────────────
type TierTheme = {
  base: string;
  hover: string;
  border: string;
  text: string;
  badgeBg: string;
  badgeText: string;
  label: string;
};

// Phase B: typed-choice theming (canon / divergence / character / wildcard).
// Replaces the previous SuspicionTier-keyed map. Wildcard pulses to flag its
// high-impact "unexpected" semantics, mirroring the v1 styling for breakthroughs.
const CHOICE_THEMES: Record<ChoiceTier, TierTheme> = {
  canon: {
    base: 'bg-emerald-900/30',
    hover: 'hover:bg-emerald-900/50',
    border: 'border-emerald-700/50',
    text: 'text-emerald-100',
    badgeBg: 'bg-emerald-700/60',
    badgeText: 'text-emerald-100',
    label: 'Canon Path',
  },
  divergence: {
    base: 'bg-amber-900/25',
    hover: 'hover:bg-amber-900/40',
    border: 'border-amber-700/50',
    text: 'text-amber-100',
    badgeBg: 'bg-amber-700/50',
    badgeText: 'text-amber-200',
    label: 'Divergence',
  },
  character: {
    base: 'bg-indigo-900/30',
    hover: 'hover:bg-indigo-900/50',
    border: 'border-indigo-700/50',
    text: 'text-indigo-100',
    badgeBg: 'bg-indigo-700/60',
    badgeText: 'text-indigo-100',
    label: 'Character',
  },
  wildcard: {
    base: 'bg-rose-900/30',
    hover: 'hover:bg-rose-900/50',
    border: 'border-rose-600/60',
    text: 'text-rose-100',
    badgeBg: 'bg-rose-600/60',
    badgeText: 'text-rose-50',
    label: 'Wildcard',
  },
};

// Default quick-pick chips for the rewrite modal.
const REWRITE_CHIPS = ['darker', 'more action', 'more dialogue', 'less expository'];

// ─── Author styling for text_delta ───────────────────────────────────────────
function fragmentClass(author: ProseFragment['author']): string {
  switch (author) {
    case 'narrator':
      return 'text-slate-300';
    case 'system':
      // Slightly muted tone + lighter weight to differentiate system asides
      // from narrator prose.
      return 'text-indigo-300/80 font-light italic';
  }
}

export default function StoryView({ story, onBack }: StoryViewProps) {
  const {
    isConnected,
    isTyping,
    prose,
    proseFragments,
    pendingInput,
    choices,
    choicePrompt,
    pendingQuestions,
    loreUpdates,
    storyState,
    sendChoice,
    submitInput,
    undoTurn,
    rewriteTurn,
    canUndo,
  } = story;

  // Per-question answers for the meta-questions panel. Cleared on each new
  // request_input arrival via parent hook resetting pendingQuestions.
  const [questionAnswers, setQuestionAnswers] = useState<Record<string, string>>({});
  useEffect(() => {
    setQuestionAnswers({});
  }, [pendingQuestions]);

  const allQuestionsAnswered =
    pendingQuestions.length === 0 ||
    pendingQuestions.every((q) => Boolean(questionAnswers[q.question]));

  const [inputText, setInputText] = useState('');
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>('lore');
  const [rewriteOpen, setRewriteOpen] = useState(false);
  const [rewriteText, setRewriteText] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const rewriteTextareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom as prose streams in
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [prose, pendingInput]);

  // Focus textarea & wire up Esc key when rewrite modal opens
  useEffect(() => {
    if (!rewriteOpen) return;
    rewriteTextareaRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setRewriteOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [rewriteOpen]);

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

  const openRewrite = () => {
    setRewriteText('');
    setRewriteOpen(true);
  };

  const submitRewrite = () => {
    const instr = rewriteText.trim();
    if (!instr) return;
    rewriteTurn(instr);
    setRewriteOpen(false);
  };

  const proseTail = useMemo(() => prose.slice(-200), [prose]);

  return (
    <div className="flex h-screen w-full bg-slate-950 overflow-hidden text-slate-100">

      {/* Mobile sidebar backdrop */}
      {mobileSidebarOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-30 md:hidden"
          onClick={() => setMobileSidebarOpen(false)}
        />
      )}

      {/* LEFT SIDEBAR: tabbed Lore / Cast / Divergences */}
      <aside className={`flex-col w-80 max-w-[85vw] bg-slate-900 border-r border-slate-800 ${
        mobileSidebarOpen ? 'fixed inset-y-0 left-0 z-40 flex' : 'hidden md:flex'
      }`}>
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Database className="w-5 h-5 text-indigo-400" />
            <h2 className="font-semibold tracking-wide text-slate-200">Story Telemetry</h2>
          </div>
          <button
            onClick={() => setMobileSidebarOpen(false)}
            className="md:hidden p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tab strip */}
        <div className="flex border-b border-slate-800 text-xs">
          <SidebarTabButton
            active={sidebarTab === 'lore'}
            onClick={() => setSidebarTab('lore')}
            icon={<Activity className="w-3.5 h-3.5" />}
            label="Lore"
            count={loreUpdates.length}
          />
          <SidebarTabButton
            active={sidebarTab === 'cast'}
            onClick={() => setSidebarTab('cast')}
            icon={<Users className="w-3.5 h-3.5" />}
            label="Cast"
            count={storyState?.active_characters.length ?? 0}
          />
          <SidebarTabButton
            active={sidebarTab === 'divergences'}
            onClick={() => setSidebarTab('divergences')}
            icon={<GitBranch className="w-3.5 h-3.5" />}
            label="Divergences"
            count={storyState?.active_divergences.length ?? 0}
          />
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {sidebarTab === 'lore' && <LoreStreamPane loreUpdates={loreUpdates} />}
          {sidebarTab === 'cast' && <CastPane characters={storyState?.active_characters ?? null} />}
          {sidebarTab === 'divergences' && (
            <DivergencesPane divergences={storyState?.active_divergences ?? null} />
          )}
        </div>
      </aside>

      {/* MAIN CONTENT: Narrative Prose */}
      <main className="flex-1 flex flex-col relative">
        {/* Header */}
        <header className="absolute top-0 inset-x-0 bg-gradient-to-b from-slate-950 to-transparent z-10 pointer-events-none">
          <div className="flex items-start justify-between px-4 md:px-6 pt-3 gap-2 md:gap-3">

            {/* Left: back + mobile sidebar toggle */}
            <div className="flex items-center gap-2 pointer-events-auto">
              <button
                onClick={onBack}
                className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-300 transition-colors py-1.5"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
                <span>Stories</span>
              </button>
              <button
                onClick={() => setMobileSidebarOpen(true)}
                className="md:hidden flex items-center gap-1 text-xs text-slate-600 hover:text-slate-300 transition-colors py-1.5 px-2 rounded-lg hover:bg-slate-800/50"
              >
                <Menu className="w-3.5 h-3.5" />
              </button>
            </div>

            {/* Center: strain bar — desktop only */}
            <div className="pointer-events-auto hidden md:block mt-8">
              {storyState !== null && (
                <StrainBar level={storyState.power_debt_level} />
              )}
            </div>

            {/* Right: connection pill + info row */}
            <div className="flex flex-col items-end gap-2 pointer-events-auto">
              <div className="flex items-center gap-1.5 text-xs bg-slate-900/80 px-2.5 md:px-3 py-1.5 rounded-full border border-slate-800 backdrop-blur-sm">
                {isConnected ? (
                  <>
                    <Cpu className={`w-3.5 h-3.5 md:w-4 md:h-4 ${isTyping ? 'text-emerald-400 animate-pulse' : 'text-slate-400'}`} />
                    <span className={isTyping ? 'text-emerald-400' : 'text-slate-400'}>
                      {isTyping ? 'Running...' : 'Idle'}
                    </span>
                  </>
                ) : (
                  <>
                    <ServerCrash className="w-3.5 h-3.5 md:w-4 md:h-4 text-rose-500" />
                    <span className="text-rose-500">Disconnected</span>
                  </>
                )}
              </div>
              {storyState !== null && (
                <div className="hidden md:block">
                  <InfoRow state={storyState} />
                </div>
              )}
            </div>

          </div>

          {/* Mobile: strain bar below the header row */}
          {storyState !== null && (
            <div className="md:hidden px-4 pb-1 pointer-events-auto">
              <StrainBar level={storyState.power_debt_level} />
            </div>
          )}
        </header>

        {/* Prose Area */}
        <div className="flex-1 overflow-y-auto pt-24 pb-4 px-6 md:px-12 lg:px-24">
          <div className="max-w-3xl mx-auto prose prose-invert prose-slate prose-lg">
            <div className="whitespace-pre-wrap leading-relaxed tracking-wide font-serif">
              {proseFragments.length === 0 ? (
                <span className="text-slate-600 italic">
                  {prose || (isTyping ? 'Igniting the narrative engine...' : 'Reconnected. Type your next action or use the input below to continue.')}
                </span>
              ) : (
                proseFragments.map((f) => (
                  <span key={f.id} className={fragmentClass(f.author)}>
                    {f.text}
                  </span>
                ))
              )}
            </div>

            {/* Blinking cursor effect while typing */}
            {isTyping && !pendingInput && (
              <span className="inline-block w-2 h-5 ml-1 bg-slate-400 animate-pulse align-middle" />
            )}

            <div ref={bottomRef} className="h-4" />
          </div>
        </div>

        {/* Input Area — capped to 50vh; choices + meta-questions + input
            scroll internally so they can never dominate the chapter prose. */}
        <div className="relative px-4 md:px-6 pt-4 pb-6 bg-gradient-to-t from-slate-950 via-slate-950 to-slate-950/0 max-h-[50vh] overflow-y-auto">
          {/* Top fade so prose appears to flow behind the panel. */}
          <div className="pointer-events-none absolute inset-x-0 -top-6 h-6 bg-gradient-to-t from-slate-950 to-transparent" />
          <div className="max-w-3xl mx-auto space-y-3">

            {/* Choice prompt header (legacy; usually empty for typed choices) */}
            {choicePrompt && choices.length > 0 && !isTyping && (
              <p className="text-xs uppercase tracking-widest text-slate-500 font-semibold">
                {choicePrompt}
              </p>
            )}

            {/* Meta-questions: shape the next chapter's tone/style */}
            {pendingQuestions.length > 0 && !isTyping && (
              <MetaQuestions
                questions={pendingQuestions}
                answers={questionAnswers}
                onAnswer={(q, opt) =>
                  setQuestionAnswers((prev) => ({ ...prev, [q]: opt }))
                }
              />
            )}

            {/* Choices */}
            {choices.length > 0 && !isTyping && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-2">
                {choices.map((choice, idx) => (
                  <ChoiceButton
                    key={idx}
                    choice={choice}
                    disabled={!isConnected || !allQuestionsAnswered}
                    onClick={() => {
                      // Option A: chapter choices ALWAYS go through sendChoice
                      // (plain message, fresh invocation_id). question_answers
                      // is bundled when the meta-questions panel was rendered.
                      sendChoice(choice.text, questionAnswers);
                    }}
                  />
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
                    <Undo2 className="w-5 h-5" />
                  </button>
                  <button
                    onClick={openRewrite}
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
                  placeholder={pendingInput ? 'Answer the prompt...' : 'What do you do next?'}
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

      {/* Rewrite Modal */}
      <AnimatePresence>
        {rewriteOpen && (
          <RewriteModal
            value={rewriteText}
            onChange={setRewriteText}
            onCancel={() => setRewriteOpen(false)}
            onSubmit={submitRewrite}
            proseTail={proseTail}
            textareaRef={rewriteTextareaRef}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

// ─── Subcomponents ───────────────────────────────────────────────────────────

function SidebarTabButton({
  active,
  onClick,
  icon,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  count: number;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 px-3 py-2 flex items-center justify-center gap-1.5 transition-colors border-b-2 ${
        active
          ? 'border-indigo-500 text-indigo-300 bg-slate-800'
          : 'border-transparent text-slate-500 hover:text-slate-300 hover:bg-slate-800/40'
      }`}
    >
      {icon}
      <span>{label}</span>
      {count > 0 && (
        <span
          className={`text-[10px] px-1.5 py-0.5 rounded-full ${
            active ? 'bg-indigo-500/30 text-indigo-200' : 'bg-slate-800 text-slate-400'
          }`}
        >
          {count}
        </span>
      )}
    </button>
  );
}

function LoreStreamPane({ loreUpdates }: { loreUpdates: LoreStatus[] }) {
  if (loreUpdates.length === 0) {
    return <EmptyState text="No lore updates yet" />;
  }
  return (
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
  );
}

function CastPane({ characters }: { characters: Array<{ name: string; trust: number; disposition: string; present: boolean }> | null }) {
  if (!characters || characters.length === 0) {
    return <EmptyState text="No characters in scene" />;
  }
  return (
    <>
      {characters.map((c) => (
        <div
          key={c.name}
          className="text-xs bg-slate-800/50 p-3 rounded-md border border-slate-700/50 shadow-sm"
        >
          <div className="flex justify-between items-center mb-1.5">
            <span className="flex items-center gap-1.5">
              <CircleDot
                className={`w-3 h-3 ${c.present ? 'text-emerald-400' : 'text-slate-600'}`}
              />
              <span className="text-slate-100 font-medium">{c.name}</span>
            </span>
            <TrustPill trust={c.trust} />
          </div>
          <div className="text-slate-400 capitalize">{c.disposition}</div>
        </div>
      ))}
    </>
  );
}

function DivergencesPane({ divergences }: { divergences: Array<{ event_id: string; description: string; ripple_count: number }> | null }) {
  if (!divergences || divergences.length === 0) {
    return <EmptyState text="No timeline divergences" />;
  }
  return (
    <>
      {divergences.map((d) => (
        <div
          key={d.event_id}
          className="text-xs bg-slate-800/50 p-3 rounded-md border border-slate-700/50 shadow-sm"
        >
          <div className="flex justify-between items-center mb-1 text-slate-400">
            <span className="flex items-center gap-1">
              <GitBranch className="w-3 h-3" />
              <span className="font-mono text-[10px]">{d.event_id}</span>
            </span>
            <span className="text-rose-300/80 text-[10px]">{d.ripple_count} ripples</span>
          </div>
          <p className="text-slate-300">{d.description}</p>
        </div>
      ))}
    </>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="text-xs text-slate-500 italic text-center pt-8">{text}</div>
  );
}

function TrustPill({ trust }: { trust: number }) {
  // Trust expected in a numeric range; map to color buckets.
  const tone =
    trust >= 70 ? 'bg-emerald-700/50 text-emerald-200'
    : trust >= 40 ? 'bg-amber-700/50 text-amber-200'
    : 'bg-rose-700/50 text-rose-200';
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${tone}`}>trust {trust}</span>
  );
}

function StrainBar({ level }: { level: number }) {
  const clamped = Math.max(0, Math.min(level, 100));
  const high = level > 80;
  const fillTone = high
    ? 'bg-rose-500'
    : level > 50
    ? 'bg-orange-400'
    : 'bg-emerald-400';

  return (
    <div className="bg-slate-900/80 px-3 py-1.5 rounded-full border border-slate-800 backdrop-blur-sm flex items-center gap-2 text-xs">
      <AlertTriangle
        className={`w-4 h-4 ${high ? 'text-rose-400' : 'text-slate-400'}`}
      />
      <span className="uppercase tracking-wider text-slate-400">Strain</span>
      <div className="w-32 h-2 bg-slate-800 rounded-full overflow-hidden">
        <motion.div
          className={`h-full ${fillTone}`}
          initial={false}
          animate={{
            width: `${clamped}%`,
            opacity: high ? [1, 0.55, 1] : 1,
          }}
          transition={
            high
              ? { width: { duration: 0.3 }, opacity: { repeat: Infinity, duration: 1.0 } }
              : { duration: 0.3 }
          }
        />
      </div>
      <span className={`tabular-nums ${high ? 'text-rose-300' : 'text-slate-300'}`}>
        {level}
      </span>
    </div>
  );
}

function InfoRow({ state }: { state: StoryStateData }) {
  return (
    <div className="flex items-center gap-2 text-[11px] uppercase tracking-widest font-mono bg-slate-900/70 px-3 py-1 rounded-full border border-slate-800 backdrop-blur-sm text-slate-400">
      <span>Ch. {state.chapter}</span>
      <span className="text-slate-700">|</span>
      <span>{state.timeline_date}</span>
      <span className="text-slate-700">|</span>
      <span className="text-slate-300">{state.location}</span>
      <span className="text-slate-700">|</span>
      <span className="text-indigo-300/80">{state.mood}</span>
    </div>
  );
}

function ChoiceButton({
  choice,
  disabled,
  onClick,
}: {
  choice: Choice;
  disabled: boolean;
  onClick: () => void;
}) {
  const theme = CHOICE_THEMES[choice.tier];
  const isWildcard = choice.tier === 'wildcard';

  const inner = (
    <button
      onClick={onClick}
      disabled={disabled}
      title={choice.tied_event ? `Ties to: ${choice.tied_event}` : undefined}
      className={`relative w-full px-3 py-2 text-[13px] text-left rounded-lg transition-colors border ${theme.base} ${theme.hover} ${theme.border} ${theme.text} disabled:opacity-50 disabled:cursor-not-allowed`}
    >
      <span className="flex items-start gap-2">
        <span className="flex-1 leading-snug">{choice.text}</span>
        <span
          className={`shrink-0 text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded-full ${theme.badgeBg} ${theme.badgeText}`}
        >
          {theme.label}
        </span>
      </span>
    </button>
  );

  if (isWildcard) {
    return (
      <motion.div
        animate={{ boxShadow: [
          '0 0 0px rgba(244,63,94,0.0)',
          '0 0 18px rgba(244,63,94,0.55)',
          '0 0 0px rgba(244,63,94,0.0)',
        ] }}
        transition={{ repeat: Infinity, duration: 2.2 }}
        className="rounded-lg"
      >
        {inner}
      </motion.div>
    );
  }
  return inner;
}

function MetaQuestions({
  questions,
  answers,
  onAnswer,
}: {
  questions: ChapterQuestion[];
  answers: Record<string, string>;
  onAnswer: (question: string, option: string) => void;
}) {
  return (
    <div className="space-y-2 mb-2">
      <p className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold">
        Shape the next chapter
      </p>
      {questions.map((q) => (
        <div
          key={q.question}
          className="rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-2 space-y-1.5"
        >
          <div className="text-[13px] text-slate-200 leading-snug">{q.question}</div>
          {q.context && (
            <div className="text-[10px] text-slate-500 italic leading-snug">{q.context}</div>
          )}
          <div className="flex flex-wrap gap-1.5">
            {q.options.map((opt) => {
              const selected = answers[q.question] === opt;
              return (
                <button
                  key={opt}
                  type="button"
                  onClick={() => onAnswer(q.question, opt)}
                  className={`text-[11px] px-2.5 py-1 rounded-full border transition-colors ${
                    selected
                      ? 'bg-indigo-600/40 border-indigo-500 text-indigo-100'
                      : 'bg-slate-800/60 border-slate-700 text-slate-300 hover:bg-slate-700/60'
                  }`}
                >
                  {opt}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function RewriteModal({
  value,
  onChange,
  onCancel,
  onSubmit,
  proseTail,
  textareaRef,
}: {
  value: string;
  onChange: (v: string) => void;
  onCancel: () => void;
  onSubmit: () => void;
  proseTail: string;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-6"
      onClick={onCancel}
    >
      <motion.div
        initial={{ opacity: 0, y: 20, scale: 0.96 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 20, scale: 0.96 }}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl overflow-hidden"
      >
        <div className="p-5 border-b border-slate-800 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-slate-100 font-semibold">
            <Sparkles className="w-5 h-5 text-indigo-400" />
            <span>Rewrite Last Turn</span>
          </h2>
          <button
            onClick={onCancel}
            className="p-1 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-800"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          <div>
            <p className="text-[11px] uppercase tracking-widest text-slate-500 mb-1">Context</p>
            <pre className="text-xs text-slate-400 bg-slate-950/70 border border-slate-800 rounded-md p-3 whitespace-pre-wrap font-serif max-h-32 overflow-y-auto">
              {proseTail || '(no prose yet)'}
            </pre>
          </div>

          <div>
            <p className="text-[11px] uppercase tracking-widest text-slate-500 mb-1">Instruction</p>
            <textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              placeholder="What should change in the rewritten turn?"
              className="w-full h-28 bg-slate-950 border border-slate-700 rounded-md p-3 text-slate-200 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 resize-none"
            />
          </div>

          <div className="flex flex-wrap gap-2">
            {REWRITE_CHIPS.map((chip) => (
              <button
                key={chip}
                type="button"
                onClick={() =>
                  onChange(value ? `${value.trim()} ${chip}`.trim() : chip)
                }
                className="text-xs px-2.5 py-1 rounded-full bg-slate-800/80 text-slate-300 border border-slate-700 hover:bg-indigo-600/30 hover:border-indigo-500/50 transition-colors"
              >
                {chip}
              </button>
            ))}
          </div>
        </div>

        <div className="px-5 py-4 border-t border-slate-800 bg-slate-900 flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="px-4 py-2 rounded-lg text-slate-300 hover:bg-slate-800 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onSubmit}
            disabled={!value.trim()}
            className="px-5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium transition-colors disabled:opacity-40"
          >
            Submit Rewrite
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}
