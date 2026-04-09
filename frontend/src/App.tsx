import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { Layout } from './components/Layout';
import { Dashboard } from './pages/Dashboard';
import Missions from './pages/Missions';
import { Opportunities } from './pages/Opportunities';
import { Products } from './pages/Products';
import { Revenue } from './pages/Revenue';
import { Settings } from './pages/Settings';

function App() {
  return (
    <Router>
      <Layout>
        <Routes>
          <Route path="/" element={<Missions />} />
          <Route path="/missions" element={<Missions />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/opportunities" element={<Opportunities />} />
          <Route path="/products" element={<Products />} />
          <Route path="/revenue" element={<Revenue />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </Layout>
    </Router>
  );
}

export default App;
