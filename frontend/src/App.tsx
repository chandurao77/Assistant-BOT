import { Header } from '@/components/Layout/Header';
import { ChatContainer } from '@/components/Chat/ChatContainer';
import { FeedbackDashboard } from '@/components/Admin/FeedbackDashboard';
import { LoginPage } from '@/components/Auth/LoginPage';
import { AuthProvider, useAuth } from '@/contexts/AuthContext';
import { useTheme } from '@/hooks/useTheme';
import { useState } from 'react';

function AppContent() {
  const { theme, toggleTheme } = useTheme();
  const { user, isLoading, logout } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [showDashboard, setShowDashboard] = useState(false);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gradient-to-br from-gray-50 via-blue-50/30 to-gray-100 dark:from-gray-900 dark:via-gray-900 dark:to-gray-950">
        <div className="w-14 h-14 mb-4">
          <img src="/assistant-bot-logo.svg" alt="Assistant Bot" className="w-14 h-14 animate-pulse" />
        </div>
        <div className="w-5 h-5 border-2 border-confluence-blue border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!user) {
    return <LoginPage />;
  }

  return (
    <div className="flex flex-col h-screen bg-gray-100 dark:bg-gray-900 overflow-hidden transition-colors">
      <Header theme={theme} onToggleTheme={toggleTheme} user={user} onLogout={logout} showDashboard={showDashboard} onToggleDashboard={isAdmin ? () => setShowDashboard(!showDashboard) : undefined} />
      <main className="flex-1 overflow-hidden">
        <div className="h-full bg-white dark:bg-gray-800">
          {showDashboard ? (
            <FeedbackDashboard onBack={() => setShowDashboard(false)} />
          ) : (
            <ChatContainer />
          )}
        </div>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}
