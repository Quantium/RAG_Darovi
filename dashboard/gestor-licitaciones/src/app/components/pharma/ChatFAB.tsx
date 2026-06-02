import { useState } from 'react';
import { Bot, Send, X, Minimize2 } from 'lucide-react';
import { useFuente, FuenteDatos } from '../../context/FuenteContext';

export function ChatFAB() {
  const [isOpen, setIsOpen] = useState(false);
  const [mensajeChat, setMensajeChat] = useState('');
  const { fuenteSeleccionada } = useFuente();
  const [conversacion, setConversacion] = useState<Array<{ tipo: 'usuario' | 'asistente'; texto: string; fuente?: FuenteDatos }>>([
    {
      tipo: 'asistente',
      texto: '¡Hola! Soy tu asistente especializado en licitaciones farmacéuticas. Puedo ayudarte a interpretar bases, identificar riesgos y responder preguntas basándome en la fuente de datos seleccionada.',
      fuente: 'Licitaciones',
    },
  ]);

  const handleEnviarMensaje = () => {
    if (mensajeChat.trim()) {
      setConversacion([...conversacion, { tipo: 'usuario', texto: mensajeChat, fuente: fuenteSeleccionada }]);
      setMensajeChat('');

      setTimeout(() => {
        setConversacion(prev => [
          ...prev,
          {
            tipo: 'asistente',
            texto: `He analizado tu consulta usando datos de "${fuenteSeleccionada}". Basándome en mi entrenamiento específico en esta fuente, puedo ayudarte con interpretación de bases, análisis de riesgos y recomendaciones específicas.`,
            fuente: fuenteSeleccionada,
          },
        ]);
      }, 1000);
    }
  };

  const fuenteColors: Record<FuenteDatos, string> = {
    Laboratorios: 'bg-green-100 text-green-700 border-green-300',
    Licitaciones: 'bg-blue-100 text-blue-700 border-blue-300',
    SSJAL: 'bg-purple-100 text-purple-700 border-purple-300',
  };

  return (
    <>
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          className="fixed bottom-6 right-6 w-16 h-16 bg-gradient-to-r from-purple-600 to-purple-700 text-white rounded-full shadow-lg hover:shadow-xl transition-all hover:scale-110 flex items-center justify-center z-50"
          title="Chat con el Asistente IA"
        >
          <Bot className="w-8 h-8" />
        </button>
      )}

      {isOpen && (
        <div className="fixed bottom-6 right-6 w-96 h-[600px] bg-white rounded-xl shadow-2xl border border-slate-200 flex flex-col z-50">
          <div className="bg-gradient-to-r from-purple-600 to-purple-700 text-white px-4 py-3 rounded-t-xl flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Bot className="w-5 h-5" />
              <div>
                <h3 className="font-semibold">Asistente IA</h3>
                <p className="text-xs text-purple-100">Usando fuente: {fuenteSeleccionada}</p>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setIsOpen(false)}
                className="p-1 hover:bg-white/20 rounded transition-colors"
                title="Minimizar"
              >
                <Minimize2 className="w-4 h-4" />
              </button>
              <button
                onClick={() => setIsOpen(false)}
                className="p-1 hover:bg-white/20 rounded transition-colors"
                title="Cerrar"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto py-4 px-4 space-y-3 bg-slate-50">
            {conversacion.map((mensaje, index) => (
              <div key={index}>
                <div className={`flex gap-2 ${mensaje.tipo === 'usuario' ? 'justify-end' : 'justify-start'}`}>
                  {mensaje.tipo === 'asistente' && (
                    <div className="w-7 h-7 rounded-full bg-purple-600 flex items-center justify-center flex-shrink-0">
                      <Bot className="w-4 h-4 text-white" />
                    </div>
                  )}
                  <div className="flex flex-col gap-1 max-w-[75%]">
                    {mensaje.fuente && mensaje.tipo === 'asistente' && (
                      <span className={`text-xs px-2 py-0.5 rounded-full self-start border ${fuenteColors[mensaje.fuente]}`}>
                        📁 {mensaje.fuente}
                      </span>
                    )}
                    <div
                      className={`rounded-lg px-3 py-2 ${
                        mensaje.tipo === 'usuario'
                          ? 'bg-blue-600 text-white'
                          : 'bg-white border border-slate-200 text-slate-900'
                      }`}
                    >
                      <p className="text-sm">{mensaje.texto}</p>
                    </div>
                  </div>
                  {mensaje.tipo === 'usuario' && (
                    <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center flex-shrink-0">
                      <span className="text-xs font-semibold text-white">TÚ</span>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="p-3 bg-white border-t border-slate-200 rounded-b-xl">
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="Escribe tu pregunta..."
                value={mensajeChat}
                onChange={(e) => setMensajeChat(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleEnviarMensaje()}
                className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
              />
              <button
                onClick={handleEnviarMensaje}
                disabled={!mensajeChat.trim()}
                className="p-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
            <p className="text-xs text-slate-500 mt-2">
              💾 Consultando carpeta: <span className="font-semibold">{fuenteSeleccionada}</span> en Minio
            </p>
          </div>
        </div>
      )}
    </>
  );
}
