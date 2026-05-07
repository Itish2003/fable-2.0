import StoryView from './components/StoryView';
import SetupWizard from './components/SetupWizard';
import { useStory } from './hooks/useStory';

function App() {
  const story = useStory();

  if (!story.setupComplete) {
    return <SetupWizard pendingInput={story.pendingInput} submitInput={story.submitInput} isConnected={story.isConnected} isResearching={story.isResearching} />;
  }

  return (
    <StoryView story={story} />
  )
}

export default App

