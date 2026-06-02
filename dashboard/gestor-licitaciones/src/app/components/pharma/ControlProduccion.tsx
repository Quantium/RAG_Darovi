import { useParams, Link } from 'react-router';
import { licitaciones, tareasProduccion } from '../../data/pharmaData';
import {
  ArrowLeft,
  Printer,
  Hash,
  Edit,
  ScanLine,
  Package,
  CheckCircle,
  AlertTriangle,
  Play,
  Pause,
} from 'lucide-react';

export function ControlProduccion() {
  const { id } = useParams();
  const licitacion = licitaciones.find(l => l.id === id);
  const tareas = tareasProduccion.filter(t => t.licitacionId === id);

  if (!licitacion) {
    return (
      <div className="text-center py-12">
        <p className="text-slate-600">Licitación no encontrada</p>
      </div>
    );
  }

  const tareasCompletadas = tareas.filter(t => t.progreso === 100).length;
  const totalHojas = tareas[0]?.totalHojas || 0;

  const tipoIcons = {
    Impresión: Printer,
    Foliado: Hash,
    Rúbrica: Edit,
    Escaneo: ScanLine,
    Empaquetado: Package,
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/" className="p-2 hover:bg-slate-100 rounded-lg transition-colors">
            <ArrowLeft className="w-5 h-5 text-slate-600" />
          </Link>
          <div>
            <h2 className="text-2xl font-bold text-slate-900">Control de Producción Física</h2>
            <div className="flex items-center gap-3 mt-1">
              <p className="text-sm font-mono text-blue-600 font-semibold">{licitacion.numeroProcedimiento}</p>
              <span className="text-slate-400">•</span>
              <p className="text-sm text-slate-600">Gestión de armado e impresión</p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-50 transition-colors">
            <Hash className="w-4 h-4" />
            Generar Etiquetas de Foliado
          </button>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-4">
        <div className="bg-white rounded-xl border border-slate-200 py-6 px-6">
          <p className="text-sm text-slate-600">Total Hojas</p>
          <p className="text-3xl font-bold text-slate-900 mt-1">
            {totalHojas.toLocaleString('es-MX')}
          </p>
        </div>
        <div className="bg-white rounded-xl border border-blue-200 py-6 px-6">
          <p className="text-sm text-slate-600">Tareas Completadas</p>
          <p className="text-3xl font-bold text-blue-600 mt-1">
            {tareasCompletadas}/{tareas.length}
          </p>
        </div>
        <div className="bg-white rounded-xl border border-green-200 py-6 px-6">
          <p className="text-sm text-slate-600">Verificadas</p>
          <p className="text-3xl font-bold text-green-600 mt-1">
            {tareas.filter(t => t.verificado).length}
          </p>
        </div>
        <div className="bg-white rounded-xl border border-orange-200 py-6 px-6">
          <p className="text-sm text-slate-600">Pendientes Verificación</p>
          <p className="text-3xl font-bold text-orange-600 mt-1">
            {tareas.filter(t => !t.verificado).length}
          </p>
        </div>
      </div>

      <div className="bg-red-50 border-l-4 border-red-500 py-4 px-4 rounded-r-lg">
        <div className="flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
          <div>
            <h3 className="text-sm font-semibold text-red-900">Validación Humana Obligatoria</h3>
            <p className="text-sm text-red-800 mt-1">
              Antes de cargar la versión final al sistema, un supervisor debe confirmar físicamente que no falten
              hojas críticas (como registros sanitarios). Este paso previene incidentes de exclusión generados
              por fallas electrónicas del escáner.
            </p>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="bg-slate-50 px-6 py-4 border-b border-slate-200">
          <h3 className="text-lg font-semibold text-slate-900">Pipeline de Producción</h3>
          <p className="text-sm text-slate-600 mt-1">Seguimiento paso a paso del proceso físico</p>
        </div>

        <div className="p-6 space-y-4">
          {tareas.map((tarea, index) => {
            const Icon = tipoIcons[tarea.tipo];
            const isCompleto = tarea.progreso === 100;
            const isEnProceso = tarea.progreso > 0 && tarea.progreso < 100;

            return (
              <div key={tarea.id} className="relative">
                {index < tareas.length - 1 && (
                  <div
                    className={`absolute left-6 top-14 w-0.5 h-12 ${
                      isCompleto ? 'bg-green-300' : 'bg-slate-200'
                    }`}
                  ></div>
                )}

                <div
                  className={`border-2 rounded-xl py-6 px-6 transition-all ${
                    isCompleto
                      ? 'border-green-300 bg-green-50'
                      : isEnProceso
                      ? 'border-blue-300 bg-blue-50'
                      : 'border-slate-200 bg-white'
                  }`}
                >
                  <div className="flex items-start gap-4">
                    <div
                      className={`w-12 h-12 rounded-xl flex items-center justify-center ${
                        isCompleto
                          ? 'bg-green-600 text-white'
                          : isEnProceso
                          ? 'bg-blue-600 text-white'
                          : 'bg-slate-200 text-slate-600'
                      }`}
                    >
                      <Icon className="w-6 h-6" />
                    </div>

                    <div className="flex-1">
                      <div className="flex items-center justify-between mb-2">
                        <div>
                          <h4 className="text-lg font-semibold text-slate-900">{tarea.tipo}</h4>
                          <p className="text-sm text-slate-600">
                            {tarea.totalHojas.toLocaleString('es-MX')} hojas • Responsable:{' '}
                            <span className="font-medium text-slate-900">{tarea.responsable}</span>
                          </p>
                        </div>

                        <div className="flex items-center gap-3">
                          {tarea.verificado ? (
                            <div className="flex items-center gap-2 px-3 py-1 bg-green-100 text-green-700 rounded-full text-sm font-medium">
                              <CheckCircle className="w-4 h-4" />
                              Verificado
                            </div>
                          ) : (
                            <div className="flex items-center gap-2 px-3 py-1 bg-orange-100 text-orange-700 rounded-full text-sm font-medium">
                              <AlertTriangle className="w-4 h-4" />
                              Sin Verificar
                            </div>
                          )}

                          {isEnProceso && (
                            <button className="p-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
                              <Pause className="w-4 h-4" />
                            </button>
                          )}
                          {!isCompleto && !isEnProceso && (
                            <button className="p-2 bg-green-600 text-white rounded-lg hover:bg-green-700">
                              <Play className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                      </div>

                      <div className="mt-4">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-sm text-slate-600">Progreso</span>
                          <span className="text-sm font-semibold text-slate-900">{tarea.progreso}%</span>
                        </div>
                        <div className="w-full bg-slate-200 rounded-full h-3">
                          <div
                            className={`h-3 rounded-full transition-all ${
                              isCompleto ? 'bg-green-500' : isEnProceso ? 'bg-blue-500' : 'bg-slate-400'
                            }`}
                            style={{ width: `${tarea.progreso}%` }}
                          ></div>
                        </div>
                      </div>

                      {tarea.observaciones && (
                        <div className="mt-4 py-3 px-3 bg-red-100 border border-red-300 rounded-lg">
                          <p className="text-sm font-semibold text-red-900 mb-1">⚠️ OBSERVACIÓN CRÍTICA:</p>
                          <p className="text-sm text-red-800">{tarea.observaciones}</p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-6">
        <div className="bg-white rounded-xl border border-slate-200 py-6 px-6 shadow-sm">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 bg-purple-100 rounded-lg flex items-center justify-center">
              <Hash className="w-5 h-5 text-purple-600" />
            </div>
            <h3 className="text-lg font-semibold text-slate-900">Gestor de Foliado</h3>
          </div>

          <p className="text-sm text-slate-700 mb-4">
            Conectado a impresoras para generar automáticamente etiquetas consecutivas necesarias para el
            foliado físico de las carpetas.
          </p>

          <div className="space-y-3">
            <div>
              <label className="text-xs font-semibold text-slate-700 uppercase mb-2 block">
                Rango de Folios
              </label>
              <div className="grid grid-cols-2 gap-2">
                <input
                  type="number"
                  placeholder="Desde"
                  defaultValue={1}
                  className="px-3 py-2 border border-slate-300 rounded-lg text-sm"
                />
                <input
                  type="number"
                  placeholder="Hasta"
                  defaultValue={totalHojas}
                  className="px-3 py-2 border border-slate-300 rounded-lg text-sm"
                />
              </div>
            </div>

            <button className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 font-medium">
              <Printer className="w-4 h-4" />
              Imprimir Etiquetas
            </button>
          </div>
        </div>

        <div className="bg-slate-900 rounded-xl py-6 px-6 text-white">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 bg-white/20 rounded-lg flex items-center justify-center">
              <CheckCircle className="w-5 h-5 text-white" />
            </div>
            <h3 className="text-lg font-semibold">Checklist Final de Validación</h3>
          </div>

          <ul className="space-y-3 text-sm">
            <li className="flex items-start gap-3">
              <input type="checkbox" className="mt-1 w-4 h-4" />
              <span>Todas las hojas están numeradas consecutivamente sin saltos</span>
            </li>
            <li className="flex items-start gap-3">
              <input type="checkbox" className="mt-1 w-4 h-4" />
              <span>Los registros sanitarios están completos y legibles</span>
            </li>
            <li className="flex items-start gap-3">
              <input type="checkbox" className="mt-1 w-4 h-4" />
              <span>Todas las páginas tienen rúbrica en el margen inferior derecho</span>
            </li>
            <li className="flex items-start gap-3">
              <input type="checkbox" className="mt-1 w-4 h-4" />
              <span>El escaneo no omitió documentos críticos</span>
            </li>
            <li className="flex items-start gap-3">
              <input type="checkbox" className="mt-1 w-4 h-4" />
              <span>Los anexos firmados están en el orden correcto</span>
            </li>
          </ul>

          <button className="w-full mt-6 flex items-center justify-center gap-2 px-4 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 font-semibold">
            <CheckCircle className="w-5 h-5" />
            Aprobar para Carga Final
          </button>
        </div>
      </div>
    </div>
  );
}
