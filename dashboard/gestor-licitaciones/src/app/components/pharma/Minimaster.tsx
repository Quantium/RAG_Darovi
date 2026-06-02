import { useParams, Link } from 'react-router';
import { licitaciones, registrosSanitarios } from '../../data/pharmaData';
import { ArrowLeft, FileCheck, Download, Send, CheckCircle, XCircle, AlertTriangle, Clock } from 'lucide-react';

export function Minimaster() {
  const { id } = useParams();
  const licitacion = licitaciones.find(l => l.id === id);

  if (!licitacion) {
    return (
      <div className="text-center py-12">
        <p className="text-slate-600">Licitación no encontrada</p>
      </div>
    );
  }

  const registrosAprobados = registrosSanitarios.filter(r => r.estatusCalidad === 'Aprobado').length;
  const registrosPendientes = registrosSanitarios.filter(r => r.estatusCalidad === 'Pendiente').length;
  const registrosProblemas = registrosSanitarios.filter(
    r => r.estatusCalidad === 'Faltante' || r.estatusCalidad === 'Inconsistencia'
  ).length;

  const estatusColors = {
    Aprobado: 'bg-green-500',
    Pendiente: 'bg-yellow-500',
    Faltante: 'bg-red-500',
    Inconsistencia: 'bg-orange-500',
  };

  const puedeGenerarCartas = registrosAprobados > 0 && registrosProblemas === 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/" className="p-2 hover:bg-slate-100 rounded-lg transition-colors">
            <ArrowLeft className="w-5 h-5 text-slate-600" />
          </Link>
          <div>
            <h2 className="text-2xl font-bold text-slate-900">Minimáster y Cartas de Apoyo</h2>
            <div className="flex items-center gap-3 mt-1">
              <p className="text-sm font-mono text-blue-600 font-semibold">{licitacion.numeroProcedimiento}</p>
              <span className="text-slate-400">•</span>
              <p className="text-sm text-slate-600">Validación de registros sanitarios</p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-50 transition-colors">
            <Download className="w-4 h-4" />
            Exportar Matriz
          </button>
          <button
            disabled={!puedeGenerarCartas}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
              puedeGenerarCartas
                ? 'bg-green-600 text-white hover:bg-green-700'
                : 'bg-slate-300 text-slate-500 cursor-not-allowed'
            }`}
          >
            <Send className="w-4 h-4" />
            Generar Cartas (Macros)
          </button>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-4">
        <div className="bg-white rounded-xl border border-slate-200 py-6 px-6">
          <p className="text-sm text-slate-600">Total Productos</p>
          <p className="text-3xl font-bold text-slate-900 mt-1">{registrosSanitarios.length}</p>
        </div>
        <div className="bg-white rounded-xl border border-green-200 py-6 px-6">
          <p className="text-sm text-slate-600">Aprobados (Verde)</p>
          <p className="text-3xl font-bold text-green-600 mt-1">{registrosAprobados}</p>
        </div>
        <div className="bg-white rounded-xl border border-yellow-200 py-6 px-6">
          <p className="text-sm text-slate-600">Pendientes (Amarillo)</p>
          <p className="text-3xl font-bold text-yellow-600 mt-1">{registrosPendientes}</p>
        </div>
        <div className="bg-white rounded-xl border border-red-200 py-6 px-6">
          <p className="text-sm text-slate-600">Problemas (Rojo)</p>
          <p className="text-3xl font-bold text-red-600 mt-1">{registrosProblemas}</p>
        </div>
      </div>

      {!puedeGenerarCartas && (
        <div className="bg-orange-50 border-l-4 border-orange-500 py-4 px-4 rounded-r-lg">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-orange-600 flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="text-sm font-semibold text-orange-900">Generación de Cartas Bloqueada</h3>
              <p className="text-sm text-orange-800 mt-1">
                Para generar las cartas de apoyo automáticamente, todos los productos deben estar en estatus "Aprobado" (verde).
                Resuelve primero los productos pendientes o con inconsistencias.
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="bg-slate-50 px-6 py-4 border-b border-slate-200">
          <h3 className="text-lg font-semibold text-slate-900">Matriz de Registros Sanitarios (Tiempo Real)</h3>
          <p className="text-sm text-slate-600 mt-1">
            Sincronizado con el área de Calidad • Última actualización: hace 5 minutos
          </p>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-slate-100 border-b border-slate-200">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  Semáforo
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  Producto
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  Clave Darovi
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  Fabricante
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  Registro Sanitario
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  Vigencia
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                  Estatus Calidad
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {registrosSanitarios.map((registro) => {
                const getIcono = () => {
                  switch (registro.estatusCalidad) {
                    case 'Aprobado':
                      return <CheckCircle className="w-5 h-5 text-green-600" />;
                    case 'Pendiente':
                      return <Clock className="w-5 h-5 text-yellow-600" />;
                    case 'Faltante':
                      return <XCircle className="w-5 h-5 text-red-600" />;
                    case 'Inconsistencia':
                      return <AlertTriangle className="w-5 h-5 text-orange-600" />;
                  }
                };

                const getRowClass = () => {
                  switch (registro.estatusCalidad) {
                    case 'Aprobado':
                      return 'bg-green-50';
                    case 'Pendiente':
                      return 'bg-yellow-50';
                    case 'Faltante':
                      return 'bg-red-50';
                    case 'Inconsistencia':
                      return 'bg-orange-50';
                  }
                };

                return (
                  <tr key={registro.id} className={`${getRowClass()} hover:shadow-inner transition-all`}>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <div
                          className={`w-4 h-4 rounded-full ${estatusColors[registro.estatusCalidad]}`}
                          title={registro.estatusCalidad}
                        ></div>
                        {getIcono()}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <p className="text-sm font-medium text-slate-900">{registro.producto}</p>
                    </td>
                    <td className="px-6 py-4">
                      <span className="font-mono text-sm text-blue-700">{registro.clave}</span>
                    </td>
                    <td className="px-6 py-4">
                      <p className="text-sm text-slate-700">{registro.fabricante}</p>
                    </td>
                    <td className="px-6 py-4">
                      <span className="font-mono text-sm font-semibold text-slate-900">
                        {registro.registroSanitario}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      {registro.fechaVigencia ? (
                        <span className="text-sm text-slate-700">
                          {new Intl.DateTimeFormat('es-MX', {
                            day: '2-digit',
                            month: 'short',
                            year: 'numeric',
                          }).format(registro.fechaVigencia)}
                        </span>
                      ) : (
                        <span className="text-sm text-slate-400">-</span>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      <div>
                        <span
                          className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-medium ${
                            registro.estatusCalidad === 'Aprobado'
                              ? 'bg-green-100 text-green-800'
                              : registro.estatusCalidad === 'Pendiente'
                              ? 'bg-yellow-100 text-yellow-800'
                              : registro.estatusCalidad === 'Faltante'
                              ? 'bg-red-100 text-red-800'
                              : 'bg-orange-100 text-orange-800'
                          }`}
                        >
                          {registro.estatusCalidad}
                        </span>
                        {registro.observaciones && (
                          <p className="text-xs text-red-700 mt-2 font-medium">{registro.observaciones}</p>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="bg-gradient-to-br from-blue-600 to-blue-800 rounded-xl py-6 px-6 text-white shadow-lg">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-lg font-semibold mb-2 flex items-center gap-2">
              <FileCheck className="w-5 h-5" />
              Proceso de Generación de Cartas
            </h3>
            <p className="text-sm text-blue-100 mb-4">
              Una vez que todos los registros estén en verde (Aprobado), el sistema:
            </p>
            <ol className="space-y-2 text-sm list-decimal list-inside">
              <li>Extrae automáticamente los datos de cada registro sanitario aprobado</li>
              <li>Autocompleta las plantillas de cartas de apoyo predefinidas</li>
              <li>Genera documentos PDF individuales para cada proveedor</li>
              <li>Envía digitalmente a Adquisiciones para firma del proveedor</li>
              <li>Registra el envío en Salesforce para trazabilidad</li>
            </ol>
          </div>
          <Send className="w-20 h-20 text-white/20" />
        </div>
      </div>
    </div>
  );
}
