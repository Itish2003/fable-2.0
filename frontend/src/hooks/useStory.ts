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
  
  const [prose, setProse] = useState<string>('');
  const [pendingInput, setPendingInput] = useState<RequestInputData | null>(null);
  const [loreUpdates, setLoreUpdates] = useState<LoreStatus[]>([]);
  
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
            break;
            
          case 'request_input':
            setIsTyping(false);
            setPendingInput({
              interrupt_id: data.interrupt_id,
              message: data.message
            });
            // Ensure prose has a clean break before the prompt
            setProse(prev => prev + `\n\n> *${data.message}*\n\n`);
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
    
    setProse(prev => prev + `**[Reply]**: ${text}\n\n`);
    setIsTyping(true);
    
    wsRef.current.send(JSON.stringify({
      interrupt_id: pendingInput.interrupt_id,
      resume_payload: text
    }));
    
    setPendingInput(null);
  }, [pendingInput]);

  return {
    isConnected,
    isTyping,
    prose,
    pendingInput,
    loreUpdates,
    sendChoice,
    submitInput
  };
}