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

export type Choice = {
  text: string;
  tier: SuspicionTier | null;
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

export type ProseFragment = {
  id: number;
  author: 'narrator' | 'system';
  text: string;
};

// ─── Inbound WS message discriminated union (covers ALL 8 backend types) ─────
export type WsMessage =
  | { type: 'text_delta'; text: string; author?: string }
  | { type: 'request_input'; interrupt_id: string; message: string }
  | { type: 'status'; message: string }
  | { type: 'turn_complete'; invocation_id?: string }
  | { type: 'error'; message: string }
  | { type: 'undo_complete' }
  | { type: 'rewrite_started' }
  | { type: 'state_update'; data: StoryStateData };

// Exhaustiveness helper: the never-check fallthrough surfaces unhandled
// message types as TypeScript errors at compile time.
function assertNever(x: never): never {
  throw new Error(`Unhandled WS message type: ${JSON.stringify(x)}`);
}

const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000, 16000];

export function useStory() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [isResearching, setIsResearching] = useState(false);

  const [prose, setProse] = useState<string>('');
  const [proseFragments, setProseFragments] = useState<ProseFragment[]>([]);
  const [pendingInput, setPendingInput] = useState<RequestInputData | null>(null);
  const [choices, setChoices] = useState<Choice[]>([]);
  const [choicePrompt, setChoicePrompt] = useState<string>('');
  const [loreUpdates, setLoreUpdates] = useState<LoreStatus[]>([]);
  const [setupComplete, setSetupComplete] = useState(false);
  const [invocationHistory, setInvocationHistory] = useState<string[]>([]);
  const [storyState, setStoryState] = useState<StoryStateData | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const loreIdRef = useRef(0);
  const fragmentIdRef = useRef(0);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<number | null>(null);
  const intentionalCloseRef = useRef(false);

  const appendFragment = useCallback((author: ProseFragment['author'], text: string) => {
    if (!text) return;
    setProseFragments(prev => {
      // Coalesce consecutive same-author chunks to keep the segment list short.
      const last = prev[prev.length - 1];
      if (last && last.author === author) {
        return [...prev.slice(0, -1), { ...last, text: last.text + text }];
      }
      fragmentIdRef.current += 1;
      return [...prev, { id: fragmentIdRef.current, author, text }];
    });
  }, []);

  // Keep the legacy `prose` string in sync so existing UI code that consumed
  // the concatenated form keeps working (cursor, scroll, rewrite modal context).
  const setProseAndFragment = useCallback((author: ProseFragment['author'], text: string) => {
    setProse(prev => prev + text);
    appendFragment(author, text);
  }, [appendFragment]);

  // 1. Initialize Session
  useEffect(() => {
    async function initSession() {
      try {
        const res = await fetch(`${API_BASE}/stories`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: 'local_tester' })
        });
        const data = await res.json();
        setSessionId(data.session_id);
      } catch (err) {
        console.error('Failed to create session:', err);
      }
    }
    initSession();
  }, []);

  // 2. Manage WebSocket Connection (with reconnect)
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
        case 'text_delta': {
          setIsTyping(true);
          // Honor the author tag: storyteller text is the narrator voice,
          // anything else (e.g. status-injected updates) renders in the
          // system tone.
          const author: ProseFragment['author'] =
            data.author && data.author !== 'storyteller' ? 'system' : 'narrator';
          setProseAndFragment(author, data.text);
          // If we are getting text deltas, we are definitely done with setup
          setSetupComplete(true);
          break;
        }

        case 'request_input':
          setIsTyping(false);
          setIsResearching(false);
          setPendingInput({
            interrupt_id: data.interrupt_id,
            message: data.message,
          });

          if (data.interrupt_id === 'user_choice_selection') {
            try {
              const parsed = JSON.parse(data.message) as {
                prompt?: string;
                choices?: Array<{ text: string; tier: Choice['tier'] }>;
              };
              const incoming = Array.isArray(parsed.choices) ? parsed.choices : [];
              // Defensively normalize: legacy paths may still emit bare strings.
              const normalized: Choice[] = incoming.map((c: unknown) => {
                if (typeof c === 'string') return { text: c, tier: null };
                if (c && typeof c === 'object' && 'text' in c) {
                  const obj = c as { text: string; tier?: Choice['tier'] };
                  return { text: obj.text, tier: obj.tier ?? null };
                }
                return { text: String(c), tier: null };
              });
              setChoices(normalized);
              setChoicePrompt(parsed.prompt ?? '');
            } catch {
              setChoices([]);
              setChoicePrompt('');
            }
          } else {
            setChoices([]);
            setChoicePrompt('');
          }

          // Ensure prose has a clean break before the prompt
          if (
            data.interrupt_id !== 'setup_lore_dump' &&
            data.interrupt_id !== 'setup_configuration' &&
            data.interrupt_id !== 'setup_world_primer' &&
            data.interrupt_id !== 'user_choice_selection'
          ) {
            setProseAndFragment('system', `\n\n> *${data.message}*\n\n`);
          }
          break;

        case 'status':
          loreIdRef.current += 1;
          setLoreUpdates(prev => [
            { id: loreIdRef.current, message: data.message, timestamp: new Date().toLocaleTimeString() },
            ...prev,
          ]);
          break;

        case 'turn_complete':
          setIsTyping(false);
          setProseAndFragment('narrator', '\n\n');
          if (data.invocation_id) {
            setInvocationHistory(prev => [...prev, data.invocation_id as string]);
          }
          break;

        case 'undo_complete':
          setIsTyping(false);
          setProseAndFragment('system', '\n\n**[System]**: Timeline rewind successful. Awaiting new input...\n\n');
          // Remove the last invocation since it was undone
          setInvocationHistory(prev => prev.slice(0, -1));
          setPendingInput(null);
          setChoices([]);
          setChoicePrompt('');
          break;

        case 'rewrite_started':
          setIsTyping(true);
          setProseAndFragment('system', '\n\n**[System]**: Applying rewrite constraint and regenerating timeline...\n\n');
          // Remove the last invocation since it was undone
          setInvocationHistory(prev => prev.slice(0, -1));
          setPendingInput(null);
          setChoices([]);
          setChoicePrompt('');
          break;

        case 'error':
          setIsTyping(false);
          setProseAndFragment('system', `\n\n[System Error]: ${data.message}\n\n`);
          break;

        case 'state_update':
          setStoryState(data.data);
          break;

        default:
          // Compile-time exhaustiveness: a future backend type that's not in
          // the WsMessage union will surface here as a TS error.
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

        // Abnormal close: exponential backoff reconnect.
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
  const sendChoice = useCallback((message: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    setProseAndFragment('system', `\n**[Action]**: ${message}\n\n`);
    setIsTyping(true);

    wsRef.current.send(JSON.stringify({ message }));
  }, [setProseAndFragment]);

  const submitInput = useCallback((text: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || !pendingInput) return;

    if (
      pendingInput.interrupt_id !== 'setup_lore_dump' &&
      pendingInput.interrupt_id !== 'setup_configuration' &&
      pendingInput.interrupt_id !== 'setup_world_primer'
    ) {
      setProseAndFragment('system', `**[Reply]**: ${text}\n\n`);
    }

    if (pendingInput.interrupt_id === 'setup_configuration') {
      setIsResearching(true);
    }

    // Once primer is approved, we are waiting for the storyteller, no longer researching
    if (pendingInput.interrupt_id === 'setup_world_primer') {
      setIsResearching(false);
    }

    setIsTyping(true);

    wsRef.current.send(JSON.stringify({
      interrupt_id: pendingInput.interrupt_id,
      resume_payload: text,
    }));

    setPendingInput(null);
  }, [pendingInput, setProseAndFragment]);

  const undoTurn = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    if (invocationHistory.length === 0) return;

    const lastInvocation = invocationHistory[invocationHistory.length - 1];

    setIsTyping(true);
    setProseAndFragment('system', `\n\n**[System]**: Initiating timeline rewind...\n\n`);

    wsRef.current.send(JSON.stringify({
      action: 'undo',
      invocation_id: lastInvocation,
    }));
  }, [invocationHistory, setProseAndFragment]);

  const rewriteTurn = useCallback((instruction: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    if (invocationHistory.length === 0) return;

    const lastInvocation = invocationHistory[invocationHistory.length - 1];

    setIsTyping(true);
    setProseAndFragment('system', `\n\n**[System]**: Requesting rewrite constraint: "${instruction}"...\n\n`);

    wsRef.current.send(JSON.stringify({
      action: 'rewrite',
      invocation_id: lastInvocation,
      instruction: instruction,
    }));
  }, [invocationHistory, setProseAndFragment]);

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
    sendChoice,
    submitInput,
    undoTurn,
    rewriteTurn,
    canUndo: invocationHistory.length > 0,
  };
}
