import { useState } from 'react';
import { mensajes, proveedores, licitaciones } from '../data/mockData';
import { Search, Send, Paperclip, Users, CheckCircle, Clock, Megaphone } from 'lucide-react';

export function Mensajeria() {
  const [mensajeSeleccionado, setMensajeSeleccionado] = useState(mensajes[0]?.id);
  const [respuesta, setRespuesta] = useState('');
  const [busqueda, setBusqueda] = useState('');

  const mensajeActual = mensajes.find(m => m.id === mensajeSeleccionado);
  const proveedorActual = proveedores.find(p => p.id === mensajeActual?.proveedorId);
  const licitacionActual = licitaciones.find(l => l.id === mensajeActual?.licitacionId);

  const mensajesFiltrados = busqueda
    ? mensajes.filter(m =>
        proveedores.find(p => p.id === m.proveedorId)?.nombre.toLowerCase().includes(busqueda.toLowerCase()) ||
        m.pregunta.toLowerCase().includes(busqueda.toLowerCase())
      )
    : mensajes;

  const formatDate = (date: Date) => {
    return new Intl.DateTimeFormat('es-CL', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    }).format(date);
  };

  const handleEnviarRespuesta = () => {
    if (respuesta.trim()) {
      alert('Respuesta enviada a todos los participantes (modo circular)');
      setRespuesta('');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-slate-900">Mensajería y Aclaraciones</h2>
          <p className="text-slate-600 mt-1">Centro de soporte para participantes</p>
        </div>

        <div className="flex items-center gap-3">
          <div className="bg-white rounded-lg border border-slate-200 px-4 py-2">
            <span className="text-sm text-slate-600">Pendientes: </span>
            <span className="font-semibold text-orange-600">{mensajes.filter(m => !m.respuesta).length}</span>
          </div>
          <div className="bg-white rounded-lg border border-slate-200 px-4 py-2">
            <span className="text-sm text-slate-600">Respondidas: </span>
            <span className="font-semibold text-green-600">{mensajes.filter(m => m.respuesta).length}</span>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
        <div className="grid grid-cols-12 h-[calc(100vh-280px)]">
          <div className="col-span-4 border-r border-slate-200 flex flex-col">
            <div className="p-4 border-b border-slate-200">
              <div className="relative">
                <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="search"
                  placeholder="Buscar proveedor o consulta..."
                  value={busqueda}
                  onChange={(e) => setBusqueda(e.target.value)}
                  className="w-full pl-10 pr-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
            </div>

            <div className="flex-1 overflow-y-auto">
              {mensajesFiltrados.map((mensaje) => {
                const proveedor = proveedores.find(p => p.id === mensaje.proveedorId);
                const licitacion = licitaciones.find(l => l.id === mensaje.licitacionId);
                const isSelected = mensaje.id === mensajeSeleccionado;
                const isPendiente = !mensaje.respuesta;

                return (
                  <button
                    key={mensaje.id}
                    onClick={() => setMensajeSeleccionado(mensaje.id)}
                    className={`w-full p-4 border-b border-slate-200 text-left transition-colors ${
                      isSelected ? 'bg-blue-50' : 'hover:bg-slate-50'
                    }`}
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <div className={`w-2 h-2 rounded-full ${isPendiente ? 'bg-orange-500' : 'bg-green-500'}`}></div>
                        <p className="font-semibold text-slate-900 text-sm">{proveedor?.nombre}</p>
                      </div>
                      {isPendiente ? (
                        <Clock className="w-4 h-4 text-orange-500 flex-shrink-0" />
                      ) : (
                        <CheckCircle className="w-4 h-4 text-green-500 flex-shrink-0" />
                      )}
                    </div>
                    <p className="text-xs text-slate-500 mb-2">{licitacion?.id}</p>
                    <p className="text-sm text-slate-700 line-clamp-2">{mensaje.pregunta}</p>
                    <p className="text-xs text-slate-400 mt-2">{formatDate(mensaje.fecha)}</p>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="col-span-8 flex flex-col">
            {mensajeActual ? (
              <>
                <div className="p-4 border-b border-slate-200 bg-slate-50">
                  <div className="flex items-start justify-between">
                    <div>
                      <h3 className="font-semibold text-slate-900">{proveedorActual?.nombre}</h3>
                      <p className="text-sm text-slate-600 mt-1">{proveedorActual?.email}</p>
                      <p className="text-xs text-slate-500 mt-1">
                        {licitacionActual?.id} - {licitacionActual?.titulo}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 px-3 py-1 bg-blue-100 text-blue-700 rounded-full text-xs font-medium">
                      <Users className="w-3 h-3" />
                      Público
                    </div>
                  </div>
                </div>

                <div className="flex-1 overflow-y-auto p-6 space-y-4">
                  <div className="flex gap-3">
                    <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
                      <span className="text-sm font-semibold text-blue-700">
                        {proveedorActual?.nombre.charAt(0)}
                      </span>
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-semibold text-slate-900 text-sm">{proveedorActual?.nombre}</span>
                        <span className="text-xs text-slate-500">{formatDate(mensajeActual.fecha)}</span>
                      </div>
                      <div className="bg-slate-100 rounded-lg p-4">
                        <p className="text-slate-900">{mensajeActual.pregunta}</p>
                        {mensajeActual.adjuntos.length > 0 && (
                          <div className="mt-3 pt-3 border-t border-slate-200">
                            <p className="text-xs text-slate-600 mb-2">Adjuntos:</p>
                            {mensajeActual.adjuntos.map((adjunto, idx) => (
                              <div key={idx} className="flex items-center gap-2 text-sm text-blue-600">
                                <Paperclip className="w-3 h-3" />
                                {adjunto}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  {mensajeActual.respuesta && (
                    <div className="flex gap-3">
                      <div className="w-10 h-10 rounded-full bg-green-100 flex items-center justify-center flex-shrink-0">
                        <span className="text-sm font-semibold text-green-700">AD</span>
                      </div>
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-semibold text-slate-900 text-sm">Administrador</span>
                          <span className="text-xs text-slate-500">{formatDate(mensajeActual.fecha)}</span>
                          <span className="flex items-center gap-1 text-xs text-blue-600">
                            <Megaphone className="w-3 h-3" />
                            Circular a todos
                          </span>
                        </div>
                        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                          <p className="text-slate-900">{mensajeActual.respuesta}</p>
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                <div className="p-4 border-t border-slate-200 bg-slate-50">
                  {!mensajeActual.respuesta ? (
                    <>
                      <div className="flex items-center gap-2 mb-3 p-3 bg-blue-50 border border-blue-200 rounded-lg">
                        <Megaphone className="w-4 h-4 text-blue-600 flex-shrink-0" />
                        <p className="text-sm text-blue-900">
                          Modo Circular: Tu respuesta será visible para todos los participantes de la licitación
                        </p>
                      </div>

                      <div className="flex gap-2">
                        <button className="p-2 text-slate-600 hover:bg-slate-200 rounded-lg transition-colors">
                          <Paperclip className="w-5 h-5" />
                        </button>
                        <input
                          type="text"
                          placeholder="Escribe tu aclaración..."
                          value={respuesta}
                          onChange={(e) => setRespuesta(e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && handleEnviarRespuesta()}
                          className="flex-1 px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                        />
                        <button
                          onClick={handleEnviarRespuesta}
                          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                        >
                          <Send className="w-4 h-4" />
                          Responder a Todos
                        </button>
                      </div>
                    </>
                  ) : (
                    <div className="text-center py-4">
                      <div className="inline-flex items-center gap-2 px-4 py-2 bg-green-50 text-green-700 rounded-lg">
                        <CheckCircle className="w-5 h-5" />
                        <span className="font-medium">Consulta respondida</span>
                      </div>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="flex items-center justify-center h-full">
                <div className="text-center">
                  <MessageSquare className="w-16 h-16 text-slate-300 mx-auto mb-4" />
                  <p className="text-slate-600">Selecciona una consulta para ver los detalles</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function MessageSquare({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
    </svg>
  );
}
