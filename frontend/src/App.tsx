import { useEffect, useState } from 'react';
import StoryView from './components/StoryView';
import SetupWizard from './components/SetupWizard';
import HomeScreen from './components/HomeScreen';
import { useStory } from './hooks/useStory';

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8001';

type SelectedSession = { id: string; isResumed: boolean };

function App() {
  const [selectedSession, setSelectedSession] = useState<SelectedSession | null>(null);
  const story = useStory(selectedSession?.id ?? null, selectedSession?.isResumed ?? false);

  // Listen for session-not-found from useStory: backend reported the
  // story_id we held no longer exists in the DB. Drop selectedSession
  // so we render the HomeScreen instead of staring at a broken WS.
  useEffect(() => {
    const onGone = () => setSelectedSession(null);
    window.addEventListener('fable:session-not-found', onGone);
    return () => window.removeEventListener('fable:session-not-found', onGone);
  }, []);

  const handleNewStory = async () => {
    const res = await fetch(`${API_BASE}/stories`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: 'local_tester' }),
    });
    const data = await res.json();
    setSelectedSession({ id: data.session_id, isResumed: false });
  };

  const handleContinue = (sessionId: string) => {
    setSelectedSession({ id: sessionId, isResumed: true });
  };

  if (!selectedSession) {
    return <HomeScreen onNewStory={handleNewStory} onContinue={handleContinue} />;
  }

  if (!story.setupComplete && !selectedSession?.isResumed) {
    return (
      <SetupWizard
        pendingInput={story.pendingInput}
        submitInput={story.submitInput}
        isConnected={story.isConnected}
        isResearching={story.isResearching}
        loreUpdates={story.loreUpdates}
      />
    );
  }

  return <StoryView story={story} onBack={() => setSelectedSession(null)} />;
}

export default App;
