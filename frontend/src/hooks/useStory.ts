import { useState, useEffect, useRef, useCallback } from 'react';

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8001';
const WS_BASE = (import.meta.env.VITE_WS_BASE as string | undefined) ?? 'ws://localhost:8001/ws/story';

export type RequestInputData = {
  interrupt_id: string;
  message: string;
};

export type LoreStatus = {
  id: number;
  message: string;
  timestamp: string;
};

export type SuspicionTier = 'oblivious' | 'uneasy' | 'suspicious' | 'breakthrough';

// Phase B: typed-choice taxonomy from the storyteller's ChapterOutput tail.
export type ChoiceTier = 'canon' | 'divergence' | 'character' | 'wildcard';

export type Choice = {
  text: string;
  tier: ChoiceTier;
  tied_event?: string | null;
};

export type ChapterQuestion = {
  question: string;
  context: string;
  type: 'choice';
  options: string[];
};

export type ActiveCharacter = {
  name: string;
  trust: number;
  disposition: string;
  present: boolean;
};

export type ActiveDivergence = {
  event_id: string;
  description: string;
  ripple_count: number;
};

export type StoryStateData = {
  power_debt_level: number;
  active_characters: ActiveCharacter[];
  active_divergences: ActiveDivergence[];
  timeline_date: string;
  location: string;
  mood: string;
  chapter: number;
};

// ProseFragment kept as a TYPE export for callers that import it (e.g.
// StoryView.tsx). Post-refactor the array stays empty -- streaming is
// gone; chapter prose now arrives atomically via the chapter_meta frame.
export type ProseFragment = {
  id: number;
  author: 'narrator' | 'system';
  text: string;
};

// ChapterMetaData now carries the chapter prose alongside the structured
// tail. Streaming is gone; this single frame is what the player sees as
// "the chapter completed". Backend writes `prose` from
// state.last_story_text in src/ws/runner.py::_emit_chapter_meta.
export type ChapterMetaData = {
  prose: string;
  summary: string;
  choices: Array<{
    text: string;
    tier: 'canon' | 'divergence' | 'character' | 'wildcard';
    tied_event: string | null;
  }>;
  choice_timeline_notes: {
    upcoming_event_considered: string | null;
    canon_path_choice: number | null;
    divergence_choice: number | null;
  };
  timeline: {
    chapter_start_date: string;
    chapter_end_date: string;
    time_elapsed: string;
    canon_events_addressed: string[];
    divergences_created: string[];
  };
  canon_elements_used: string[];
  power_limitations_shown: string[];
  stakes_tracking: {
    costs_paid: string[];
    near_misses: string[];
    power_debt_incurred: Record<string, string>;
    consequences_triggered: string[];
  };
  character_voices_used: string[];
  questions: Array<{
    question: string;
    context: string;
    type: 'choice';
    options: string[];
  }>;
};

// ─── Inbound WS message discriminated union ────────────────────────────────
export type WsMessage =
  | { type: 'request_input'; interrupt_id: string; message: string }
  | { type: 'status'; message: string }
  | { type: 'node_complete'; node: string; copy: string }
  | { type: 'turn_complete'; invocation_id?: string }
  | { type: 'error'; message: string; kind?: 'session_not_found' | 'timeout' | string }
  | { type: 'undo_complete' }
  | { type: 'rewrite_started' }
  | { type: 'state_update'; data: StoryStateData }
  | { type: 'chapter_meta'; data: ChapterMetaData };

function assertNever(x: never): never {
  throw new Error(`Unhandled WS message type: ${JSON.stringify(x)}`);
}

const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000, 16000];

export function useStory(sessionId: string | null, isResumed: boolean = false) {
  const [isConnected, setIsConnected] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [isResearching, setIsResearching] = useState(false);

  // `prose` now holds the LATEST chapter only (replaced on each
  // chapter_meta frame). Streaming is gone; per-word append-style state
  // is unnecessary. The proseFragments array is kept as an empty
  // backwards-compat surface for components that still import the type.
  const [prose, setProse] = useState<string>('');
  const [proseFragments] = useState<ProseFragment[]>([]);
  const [pendingInput, setPendingInput] = useState<RequestInputData | null>(null);
  const [choices, setChoices] = useState<Choice[]>([]);
  const [choicePrompt, setChoicePrompt] = useState<string>('');
  const [pendingQuestions, setPendingQuestions] = useState<ChapterQuestion[]>([]);
  const [loreUpdates, setLoreUpdates] = useState<LoreStatus[]>([]);
  const [setupComplete, setSetupComplete] = useState(isResumed);
  const [invocationHistory, setInvocationHistory] = useState<string[]>([]);
  const [storyState, setStoryState] = useState<StoryStateData | null>(null);
  // currentPhase carries the latest node_complete copy ("Drafting
  // chapter…", "Recording outcomes…", etc.) so the loading state has
  // progressive feedback during the ~60-120s chapter generation.
  const [currentPhase, setCurrentPhase] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const loreIdRef = useRef(0);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<number | null>(null);
  const intentionalCloseRef = useRef(false);

  // Manage WebSocket Connection (with reconnect)
  useEffect(() => {
    if (!sessionId) return;

    let cancelled = false;

    const handleMessage = (raw: string) => {
      let data: WsMessage;
      try {
        data = JSON.parse(raw) as WsMessage;
      } catch (e) {
        console.error('Error parsing WS message:', e);
        return;
      }

      switch (data.type) {
        case 'request_input':
          setIsTyping(false);
          setIsResearching(false);
          setCurrentPhase(null);
          setPendingInput({
            interrupt_id: data.interrupt_id,
            message: data.message,
          });
          // Setup HITLs never carry choices; chapter choices arrive via
          // chapter_meta. Reset both surfaces here.
          setChoices([]);
          setChoicePrompt('');
          setPendingQuestions([]);
          break;

        case 'status':
          loreIdRef.current += 1;
          setLoreUpdates(prev => [
            { id: loreIdRef.current, message: data.message, timestamp: new Date().toLocaleTimeString() },
            ...prev,
          ]);
          break;

        case 'node_complete':
          // Backend emits one of these per inner-agent end_of_agent
          // event. Replace the current phase copy so the loading UI
          // tracks workflow progress without streaming any prose.
          setCurrentPhase(data.copy);
          setIsTyping(true);
          setSetupComplete(true);
          break;

        case 'turn_complete':
          setIsTyping(false);
          setCurrentPhase(null);
          if (data.invocation_id) {
            setInvocationHistory(prev => [...prev, data.invocation_id as string]);
          }
          break;

        case 'undo_complete':
          setIsTyping(false);
          setCurrentPhase(null);
          setInvocationHistory(prev => prev.slice(0, -1));
          setPendingInput(null);
          setChoices([]);
          setChoicePrompt('');
          setPendingQuestions([]);
          break;

        case 'rewrite_started':
          setIsTyping(true);
          setCurrentPhase('Applying rewrite…');
          setInvocationHistory(prev => prev.slice(0, -1));
          setPendingInput(null);
          setChoices([]);
          setChoicePrompt('');
          setPendingQuestions([]);
          break;

        case 'error':
          setIsTyping(false);
          setCurrentPhase(null);
          if (data.kind === 'session_not_found') {
            window.dispatchEvent(new CustomEvent('fable:session-not-found'));
            return;
          }
          // For visible errors, surface inline by replacing prose
          // briefly. The chapter is still in DB; reload restores it.
          setProse(`[System Error]: ${data.message}`);
          break;

        case 'state_update':
          setStoryState(data.data);
          break;

        case 'chapter_meta': {
          // Atomic chapter render: prose + structured tail in one frame.
          // REPLACE prose so a reconnect re-emit doesn't double the
          // chapter on top of itself (kills the bug 08f5577 used to fix
          // via is_snapshot=true; the redesign makes that flag obsolete).
          setIsTyping(false);
          setIsResearching(false);
          setCurrentPhase(null);
          const meta = data.data;
          if (typeof meta.prose === 'string' && meta.prose.length > 0) {
            setProse(meta.prose);
            setSetupComplete(true);
          }
          const choicesIn = Array.isArray(meta.choices) ? meta.choices : [];
          const normalized: Choice[] = choicesIn.map((c) => ({
            text: String(c.text ?? ''),
            tier: c.tier,
            tied_event: c.tied_event ?? null,
          }));
          setChoices(normalized);
          setChoicePrompt('');
          setPendingQuestions(Array.isArray(meta.questions) ? meta.questions : []);
          break;
        }

        default:
          assertNever(data);
      }
    };

    const connect = () => {
      if (cancelled) return;
      const ws = new WebSocket(`${WS_BASE}/${sessionId}`);
      wsRef.current = ws;
      intentionalCloseRef.current = false;

      ws.onopen = () => {
        if (cancelled) return;
        console.log('WebSocket connected.');
        reconnectAttemptsRef.current = 0;
        setIsConnected(true);
      };

      ws.onmessage = (event) => handleMessage(event.data);

      ws.onclose = (ev) => {
        console.log('WebSocket disconnected.', ev.code, ev.reason);
        setIsConnected(false);

        if (cancelled || intentionalCloseRef.current || ev.code === 1000) {
          return;
        }

        if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
          const delay = RECONNECT_DELAYS_MS[reconnectAttemptsRef.current] ?? 16000;
          reconnectAttemptsRef.current += 1;
          console.log(
            `Reconnecting WS in ${delay}ms (attempt ${reconnectAttemptsRef.current}/${MAX_RECONNECT_ATTEMPTS})`,
          );
          reconnectTimerRef.current = window.setTimeout(connect, delay);
        } else {
          console.error('Max reconnect attempts reached. Giving up.');
        }
      };

      ws.onerror = (e) => {
        console.error('WebSocket error:', e);
      };
    };

    connect();

    return () => {
      cancelled = true;
      intentionalCloseRef.current = true;
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      wsRef.current?.close(1000, 'unmount');
    };
  }, [sessionId]);

  // 3. User Actions
  const sendChoice = useCallback((
    message: string,
    questionAnswers?: Record<string, string>,
  ) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    setIsTyping(true);
    setCurrentPhase('Sending choice…');

    // Option A: chapter choice goes as plain message (NOT a function_response
    // wrapper) so the runner gets a fresh invocation_id per chapter.
    const payload: Record<string, unknown> = { message };
    if (questionAnswers && Object.keys(questionAnswers).length > 0) {
      payload.question_answers = questionAnswers;
    }
    wsRef.current.send(JSON.stringify(payload));

    setChoices([]);
    setPendingQuestions([]);
  }, []);

  const submitInput = useCallback((
    payload: string | { choice: string; question_answers?: Record<string, string> },
  ) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || !pendingInput) return;

    const isStructured = typeof payload !== 'string';
    const resumePayload: string | { choice: string; question_answers: Record<string, string> } =
      isStructured
        ? { choice: payload.choice, question_answers: payload.question_answers ?? {} }
        : payload;

    if (pendingInput.interrupt_id === 'setup_configuration') {
      setIsResearching(true);
    }
    if (pendingInput.interrupt_id === 'setup_world_primer') {
      setIsResearching(false);
      setSetupComplete(true);
    }

    setIsTyping(true);
    setCurrentPhase('Submitting…');

    wsRef.current.send(JSON.stringify({
      interrupt_id: pendingInput.interrupt_id,
      resume_payload: resumePayload,
    }));

    setPendingInput(null);
    setPendingQuestions([]);
  }, [pendingInput]);

  const undoTurn = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    if (invocationHistory.length === 0) return;

    const lastInvocation = invocationHistory[invocationHistory.length - 1];
    setIsTyping(true);
    setCurrentPhase('Rewinding…');

    wsRef.current.send(JSON.stringify({
      action: 'undo',
      invocation_id: lastInvocation,
    }));
  }, [invocationHistory]);

  const rewriteTurn = useCallback((instruction: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    if (invocationHistory.length === 0) return;

    const lastInvocation = invocationHistory[invocationHistory.length - 1];
    setIsTyping(true);
    setCurrentPhase('Requesting rewrite…');

    wsRef.current.send(JSON.stringify({
      action: 'rewrite',
      invocation_id: lastInvocation,
      instruction: instruction,
    }));
  }, [invocationHistory]);

  return {
    isConnected,
    isTyping,
    isResearching,
    prose,
    proseFragments,
    pendingInput,
    choices,
    choicePrompt,
    loreUpdates,
    storyState,
    setupComplete,
    pendingQuestions,
    currentPhase,
    sendChoice,
    submitInput,
    undoTurn,
    rewriteTurn,
    canUndo: invocationHistory.length > 0,
  };
}
