import { useParams, Link } from 'react-router';
import { useState } from 'react';
import { licitaciones, preguntasAclaracion } from '../../data/pharmaData';
import { ArrowLeft, Plus, Download, Send, CheckCircle, Clock } from 'lucide-react';

type Area = 'Finanzas' | 'Tráfico' | 'Calidad' | 'Legal' | 'Operaciones';

export function JuntasAclaraciones() {
  const { id } = useParams();
  const licitacion = licitaciones.find(l => l.id === id);
  const [areaFiltro, setAreaFiltro] = useState<Area | 'Todas'>('Todas');

  if (!licitacion) {
    return (
      <div className="text-center py-12">
        <p className="text-slate-600">Licitación no encontrada</p>
      </div>
    );
  }

  const preguntasFiltradas =
    areaFiltro === 'Todas' ? preguntasAclaracion : preguntasAclaracion.filter(p => p.area === areaFiltro);

  const preguntasPendientes = preguntasAclaracion.filter(p => !p.respondida).length;
  const preguntasRespondidas = preguntasAclaracion.filter(p => p.respondida).length;

  const areaColors: Record<Area, string> = {
    Finanzas: 'bg-green-100 text-green-700',
    Tráfico: 'bg-blue-100 text-blue-700',
    Calidad: 'bg-purple-100 text-purple-700',
    Legal: 'bg-red-100 text-red-700',
    Operaciones: 'bg-orange-100 text-orange-700',
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/" className="p-2 hover:bg-slate-100 rounded-lg transition-colors">
            <ArrowLeft className="w-5 h-5 text-slate-600" />
          </Link>
          <div>
            <h2 className="text-2xl font-bold text-slate-900">Juntas de Aclaraciones</h2>
            <div className="flex items-center gap-3 mt-1">
              <p className="text-sm font-mono text-blue-600 font-semibold">{licitacion.numeroProcedimiento}</p>
              <span className="text-slate-400">•</span>
              <p className="text-sm text-slate-600">Consolidación de dudas por área</p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-50 transition-colors">
            <Plus className="w-4 h-4" />
            Nueva Pregunta
          </button>
          <button className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
            <Download className="w-4 h-4" />
            Exportar para Cliente
          </button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white rounded-xl border border-slate-200 py-6 px-6">
          <p className="text-sm text-slate-600">Total Preguntas</p>
          <p className="text-3xl font-bold text-slate-900 mt-1">{preguntasAclaracion.length}</p>
        </div>
        <div className="bg-white rounded-xl border border-orange-200 py-6 px-6">
          <p className="text-sm text-slate-600">Pendientes</p>
          <p className="text-3xl font-bold text-orange-600 mt-1">{preguntasPendientes}</p>
        </div>
        <div className="bg-white rounded-xl border border-green-200 py-6 px-6">
          <p className="text-sm text-slate-600">Respondidas</p>
          <p className="text-3xl font-bold text-green-600 mt-1">{preguntasRespondidas}</p>
        </div>
      </div>

      <div className="bg-blue-50 border-l-4 border-blue-500 py-4 px-4 rounded-r-lg">
        <div className="flex items-start gap-3">
          <Send className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
          <div>
            <h3 className="text-sm font-semibold text-blue-900">Formato Estandarizado para el Cliente</h3>
            <p className="text-sm text-blue-800 mt-1">
              Al exportar, el sistema genera automáticamente el documento en el formato oficial exigido por{' '}
              <span className="font-semibold">{licitacion.dependencia}</span>, consolidando todas las preguntas
              de Darovi y proveedores asociados.
            </p>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 py-6 px-6 shadow-sm">
        <div className="flex items-center gap-2 mb-4">
          <button
            onClick={() => setAreaFiltro('Todas')}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              areaFiltro === 'Todas' ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
            }`}
          >
            Todas
          </button>
          {(['Finanzas', 'Tráfico', 'Calidad', 'Legal', 'Operaciones'] as Area[]).map(area => (
            <button
              key={area}
              onClick={() => setAreaFiltro(area)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                areaFiltro === area ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
              }`}
            >
              {area}
            </button>
          ))}
        </div>

        <div className="space-y-4">
          {preguntasFiltradas.map(pregunta => (
            <div
              key={pregunta.id}
              className={`border-l-4 rounded-r-lg py-4 px-4 ${
                pregunta.respondida ? 'border-green-400 bg-green-50' : 'border-orange-400 bg-orange-50'
              }`}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <span className={`px-3 py-1 rounded-full text-xs font-semibold ${areaColors[pregunta.area]}`}>
                    {pregunta.area}
                  </span>
                  {pregunta.respondida ? (
                    <div className="flex items-center gap-1 text-xs text-green-700 font-medium">
                      <CheckCircle className="w-4 h-4" />
                      Respondida
                    </div>
                  ) : (
                    <div className="flex items-center gap-1 text-xs text-orange-700 font-medium">
                      <Clock className="w-4 h-4" />
                      Pendiente
                    </div>
                  )}
                </div>
                <span className="text-xs text-slate-500">
                  {new Intl.DateTimeFormat('es-MX', {
                    day: '2-digit',
                    month: 'short',
                    hour: '2-digit',
                    minute: '2-digit',
                  }).format(pregunta.fechaCreacion)}
                </span>
              </div>

              <div className="bg-white rounded-lg py-4 px-4 mb-3">
                <p className="text-xs text-slate-600 mb-2 font-medium">📍 {pregunta.referenciaBase}</p>
                <p className="text-sm text-slate-900 font-medium">Pregunta:</p>
                <p className="text-sm text-slate-700 mt-1">{pregunta.pregunta}</p>
              </div>

              {pregunta.respuesta && (
                <div className="bg-green-100 border border-green-300 rounded-lg py-4 px-4">
                  <p className="text-sm text-green-900 font-medium mb-1">Respuesta del Cliente:</p>
                  <p className="text-sm text-green-800">{pregunta.respuesta}</p>
                </div>
              )}

              {!pregunta.respondida && (
                <div className="mt-3 flex gap-2">
                  <input
                    type="text"
                    placeholder="Ingresa la respuesta del cliente..."
                    className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <button className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium">
                    Guardar Respuesta
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="bg-slate-900 rounded-xl py-6 px-6 text-white">
        <h3 className="text-lg font-semibold mb-3">Formulario Unificado</h3>
        <p className="text-sm text-slate-300 mb-4">
          Este módulo elimina los "correos infinitos" centralizando todas las dudas en un solo lugar.
        </p>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-semibold text-slate-400 uppercase mb-2 block">Área Solicitante</label>
            <select className="w-full px-3 py-2 bg-white/10 border border-white/20 rounded-lg text-white text-sm">
              <option>Finanzas</option>
              <option>Tráfico</option>
              <option>Calidad</option>
              <option>Legal</option>
              <option>Operaciones</option>
            </select>
          </div>
          <div>
            <label className="text-xs font-semibold text-slate-400 uppercase mb-2 block">
              Referencia a la Base
            </label>
            <input
              type="text"
              placeholder="Ej: Anexo 2, página 4"
              className="w-full px-3 py-2 bg-white/10 border border-white/20 rounded-lg text-white placeholder-slate-400 text-sm"
            />
          </div>
        </div>

        <div className="mt-4">
          <label className="text-xs font-semibold text-slate-400 uppercase mb-2 block">Pregunta Literal</label>
          <textarea
            rows={3}
            placeholder="Escribe la pregunta exactamente como debe aparecer en el documento oficial..."
            className="w-full px-3 py-2 bg-white/10 border border-white/20 rounded-lg text-white placeholder-slate-400 text-sm resize-none"
          ></textarea>
        </div>

        <button className="mt-4 flex items-center gap-2 px-4 py-2 bg-white text-slate-900 rounded-lg hover:bg-slate-100 transition-colors font-medium text-sm">
          <Plus className="w-4 h-4" />
          Agregar Pregunta
        </button>
      </div>
    </div>
  );
}
