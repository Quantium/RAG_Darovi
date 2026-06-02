import { useParams, Link } from 'react-router';
import { useState } from 'react';
import { licitaciones, alertasIA } from '../../data/pharmaData';
import { ArrowLeft, Bot, FileText, AlertTriangle, CheckCircle, Sparkles, Download, RefreshCw, Send, Database } from 'lucide-react';

export function AsistenteIA() {
  const { id } = useParams();
  const licitacion = licitaciones.find(l => l.id === id);
  const [procesando, setProcesando] = useState(false);
  const [mensajeChat, setMensajeChat] = useState('');
  const [conversacion, setConversacion] = useState<Array<{ tipo: 'usuario' | 'asistente'; texto: string }>>([
    {
      tipo: 'asistente',
      texto: '¡Hola! Soy tu asistente especializado en licitaciones farmacéuticas. Puedo ayudarte a interpretar bases, identificar riesgos y responder preguntas sobre este proceso. ¿En qué puedo ayudarte?',
    },
  ]);

  if (!licitacion) {
    return (
      <div className="text-center py-12">
        <p className="text-slate-600">Licitación no encontrada</p>
      </div>
    );
  }

  const alertasPorSeveridad = {
    Alta: alertasIA.filter(a => a.severidad === 'Alta'),
    Media: alertasIA.filter(a => a.severidad === 'Media'),
    Baja: alertasIA.filter(a => a.severidad === 'Baja'),
  };

  const severidadColors = {
    Alta: 'bg-red-100 text-red-700 border-red-300',
    Media: 'bg-orange-100 text-orange-700 border-orange-300',
    Baja: 'bg-yellow-100 text-yellow-700 border-yellow-300',
  };

  const handleProcesarBases = () => {
    setProcesando(true);
    setTimeout(() => setProcesando(false), 3000);
  };

  const handleEnviarMensaje = () => {
    if (mensajeChat.trim()) {
      setConversacion([...conversacion, { tipo: 'usuario', texto: mensajeChat }]);
      setMensajeChat('');

      setTimeout(() => {
        setConversacion(prev => [
          ...prev,
          {
            tipo: 'asistente',
            texto: 'He analizado tu consulta. Basándome en las bases de esta licitación y mi entrenamiento en procesos del sector salud mexicano, te recomiendo verificar los puntos críticos identificados en el panel de alertas.',
          },
        ]);
      }, 1000);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/" className="p-2 hover:bg-slate-100 rounded-lg transition-colors">
            <ArrowLeft className="w-5 h-5 text-slate-600" />
          </Link>
          <div>
            <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
              <Bot className="w-7 h-7 text-purple-600" />
              Asistente IA Vectorizado
            </h2>
            <div className="flex items-center gap-3 mt-1">
              <p className="text-sm font-mono text-blue-600 font-semibold">{licitacion.numeroProcedimiento}</p>
              <span className="text-slate-400">•</span>
              <p className="text-sm text-slate-600">{licitacion.descripcion}</p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <a
            href="http://localhost:9001/login"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-50 transition-colors"
          >
            <Database className="w-4 h-4" />
            Archivos Minio
          </a>
          <button className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-50 transition-colors">
            <Download className="w-4 h-4" />
            Exportar Análisis
          </button>
          <button
            onClick={handleProcesarBases}
            disabled={procesando}
            className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50"
          >
            {procesando ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                Procesando...
              </>
            ) : (
              <>
                <Sparkles className="w-4 h-4" />
                Procesar Bases
              </>
            )}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-6">
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <div className="bg-gradient-to-r from-purple-600 to-purple-700 text-white px-6 py-4">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <FileText className="w-5 h-5" />
              Visor de Bases (PDF)
            </h3>
            <p className="text-sm text-purple-100 mt-1">Documento original del cliente</p>
          </div>

          <div className="p-6 bg-slate-50 h-[700px] overflow-y-auto">
            <div className="bg-white border-2 border-purple-200 rounded-lg py-6 px-6 mb-4">
              <div className="flex items-start gap-3 mb-3">
                <div className="w-8 h-8 bg-purple-100 rounded flex items-center justify-center flex-shrink-0">
                  <span className="text-xs font-bold text-purple-700">1</span>
                </div>
                <div className="flex-1">
                  <h4 className="font-semibold text-slate-900 mb-2">BASES DE LICITACIÓN PÚBLICA</h4>
                  <p className="text-sm text-slate-700 leading-relaxed">
                    La presente Licitación Pública tiene por objeto la adquisición de medicamentos oncológicos
                    de alto espectro para el Instituto Mexicano del Seguro Social...
                  </p>
                </div>
              </div>

              <div className="mt-4 py-3 px-3 bg-yellow-50 border-l-4 border-yellow-400 rounded-r">
                <p className="text-sm text-slate-700">
                  <span className="font-semibold">Sección 4.3:</span> "El proveedor deberá indicar la{' '}
                  <mark className="bg-yellow-200 px-1">cantidad ofertada</mark> en la columna correspondiente"
                </p>
              </div>
            </div>

            <div className="bg-white border-2 border-purple-200 rounded-lg py-6 px-6 mb-4">
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 bg-purple-100 rounded flex items-center justify-center flex-shrink-0">
                  <span className="text-xs font-bold text-purple-700">2</span>
                </div>
                <div className="flex-1">
                  <h4 className="font-semibold text-slate-900 mb-2">CALENDARIO DE EVENTOS</h4>
                  <ul className="text-sm text-slate-700 space-y-1">
                    <li>• Publicación de bases: 15 de abril de 2026</li>
                    <li className="text-red-600 font-medium">
                      • Entrega de muestras:{' '}
                      <mark className="bg-red-100 px-1">5 de mayo de 2026, 14:00 hrs</mark>
                    </li>
                    <li>• Junta de aclaraciones: 8 de mayo de 2026</li>
                    <li>• Presentación de propuestas: 15 de mayo de 2026, 14:00 hrs</li>
                  </ul>
                </div>
              </div>
            </div>

            <div className="bg-white border-2 border-purple-200 rounded-lg py-6 px-6">
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 bg-purple-100 rounded flex items-center justify-center flex-shrink-0">
                  <span className="text-xs font-bold text-purple-700">9</span>
                </div>
                <div className="flex-1">
                  <h4 className="font-semibold text-slate-900 mb-2">REQUISITOS TÉCNICOS</h4>
                  <p className="text-sm text-slate-700">
                    Todos los medicamentos deberán contar con registro sanitario vigente expedido por COFEPRIS.
                  </p>
                  <p className="text-xs text-slate-500 mt-2">
                    *Nota: Todos los proveedores deberán contar con{' '}
                    <mark className="bg-green-200 px-1">ISO 9001:2015 vigente</mark>
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
            <div className="bg-gradient-to-r from-blue-600 to-blue-700 text-white px-6 py-4">
              <h3 className="text-lg font-semibold flex items-center gap-2">
                <Sparkles className="w-5 h-5" />
                Resumen Automático del Evento
              </h3>
            </div>

            <div className="p-6 space-y-4">
              <div>
                <label className="text-xs font-semibold text-slate-700 uppercase tracking-wide">
                  Objeto de la Licitación
                </label>
                <p className="mt-1 text-sm text-slate-900 py-3 px-3 bg-blue-50 border border-blue-200 rounded-lg">
                  Adquisición de medicamentos oncológicos de alto espectro para tratamiento de pacientes del IMSS
                </p>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-xs font-semibold text-slate-700 uppercase tracking-wide">
                    Fecha de Publicación
                  </label>
                  <div className="mt-1 flex items-center gap-2 text-sm text-slate-900 py-3 px-3 bg-slate-50 border border-slate-200 rounded-lg">
                    <CheckCircle className="w-4 h-4 text-green-600" />
                    15/04/2026
                  </div>
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-700 uppercase tracking-wide">
                    Fecha Límite
                  </label>
                  <div className="mt-1 flex items-center gap-2 text-sm text-slate-900 py-3 px-3 bg-orange-50 border border-orange-200 rounded-lg">
                    <AlertTriangle className="w-4 h-4 text-orange-600" />
                    15/05/2026 14:00
                  </div>
                </div>
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-700 uppercase tracking-wide">
                  Entregables Clave
                </label>
                <ul className="mt-2 space-y-2">
                  <li className="flex items-center gap-2 text-sm text-slate-900 py-2 px-2 bg-slate-50 rounded">
                    <CheckCircle className="w-4 h-4 text-green-600" />
                    Propuesta Técnica (3 tantos)
                  </li>
                  <li className="flex items-center gap-2 text-sm text-slate-900 py-2 px-2 bg-slate-50 rounded">
                    <CheckCircle className="w-4 h-4 text-green-600" />
                    Propuesta Económica (sobre cerrado)
                  </li>
                  <li className="flex items-center gap-2 text-sm text-red-900 py-2 px-2 bg-red-50 rounded">
                    <AlertTriangle className="w-4 h-4 text-red-600" />
                    Muestras físicas (antes del 05/05)
                  </li>
                </ul>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-xl border border-red-200 shadow-sm">
            <div className="bg-gradient-to-r from-red-600 to-red-700 text-white px-6 py-4">
              <h3 className="text-lg font-semibold flex items-center gap-2">
                <AlertTriangle className="w-5 h-5" />
                Panel de Alertas de Ambigüedad
              </h3>
              <p className="text-sm text-red-100 mt-1">
                {alertasIA.length} alertas detectadas automáticamente
              </p>
            </div>

            <div className="p-6 max-h-[500px] overflow-y-auto space-y-3">
              {Object.entries(alertasPorSeveridad).map(([severidad, alertas]) =>
                alertas.map(alerta => (
                  <div
                    key={alerta.id}
                    className={`border-l-4 rounded-r-lg py-4 px-4 ${severidadColors[severidad as keyof typeof severidadColors]}`}
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <AlertTriangle className="w-4 h-4" />
                        <span className="text-xs font-semibold uppercase">{alerta.tipo}</span>
                      </div>
                      <span className={`text-xs font-bold px-2 py-1 rounded ${
                        severidad === 'Alta' ? 'bg-red-200 text-red-900' :
                        severidad === 'Media' ? 'bg-orange-200 text-orange-900' :
                        'bg-yellow-200 text-yellow-900'
                      }`}>
                        {severidad}
                      </span>
                    </div>

                    <p className="text-sm font-medium text-slate-900 mb-2">{alerta.descripcion}</p>

                    <div className="text-xs text-slate-600 mb-2">
                      📍 {alerta.ubicacion}
                    </div>

                    <div className="bg-white/50 rounded py-2 px-2 mb-2">
                      <p className="text-xs font-mono text-slate-700 italic">
                        "{alerta.textoOriginal}"
                      </p>
                    </div>

                    <div className="bg-white rounded py-3 px-3 border-l-2 border-blue-500">
                      <p className="text-xs font-semibold text-blue-900 mb-1">💡 Recomendación:</p>
                      <p className="text-xs text-slate-700">{alerta.recomendacion}</p>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="bg-gradient-to-r from-purple-600 to-blue-600 rounded-xl py-6 px-6 text-white shadow-lg">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-lg font-semibold mb-2">¿Cómo funciona el Asistente IA?</h3>
            <p className="text-sm text-purple-100 mb-4">
              Este sistema utiliza modelos de lenguaje especializados entrenados en bases de licitaciones
              del sector salud mexicano para detectar patrones de riesgo y ambigüedades.
            </p>
            <ul className="space-y-2 text-sm">
              <li className="flex items-center gap-2">
                <CheckCircle className="w-4 h-4 flex-shrink-0" />
                Extracción automática de fechas y entregables críticos
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle className="w-4 h-4 flex-shrink-0" />
                Detección de requisitos ocultos en notas al pie y anexos
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle className="w-4 h-4 flex-shrink-0" />
                Análisis de términos ambiguos que han causado descalificaciones previas
              </li>
            </ul>
          </div>
          <Bot className="w-24 h-24 text-white/30" />
        </div>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="bg-gradient-to-r from-purple-600 to-purple-700 text-white px-6 py-4">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <Bot className="w-5 h-5" />
            Chat con el LLM Entrenado
          </h3>
          <p className="text-sm text-purple-100 mt-1">Consulta directamente con el asistente especializado</p>
        </div>

        <div className="h-[500px] flex flex-col">
          <div className="flex-1 overflow-y-auto py-6 px-6 space-y-4 bg-slate-50">
            {conversacion.map((mensaje, index) => (
              <div
                key={index}
                className={`flex gap-3 ${mensaje.tipo === 'usuario' ? 'justify-end' : 'justify-start'}`}
              >
                {mensaje.tipo === 'asistente' && (
                  <div className="w-8 h-8 rounded-full bg-purple-600 flex items-center justify-center flex-shrink-0">
                    <Bot className="w-5 h-5 text-white" />
                  </div>
                )}
                <div
                  className={`max-w-[70%] rounded-lg px-4 py-3 ${
                    mensaje.tipo === 'usuario'
                      ? 'bg-blue-600 text-white'
                      : 'bg-white border border-slate-200 text-slate-900'
                  }`}
                >
                  <p className="text-sm">{mensaje.texto}</p>
                </div>
                {mensaje.tipo === 'usuario' && (
                  <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center flex-shrink-0">
                    <span className="text-sm font-semibold text-white">TÚ</span>
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="p-4 bg-white border-t border-slate-200">
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="Pregunta algo sobre esta licitación..."
                value={mensajeChat}
                onChange={(e) => setMensajeChat(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleEnviarMensaje()}
                className="flex-1 px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
              />
              <button
                onClick={handleEnviarMensaje}
                disabled={!mensajeChat.trim()}
                className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Send className="w-4 h-4" />
                Enviar
              </button>
            </div>
            <p className="text-xs text-slate-500 mt-2">
              El LLM está entrenado con datos de licitaciones anteriores almacenados en Minio
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
