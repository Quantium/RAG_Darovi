import { useState } from 'react';
import { Link } from 'react-router';
import { licitaciones } from '../data/mockData';
import { EstadoLicitacion } from '../types';
import { Edit, Copy, FileBarChart, AlertCircle, Calendar, DollarSign, Users } from 'lucide-react';

const estadoColors: Record<EstadoLicitacion, string> = {
  'Borrador': 'bg-slate-100 text-slate-700',
  'Publicada': 'bg-green-100 text-green-700',
  'En Evaluación': 'bg-yellow-100 text-yellow-700',
  'Cerrada': 'bg-red-100 text-red-700',
  'Adjudicada': 'bg-blue-100 text-blue-700',
};

export function LicitacionesListado() {
  const [filtroEstado, setFiltroEstado] = useState<EstadoLicitacion | 'Todas'>('Todas');

  const licitacionesFiltradas = filtroEstado === 'Todas'
    ? licitaciones
    : licitaciones.filter(l => l.estado === filtroEstado);

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('es-CL', {
      style: 'currency',
      currency: 'CLP',
      minimumFractionDigits: 0,
    }).format(amount);
  };

  const formatDate = (date: Date) => {
    return new Intl.DateTimeFormat('es-CL', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    }).format(date);
  };

  const getDaysRemaining = (fechaCierre: Date) => {
    const today = new Date();
    const diffTime = fechaCierre.getTime() - today.getTime();
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    return diffDays;
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-slate-900">Licitaciones</h2>
          <p className="text-slate-600 mt-1">Gestiona todos los procesos de licitación</p>
        </div>

        <div className="flex items-center gap-3">
          <div className="bg-white rounded-lg border border-slate-200 px-4 py-2">
            <span className="text-sm text-slate-600">Total: </span>
            <span className="font-semibold text-slate-900">{licitacionesFiltradas.length}</span>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 p-4">
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setFiltroEstado('Todas')}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              filtroEstado === 'Todas'
                ? 'bg-blue-600 text-white'
                : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
            }`}
          >
            Todas
          </button>
          {(['Borrador', 'Publicada', 'En Evaluación', 'Cerrada', 'Adjudicada'] as EstadoLicitacion[]).map(estado => (
            <button
              key={estado}
              onClick={() => setFiltroEstado(estado)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                filtroEstado === estado
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
              }`}
            >
              {estado}
            </button>
          ))}
        </div>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">ID / Licitación</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Estado</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Progreso</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Presupuesto</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Ofertas</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Cierre</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {licitacionesFiltradas.map((licitacion) => {
                const daysRemaining = getDaysRemaining(licitacion.fechaCierre);
                const isUrgent = daysRemaining <= 7 || licitacion.urgente;

                return (
                  <tr key={licitacion.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-6 py-4">
                      <div className="flex items-start gap-3">
                        {isUrgent && (
                          <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
                        )}
                        <div>
                          <Link
                            to={`/licitaciones/${licitacion.id}/ofertas`}
                            className="text-blue-600 hover:text-blue-800 font-medium"
                          >
                            {licitacion.id}
                          </Link>
                          <p className="text-sm text-slate-900 mt-1 max-w-md">{licitacion.titulo}</p>
                          <p className="text-xs text-slate-500 mt-1">{licitacion.descripcion}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-medium ${estadoColors[licitacion.estado]}`}>
                        {licitacion.estado}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="w-32">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs text-slate-600">{licitacion.progreso}%</span>
                          <span className="text-xs text-slate-500">
                            {daysRemaining > 0 ? `${daysRemaining}d restantes` : 'Vencida'}
                          </span>
                        </div>
                        <div className="w-full bg-slate-200 rounded-full h-2">
                          <div
                            className={`h-2 rounded-full transition-all ${
                              isUrgent ? 'bg-red-500' : licitacion.progreso >= 80 ? 'bg-yellow-500' : 'bg-green-500'
                            }`}
                            style={{ width: `${licitacion.progreso}%` }}
                          ></div>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <DollarSign className="w-4 h-4 text-slate-400" />
                        <span className="text-sm font-medium text-slate-900">
                          {formatCurrency(licitacion.presupuesto)}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <Users className="w-4 h-4 text-slate-400" />
                        <span className="text-sm font-medium text-slate-900">{licitacion.ofertas}</span>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <Calendar className="w-4 h-4 text-slate-400" />
                        <span className="text-sm text-slate-600">{formatDate(licitacion.fechaCierre)}</span>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <button className="p-2 text-slate-600 hover:bg-slate-100 rounded-lg transition-colors" title="Editar">
                          <Edit className="w-4 h-4" />
                        </button>
                        <button className="p-2 text-slate-600 hover:bg-slate-100 rounded-lg transition-colors" title="Duplicar">
                          <Copy className="w-4 h-4" />
                        </button>
                        <Link
                          to={`/licitaciones/${licitacion.id}/ofertas`}
                          className="p-2 text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
                          title="Ver Ofertas"
                        >
                          <FileBarChart className="w-4 h-4" />
                        </Link>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
