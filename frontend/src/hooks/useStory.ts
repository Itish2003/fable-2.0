import { useState, useEffect, useRef, useCallback } from 'react';

const API_BASE = 'http://localhost:8001';
const WS_BASE = 'ws://localhost:8001/ws/story';

export type RequestInputData = {
  interrupt_id: string;
  message: string;
};

export type LoreStatus = {
  id: number;
  message: string;
  timestamp: string;
};

export function useStory() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [isResearching, setIsResearching] = useState(false);
  
  const [prose, setProse] = useState<string>('');
  const [pendingInput, setPendingInput] = useState<RequestInputData | null>(null);
  const [choices, setChoices] = useState<string[]>([]);
  const [loreUpdates, setLoreUpdates] = useState<LoreStatus[]>([]);
  const [setupComplete, setSetupComplete] = useState(false);
  const [invocationHistory, setInvocationHistory] = useState<string[]>([]);
  
  const wsRef = useRef<WebSocket | null>(null);
  const loreIdRef = useRef(0);

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
        console.error("Failed to create session:", err);
      }
    }
    initSession();
  }, []);

  // 2. Manage WebSocket Connection
  useEffect(() => {
    if (!sessionId) return;

    const ws = new WebSocket(`${WS_BASE}/${sessionId}`);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("WebSocket connected.");
      setIsConnected(true);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        switch (data.type) {
          case 'text_delta':
            setIsTyping(true);
            setProse(prev => prev + data.text);
            // If we are getting text deltas, we are definitely done with setup
            setSetupComplete(true);
            break;
            
          case 'request_input':
            setIsTyping(false);
            setIsResearching(false);
            setPendingInput({
              interrupt_id: data.interrupt_id,
              message: data.message
            });
            
            if (data.interrupt_id === 'user_choice_selection') {
                try {
                    const parsed = JSON.parse(data.message);
                    setChoices(parsed.choices || []);
                } catch (e) {
                    setChoices([]);
                }
            } else {
                setChoices([]);
            }
            
            // Ensure prose has a clean break before the prompt
            if (data.interrupt_id !== 'setup_lore_dump' && data.interrupt_id !== 'setup_configuration' && data.interrupt_id !== 'setup_world_primer' && data.interrupt_id !== 'user_choice_selection') {
                setProse(prev => prev + `\n\n> *${data.message}*\n\n`);
            }
            break;
            
          case 'status':
            loreIdRef.current += 1;
            setLoreUpdates(prev => [
            { id: loreIdRef.current, message: data.message, timestamp: new Date().toLocaleTimeString() },
            ...prev
            ]);
            break;
            
          case 'turn_complete':
            setIsTyping(false);
            setProse(prev => prev + '\n\n');
            if (data.invocation_id) {
                setInvocationHistory(prev => [...prev, data.invocation_id]);
            }
            break;
            
          case 'undo_complete':
            setIsTyping(false);
            setProse(prev => prev + '\n\n**[System]**: Timeline rewind successful. Awaiting new input...\n\n');
            // Remove the last invocation since it was undone
            setInvocationHistory(prev => prev.slice(0, -1));
            setPendingInput(null);
            setChoices([]);
            break;
            
          case 'error':
            setIsTyping(false);
            setProse(prev => prev + `\n\n[System Error]: ${data.message}\n\n`);
            break;
        }
      } catch (e) {
        console.error("Error parsing WS message:", e);
      }
    };

    ws.onclose = () => {
      console.log("WebSocket disconnected.");
      setIsConnected(false);
    };

    return () => {
      ws.close();
    };
  }, [sessionId]);

  // 3. User Actions
  const sendChoice = useCallback((message: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    
    setProse(prev => prev + `\n**[Action]**: ${message}\n\n`);
    setIsTyping(true);
    
    wsRef.current.send(JSON.stringify({ message }));
  }, []);

  const submitInput = useCallback((text: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || !pendingInput) return;
    
    if (pendingInput.interrupt_id !== 'setup_lore_dump' && pendingInput.interrupt_id !== 'setup_configuration' && pendingInput.interrupt_id !== 'setup_world_primer') {
        setProse(prev => prev + `**[Reply]**: ${text}\n\n`);
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
      resume_payload: text
    }));
    
    setPendingInput(null);
  }, [pendingInput]);

  const undoTurn = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    if (invocationHistory.length === 0) return;
    
    // We want to rewind BEFORE the last turn
    const lastInvocation = invocationHistory[invocationHistory.length - 1];
    
    setIsTyping(true);
    setProse(prev => prev + `\n\n**[System]**: Initiating timeline rewind...\n\n`);
    
    wsRef.current.send(JSON.stringify({
      action: 'undo',
      invocation_id: lastInvocation
    }));
  }, [invocationHistory]);

  return {
    isConnected,
    isTyping,
    isResearching,
    prose,
    pendingInput,
    choices,
    loreUpdates,
    setupComplete,
    sendChoice,
    submitInput,
    undoTurn,
    canUndo: invocationHistory.length > 0
  };
}