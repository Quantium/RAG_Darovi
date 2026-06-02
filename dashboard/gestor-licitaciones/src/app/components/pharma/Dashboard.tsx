import { Link } from 'react-router';
import { licitaciones, padrones } from '../../data/pharmaData';
import { EstatusLicitacion } from '../../types-pharma';
import {
  AlertTriangle,
  Clock,
  TrendingUp,
  FileText,
  Bot,
  Database,
  FileCheck,
  MessageSquare,
  Printer,
  ChevronRight,
  Calendar,
  Building2,
} from 'lucide-react';

const estatusColors: Record<EstatusLicitacion, string> = {
  Identificación: 'bg-slate-100 text-slate-700 border-slate-300',
  'Análisis de Factibilidad': 'bg-blue-100 text-blue-700 border-blue-300',
  'Armado de Propuestas': 'bg-yellow-100 text-yellow-700 border-yellow-300',
  Presentación: 'bg-orange-100 text-orange-700 border-orange-300',
  Fallo: 'bg-green-100 text-green-700 border-green-300',
};

const estatusOrder: EstatusLicitacion[] = [
  'Identificación',
  'Análisis de Factibilidad',
  'Armado de Propuestas',
  'Presentación',
  'Fallo',
];

export function Dashboard() {
  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('es-MX', {
      style: 'currency',
      currency: 'MXN',
      minimumFractionDigits: 0,
    }).format(amount);
  };

  const formatDate = (date: Date) => {
    return new Intl.DateTimeFormat('es-MX', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    }).format(date);
  };

  const getDaysRemaining = (fechaLimite: Date) => {
    const now = new Date();
    const diffTime = fechaLimite.getTime() - now.getTime();
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    return diffDays;
  };

  const licitacionesActivas = licitaciones.filter(l => l.estatus !== 'Fallo').length;
  const totalAlertas = licitaciones.reduce((sum, l) => sum + l.alertas, 0);
  const valorTotalActivo = licitaciones
    .filter(l => l.estatus !== 'Fallo')
    .reduce((sum, l) => sum + l.valorEstimado, 0);

  const licitacionesPorEstatus = estatusOrder.reduce((acc, estatus) => {
    acc[estatus] = licitaciones.filter(l => l.estatus === estatus);
    return acc;
  }, {} as Record<EstatusLicitacion, typeof licitaciones>);

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Dashboard de Licitaciones</h2>
        <p className="text-slate-600 mt-1">Vista general de procesos activos y padrones</p>
      </div>

      <div className="grid grid-cols-4 gap-6">
        <div className="bg-white rounded-xl border border-slate-200 py-7 px-7 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600">Licitaciones Activas</p>
              <p className="text-3xl font-bold text-slate-900 mt-1">{licitacionesActivas}</p>
              <p className="text-xs text-slate-500 mt-2">De {licitaciones.length} totales</p>
            </div>
            <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
              <FileText className="w-6 h-6 text-blue-600" />
            </div>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-red-200 py-7 px-7 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600">Alertas Críticas</p>
              <p className="text-3xl font-bold text-red-600 mt-1">{totalAlertas}</p>
              <p className="text-xs text-red-500 mt-2">Requieren atención inmediata</p>
            </div>
            <div className="w-12 h-12 bg-red-100 rounded-lg flex items-center justify-center">
              <AlertTriangle className="w-6 h-6 text-red-600" />
            </div>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-slate-200 py-7 px-7 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600">Valor Total Activo</p>
              <p className="text-2xl font-bold text-slate-900 mt-1">{formatCurrency(valorTotalActivo)}</p>
              <p className="text-xs text-green-600 mt-2 flex items-center gap-1">
                <TrendingUp className="w-3 h-3" />
                En proceso de captura
              </p>
            </div>
            <div className="w-12 h-12 bg-green-100 rounded-lg flex items-center justify-center">
              <TrendingUp className="w-6 h-6 text-green-600" />
            </div>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-slate-200 py-7 px-7 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600">Próximo Cierre</p>
              <p className="text-lg font-bold text-orange-600 mt-1">
                {getDaysRemaining(
                  licitaciones
                    .filter(l => l.estatus !== 'Fallo')
                    .sort((a, b) => a.fechaLimite.getTime() - b.fechaLimite.getTime())[0]?.fechaLimite
                )}{' '}
                días
              </p>
              <p className="text-xs text-slate-500 mt-2">
                {licitaciones.filter(l => l.estatus !== 'Fallo').sort((a, b) => a.fechaLimite.getTime() - b.fechaLimite.getTime())[0]?.numeroProcedimiento}
              </p>
            </div>
            <div className="w-12 h-12 bg-orange-100 rounded-lg flex items-center justify-center">
              <Clock className="w-6 h-6 text-orange-600" />
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-8">
        <div className="col-span-9">
          <div className="bg-white rounded-xl border border-slate-200 py-7 px-7 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900 mb-5">Kanban de Licitaciones</h3>

            <div className="flex gap-5 overflow-x-auto pb-4">
              {estatusOrder.map(estatus => (
                <div key={estatus} className="flex-shrink-0 w-80">
                  <div className={`rounded-lg border-2 px-3 py-2 mb-3 ${estatusColors[estatus]}`}>
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-semibold">{estatus}</span>
                      <span className="text-xs font-bold">{licitacionesPorEstatus[estatus].length}</span>
                    </div>
                  </div>

                  <div className="space-y-3 max-h-[600px] overflow-y-auto pr-2">
                    {licitacionesPorEstatus[estatus].map(licitacion => {
                      const daysRemaining = getDaysRemaining(licitacion.fechaLimite);
                      const isUrgent = daysRemaining <= 3;

                      return (
                        <div
                          key={licitacion.id}
                          className="bg-white border border-slate-200 rounded-lg py-5 px-5 hover:shadow-md transition-shadow cursor-pointer"
                        >
                          <div className="flex items-start justify-between mb-2">
                            <div className="flex-1">
                              <p className="text-xs font-mono text-blue-600 font-semibold">
                                {licitacion.numeroProcedimiento}
                              </p>
                              <p className="text-sm font-medium text-slate-900 mt-1 line-clamp-2">
                                {licitacion.descripcion}
                              </p>
                            </div>
                            {licitacion.alertas > 0 && (
                              <div className="flex items-center gap-1 px-2 py-1 bg-red-100 text-red-700 rounded-full text-xs font-semibold ml-2">
                                <AlertTriangle className="w-3 h-3" />
                                {licitacion.alertas}
                              </div>
                            )}
                          </div>

                          <div className="flex items-center gap-2 text-xs text-slate-600 mb-3">
                            <Building2 className="w-3 h-3" />
                            <span className="line-clamp-1">{licitacion.dependencia}</span>
                          </div>

                          <div className="flex items-center justify-between text-xs mb-3">
                            <span className={`font-medium ${isUrgent ? 'text-red-600' : 'text-slate-600'}`}>
                              <Clock className="w-3 h-3 inline mr-1" />
                              {daysRemaining > 0 ? `${daysRemaining}d restantes` : 'VENCIDO'}
                            </span>
                            <span className="text-slate-500">{formatDate(licitacion.fechaLimite)}</span>
                          </div>

                          <div className="flex items-center justify-between text-xs text-slate-600 mb-3">
                            <span>{formatCurrency(licitacion.valorEstimado)}</span>
                            <span className="flex items-center gap-1">
                              <FileText className="w-3 h-3" />
                              {licitacion.documentosCount} docs
                            </span>
                          </div>

                          <div className="flex gap-1 pt-3 border-t border-slate-100">
                            <Link
                              to={`/expediente/${licitacion.id}`}
                              className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 bg-blue-50 text-blue-700 hover:bg-blue-100 rounded text-xs font-medium transition-colors"
                            >
                              <FileText className="w-3 h-3" />
                              Expediente
                            </Link>
                            <Link
                              to={`/asistente-ia/${licitacion.id}`}
                              className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 bg-purple-50 text-purple-700 hover:bg-purple-100 rounded text-xs font-medium transition-colors"
                            >
                              <Bot className="w-3 h-3" />
                              IA
                            </Link>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="col-span-3">
          <div className="bg-white rounded-xl border border-slate-200 py-7 px-7 shadow-sm">
            <div className="flex items-center justify-between mb-5">
              <h3 className="text-lg font-semibold text-slate-900">Padrones Activos</h3>
              <span className="text-xs font-semibold text-blue-600">{padrones.filter(p => p.estatus !== 'Completado').length} en proceso</span>
            </div>

            <div className="space-y-4">
              {padrones.map(padron => {
                const colorMap = {
                  'En proceso': 'border-blue-300 bg-blue-50',
                  Pendiente: 'border-slate-300 bg-slate-50',
                  Completado: 'border-green-300 bg-green-50',
                  Observaciones: 'border-orange-300 bg-orange-50',
                };

                const progressColor =
                  padron.progreso === 100 ? 'bg-green-500' : padron.progreso > 50 ? 'bg-blue-500' : 'bg-orange-500';

                return (
                  <div key={padron.id} className={`border-l-4 ${colorMap[padron.estatus]} rounded-r-lg py-4 px-4`}>
                    <div className="flex items-start justify-between mb-2">
                      <div>
                        <p className="text-sm font-semibold text-slate-900">{padron.empresa}</p>
                        <p className="text-xs text-slate-600 mt-0.5">{padron.dependencia}</p>
                      </div>
                      <span className="text-xs font-medium text-slate-500">{padron.tiempoEstimado}</span>
                    </div>

                    <div className="mt-3">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs text-slate-600">Progreso</span>
                        <span className="text-xs font-semibold text-slate-900">{padron.progreso}%</span>
                      </div>
                      <div className="w-full bg-slate-200 rounded-full h-1.5">
                        <div className={`h-1.5 rounded-full ${progressColor}`} style={{ width: `${padron.progreso}%` }}></div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            <button className="w-full mt-4 flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium">
              <span>Nuevo Padrón</span>
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>

          <div className="bg-gradient-to-br from-purple-600 to-purple-800 rounded-xl py-6 px-6 shadow-lg mt-6 text-white">
            <h3 className="text-lg font-semibold mb-3">Accesos Rápidos</h3>
            <div className="space-y-2">
              <button className="w-full flex items-center gap-3 px-4 py-3 bg-white/10 hover:bg-white/20 rounded-lg transition-colors text-sm">
                <Database className="w-4 h-4" />
                Homologación de Catálogos
              </button>
              <button className="w-full flex items-center gap-3 px-4 py-3 bg-white/10 hover:bg-white/20 rounded-lg transition-colors text-sm">
                <FileCheck className="w-4 h-4" />
                Minimáster y Cartas
              </button>
              <button className="w-full flex items-center gap-3 px-4 py-3 bg-white/10 hover:bg-white/20 rounded-lg transition-colors text-sm">
                <MessageSquare className="w-4 h-4" />
                Juntas de Aclaraciones
              </button>
              <button className="w-full flex items-center gap-3 px-4 py-3 bg-white/10 hover:bg-white/20 rounded-lg transition-colors text-sm">
                <Printer className="w-4 h-4" />
                Control de Producción
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
