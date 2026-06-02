import { Outlet, Link, useLocation } from 'react-router';
import { LayoutDashboard, FileText, Bot, Database, FileCheck, MessageSquare, Printer, Bell, Search, FolderOpen } from 'lucide-react';
import { ChatFAB } from './ChatFAB';
import { useFuente, FuenteDatos } from '../../context/FuenteContext';

export function RootPharma() {
  const location = useLocation();
  const { fuenteSeleccionada, setFuenteSeleccionada } = useFuente();

  const isActive = (path: string) => {
    if (path === '/') return location.pathname === '/';
    return location.pathname.startsWith(path);
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-gradient-to-r from-blue-900 to-blue-700 text-white border-b border-blue-800 sticky top-0 z-50 shadow-lg">
        <div className="max-w-[1800px] mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-6">
              <div>
                <h1 className="text-xl font-bold">Gestor Licitaciones</h1>
              </div>

              <nav className="flex gap-1 ml-4">
                <Link
                  to="/"
                  className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                    isActive('/') && location.pathname === '/'
                      ? 'bg-white/20 text-white'
                      : 'text-blue-100 hover:bg-white/10'
                  }`}
                >
                  <LayoutDashboard className="w-4 h-4" />
                  Dashboard
                </Link>
                <a
                  href="http://localhost:9001/login"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors text-blue-100 hover:bg-white/10"
                >
                  <Database className="w-4 h-4" />
                  Archivos Minio
                </a>
              </nav>
            </div>

            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2 bg-white/10 border border-white/20 rounded-lg px-4 py-2">
                <FolderOpen className="w-4 h-4 text-blue-200" />
                <span className="text-xs text-blue-200">Fuente:</span>
                <select
                  value={fuenteSeleccionada}
                  onChange={(e) => setFuenteSeleccionada(e.target.value as FuenteDatos)}
                  className="bg-white/20 border border-white/30 text-white rounded px-3 py-1 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-white/40 cursor-pointer"
                >
                  <option value="Licitaciones" className="text-slate-900">📋 Licitaciones</option>
                  <option value="Laboratorios" className="text-slate-900">🧪 Laboratorios</option>
                  <option value="SSJAL" className="text-slate-900">🏥 SSJAL</option>
                </select>
              </div>

              <div className="relative">
                <Search className="w-4 h-4 text-blue-300 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="search"
                  placeholder="Buscar por número de procedimiento..."
                  className="w-80 pl-10 pr-4 py-2 bg-white/10 border border-white/20 text-white placeholder-blue-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-white/40 focus:bg-white/20"
                />
              </div>

              <button className="relative py-2 px-2 text-blue-100 hover:bg-white/10 rounded-lg">
                <Bell className="w-5 h-5" />
                <span className="absolute top-1 right-1 w-2.5 h-2.5 bg-red-500 rounded-full border-2 border-blue-900"></span>
              </button>

              <div className="flex items-center gap-2 px-3 py-2 bg-white/10 rounded-lg">
                <div className="w-8 h-8 rounded-full bg-white/20 flex items-center justify-center">
                  <span className="text-sm font-semibold">AD</span>
                </div>
                <div className="text-sm">
                  <p className="font-medium">Admin Darovi</p>
                  <p className="text-xs text-blue-200">Gerente de Licitaciones</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-[1800px] mx-auto px-8 py-8">
        <Outlet />
      </main>

      <ChatFAB />
    </div>
  );
}
