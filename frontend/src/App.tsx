import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/Layout';
import Missions from './pages/Missions';
import { Dashboard } from './pages/Dashboard';
import { Opportunities } from './pages/Opportunities';
import { Products } from './pages/Products';
import { Revenue } from './pages/Revenue';
import { Settings } from './pages/Settings';
import { McpSkills } from './pages/McpSkills';
import { ImprovementLoop } from './pages/ImprovementLoop';
import { MemoryMonitor } from './pages/MemoryMonitor';
import { MissionLogs } from './pages/MissionLogs';

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route path="/" element={<Layout><Missions /></Layout>} />
        <Route path="/dashboard" element={<Layout><Dashboard /></Layout>} />
        <Route path="/opportunities" element={<Layout><Opportunities /></Layout>} />
        <Route path="/products" element={<Layout><Products /></Layout>} />
        <Route path="/revenue" element={<Layout><Revenue /></Layout>} />
        <Route path="/settings" element={<Layout><Settings /></Layout>} />
        <Route path="/mcp-skills" element={<Layout><McpSkills /></Layout>} />
        <Route path="/improvement" element={<Layout><ImprovementLoop /></Layout>} />
        <Route path="/memory" element={<Layout><MemoryMonitor /></Layout>} />
        <Route path="/mission-logs" element={<Layout><MissionLogs /></Layout>} />
      </Routes>
    </Router>
  );
}

export default App;
