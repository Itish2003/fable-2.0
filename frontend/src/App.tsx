import { useEffect, useState } from 'react';
import StoryView from './components/StoryView';
import SetupWizard from './components/SetupWizard';
import HomeScreen from './components/HomeScreen';
import { useStory } from './hooks/useStory';

// No build-time override (production build, same-origin deploy): relative
// paths resolve against whatever origin serves this bundle.
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

type SelectedSession = { id: string; isResumed: boolean };

// Deep link from the agent's live-session pointer (?session=<id>): open
// that story directly, same as clicking "Continue" on it from the home
// screen -- skips the home screen and (via isResumed: true, same as
// handleContinue below) the setup wizard, straight to StoryView so a
// visitor arriving from the chat sees the actual current state.
function sessionFromUrl(): SelectedSession | null {
  const id = new URLSearchParams(window.location.search).get('session');
  return id ? { id, isResumed: true } : null;
}

function App() {
  const [selectedSession, setSelectedSession] = useState<SelectedSession | null>(sessionFromUrl);
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
