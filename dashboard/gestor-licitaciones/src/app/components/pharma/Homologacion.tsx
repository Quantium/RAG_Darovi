import { useParams, Link } from 'react-router';
import { licitaciones, catalogoItems } from '../../data/pharmaData';
import { ArrowLeft, AlertTriangle, CheckCircle, XCircle, Search, Download, Upload } from 'lucide-react';

export function Homologacion() {
  const { id } = useParams();
  const licitacion = licitaciones.find(l => l.id === id);

  if (!licitacion) {
    return (
      <div className="text-center py-12">
        <p className="text-slate-600">Licitación no encontrada</p>
      </div>
    );
  }

  const itemsValidados = catalogoItems.filter(i => i.validado).length;
  const itemsConProblemas = catalogoItems.filter(i => !i.validado).length;
  const porcentajeCompletado = Math.round((itemsValidados / catalogoItems.length) * 100);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/" className="p-2 hover:bg-slate-100 rounded-lg transition-colors">
            <ArrowLeft className="w-5 h-5 text-slate-600" />
          </Link>
          <div>
            <h2 className="text-2xl font-bold text-slate-900">Homologación de Catálogos</h2>
            <div className="flex items-center gap-3 mt-1">
              <p className="text-sm font-mono text-blue-600 font-semibold">{licitacion.numeroProcedimiento}</p>
              <span className="text-slate-400">•</span>
              <p className="text-sm text-slate-600">Cruce automático de claves</p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-50 transition-colors">
            <Upload className="w-4 h-4" />
            Importar Anexo Cliente
          </button>
          <button className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-50 transition-colors">
            <Download className="w-4 h-4" />
            Exportar Homologado
          </button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white rounded-xl border border-slate-200 py-6 px-6">
          <p className="text-sm text-slate-600">Total Items</p>
          <p className="text-3xl font-bold text-slate-900 mt-1">{catalogoItems.length}</p>
        </div>
        <div className="bg-white rounded-xl border border-green-200 py-6 px-6">
          <p className="text-sm text-slate-600">Validados</p>
          <p className="text-3xl font-bold text-green-600 mt-1">{itemsValidados}</p>
          <p className="text-xs text-green-600 mt-2">{porcentajeCompletado}% completado</p>
        </div>
        <div className="bg-white rounded-xl border border-red-200 py-6 px-6">
          <p className="text-sm text-slate-600">Requieren Revisión</p>
          <p className="text-3xl font-bold text-red-600 mt-1">{itemsConProblemas}</p>
        </div>
      </div>

      <div className="bg-red-50 border-l-4 border-red-500 py-4 px-4 rounded-r-lg">
        <div className="flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
          <div>
            <h3 className="text-sm font-semibold text-red-900">Validación Estricta Activada</h3>
            <p className="text-sm text-red-800 mt-1">
              El sistema detecta discrepancias de un solo carácter para evitar rechazos como el caso "Anacep" vs "Anacept".
              Revisa manualmente todos los items marcados en amarillo o rojo.
            </p>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="bg-slate-50 px-6 py-4 border-b border-slate-200">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-slate-900">Tabla de Cruce Automático</h3>
            <div className="relative">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="search"
                placeholder="Buscar por clave o descripción..."
                className="pl-10 pr-4 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-slate-100 border-b border-slate-200">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  Estado
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  Clave Cliente
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  Descripción Cliente
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  Coincidencia
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  Clave Darovi
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  Descripción Darovi
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  Acciones
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {catalogoItems.map((item) => {
                const getRowColor = () => {
                  if (!item.claveDarovi) return 'bg-red-50';
                  if (item.validado) return 'bg-green-50';
                  if (item.discrepancias.length > 0) return 'bg-yellow-50';
                  return 'bg-white';
                };

                const getIcono = () => {
                  if (!item.claveDarovi) return <XCircle className="w-5 h-5 text-red-600" />;
                  if (item.validado) return <CheckCircle className="w-5 h-5 text-green-600" />;
                  return <AlertTriangle className="w-5 h-5 text-yellow-600" />;
                };

                return (
                  <tr key={item.id} className={`${getRowColor()} hover:shadow-inner transition-all`}>
                    <td className="px-6 py-4">
                      <div className="flex items-center justify-center">
                        {getIcono()}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className="font-mono text-sm font-semibold text-blue-700">
                        {item.claveCliente}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <p className="text-sm text-slate-900">{item.descripcionCliente}</p>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <div className="w-24 bg-slate-200 rounded-full h-2">
                          <div
                            className={`h-2 rounded-full ${
                              item.coincidencia >= 95
                                ? 'bg-green-500'
                                : item.coincidencia >= 80
                                ? 'bg-yellow-500'
                                : 'bg-red-500'
                            }`}
                            style={{ width: `${item.coincidencia}%` }}
                          ></div>
                        </div>
                        <span className="text-sm font-semibold text-slate-700">{item.coincidencia}%</span>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      {item.claveDarovi ? (
                        <span className="font-mono text-sm font-semibold text-green-700">
                          {item.claveDarovi}
                        </span>
                      ) : (
                        <span className="text-sm text-red-600 font-medium">NO ENCONTRADO</span>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      {item.descripcionDarovi ? (
                        <div>
                          <p className="text-sm text-slate-900">{item.descripcionDarovi}</p>
                          {item.discrepancias.length > 0 && (
                            <div className="mt-2 space-y-1">
                              {item.discrepancias.map((disc, idx) => (
                                <div key={idx} className="flex items-start gap-2 text-xs text-red-700 bg-red-100 px-2 py-1 rounded">
                                  <AlertTriangle className="w-3 h-3 flex-shrink-0 mt-0.5" />
                                  <span>{disc}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className="text-sm text-slate-400">-</span>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      {item.validado ? (
                        <button className="px-3 py-1 bg-slate-100 text-slate-600 rounded text-xs font-medium">
                          Validado ✓
                        </button>
                      ) : (
                        <button className="px-3 py-1 bg-blue-600 text-white rounded text-xs font-medium hover:bg-blue-700">
                          Validar Manualmente
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="bg-slate-900 rounded-xl py-6 px-6 text-white">
        <h3 className="text-lg font-semibold mb-3">Acerca de la Homologación</h3>
        <p className="text-sm text-slate-300 mb-4">
          El motor de homologación compara las claves del anexo del cliente contra el catálogo maestro de Darovi
          utilizando algoritmos de similitud de texto y validación estricta carácter por carácter.
        </p>
        <div className="grid grid-cols-3 gap-4 text-sm">
          <div className="bg-white/10 rounded-lg py-3 px-3">
            <p className="text-slate-300 mb-1">Verde (≥95%)</p>
            <p className="text-xs text-slate-400">Coincidencia exacta o casi exacta</p>
          </div>
          <div className="bg-white/10 rounded-lg py-3 px-3">
            <p className="text-slate-300 mb-1">Amarillo (80-94%)</p>
            <p className="text-xs text-slate-400">Requiere validación manual</p>
          </div>
          <div className="bg-white/10 rounded-lg py-3 px-3">
            <p className="text-slate-300 mb-1">Rojo (&lt;80%)</p>
            <p className="text-xs text-slate-400">Sin coincidencia / No encontrado</p>
          </div>
        </div>
      </div>
    </div>
  );
}
