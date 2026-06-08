import { ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  TrendingUp,
  Package,
  DollarSign,
  Settings,
  Brain,
  Cpu,
  Sparkles,
  Database,
} from 'lucide-react';
import { cn } from '../utils/cn';
import { Logo } from './Logo';
import { AIGradientBg } from './AIGradientBg';

interface LayoutProps {
  children: ReactNode;
}

const navigation = [
  { name: 'Missions', href: '/', icon: Brain },
  { name: 'Dashboard', href: '/dashboard', icon: LayoutDashboard },
  { name: 'Opportunities', href: '/opportunities', icon: TrendingUp },
  { name: 'Products', href: '/products', icon: Package },
  { name: 'Revenue', href: '/revenue', icon: DollarSign },
  { name: 'MCP & Skills', href: '/mcp-skills', icon: Cpu },
  { name: 'Auto-Improve', href: '/improvement', icon: Sparkles },
  { name: 'Memory', href: '/memory', icon: Database },
  { name: 'Settings', href: '/settings', icon: Settings },
];

export const Layout = ({ children }: LayoutProps) => {
  const location = useLocation();

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 transition-colors relative">
      <AIGradientBg />
      
      {/* Sidebar — hidden below md (768px) ; restores baseline mobile usability.
           A hamburger toggle is a TODO ; this fix removes the immediate
           fullscreen-coverage bug. */}
      <aside className="hidden md:block fixed inset-y-0 left-0 w-64 bg-white/80 dark:bg-gray-800/80 backdrop-blur-xl border-r border-gray-200 dark:border-gray-700 transition-colors z-40">
        <div className="flex flex-col h-full">
          {/* Logo */}
          <div className="p-6 border-b border-gray-200 dark:border-gray-700">
            <Logo size="sm" showText={true} animated={true} />
          </div>

          {/* Navigation */}
          <nav className="flex-1 px-4 py-6 space-y-1">
            {navigation.map((item) => {
              const isActive = location.pathname === item.href;
              return (
                <Link
                  key={item.name}
                  to={item.href}
                  className={cn(
                    'flex items-center gap-3 px-4 py-3 rounded-lg transition-all duration-200',
                    isActive
                      ? 'bg-primary-50 dark:bg-primary-900/20 text-primary-600 dark:text-primary-400'
                      : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                  )}
                >
                  <item.icon className="w-5 h-5" />
                  <span className="font-medium">{item.name}</span>
                </Link>
              );
            })}
          </nav>

          {/* Footer */}
          <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-700">
            <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
              <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
              <span>System Online</span>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="md:pl-64">
        <div className="px-4 md:px-8 py-6">{children}</div>
      </main>
    </div>
  );
};
