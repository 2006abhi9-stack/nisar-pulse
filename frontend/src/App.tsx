import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { TopCommandBar } from './components/TopCommandBar';
import { LiveMissionPage } from './pages/LiveMissionPage';
import { UploadPage } from './pages/UploadPage';
import { HistoryPage } from './pages/HistoryPage';
import { SettingsPage } from './pages/SettingsPage';

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <div className="w-screen h-screen flex flex-col bg-canvas-sand overflow-hidden font-sans">
        <TopCommandBar />
        <main className="flex-1 w-full overflow-hidden relative">
          <Routes>
            <Route path="/" element={<LiveMissionPage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
};

export default App;
