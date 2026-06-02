import { useParams, Link } from 'react-router';
import { useState } from 'react';
import { licitaciones, documentos, requisitosBase } from '../../data/pharmaData';
import { TipoPropuesta } from '../../types-pharma';
import {
  ArrowLeft,
  FolderTree,
  Upload,
  Download,
  CheckCircle,
  XCircle,
  AlertTriangle,
  FileText,
  Eye,
  Trash2,
  ExternalLink,
} from 'lucide-react';

export function Expediente() {
  const { id } = useParams();
  const licitacion = licitaciones.find(l => l.id === id);
  const [pestanaActiva, setPestanaActiva] = useState<TipoPropuesta>('Técnica');

  if (!licitacion) {
    return (
      <div className="text-center py-12">
        <p className="text-slate-600">Licitación no encontrada</p>
      </div>
    );
  }

  const documentosPorTipo = documentos.filter(d => d.tipo === pestanaActiva);
  const requisitosNoVerificados = requisitosBase.filter(r => !r.verificado && r.esObligatorio);
  const requisitosCriticos = requisitosBase.filter(r => r.alertaCritica);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/" className="p-2 hover:bg-slate-100 rounded-lg transition-colors">
            <ArrowLeft className="w-5 h-5 text-slate-600" />
          </Link>
          <div>
            <h2 className="text-2xl font-bold text-slate-900">Expediente de Contrato</h2>
            <div className="flex items-center gap-3 mt-1">
              <p className="text-sm font-mono text-blue-600 font-semibold">{licitacion.numeroProcedimiento}</p>
              <span className="text-slate-400">•</span>
              <p className="text-sm text-slate-600">{licitacion.dependencia}</p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-50 transition-colors">
            <ExternalLink className="w-4 h-4" />
            Abrir OneDrive
          </button>
          <button className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-50 transition-colors">
            <ExternalLink className="w-4 h-4" />
            Ver en Libra
          </button>
          <button className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
            <Upload className="w-4 h-4" />
            Subir Documentos
          </button>
        </div>
      </div>

      {requisitosCriticos.length > 0 && (
        <div className="bg-red-50 border-l-4 border-red-500 py-4 px-4 rounded-r-lg">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <h3 className="text-sm font-semibold text-red-900">
                Alertas Críticas ({requisitosCriticos.length})
              </h3>
              <ul className="mt-2 space-y-1">
                {requisitosCriticos.map(req => (
                  <li key={req.id} className="text-sm text-red-800">
                    • {req.descripcion} <span className="text-xs text-red-600">({req.seccion}, pág. {req.pagina})</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-8">
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
            <div className="border-b border-slate-200">
              <div className="flex">
                {(['Técnica', 'Legal/Administrativa', 'Económica'] as TipoPropuesta[]).map(tipo => (
                  <button
                    key={tipo}
                    onClick={() => setPestanaActiva(tipo)}
                    className={`flex-1 px-6 py-4 text-sm font-medium transition-colors ${
                      pestanaActiva === tipo
                        ? 'text-blue-700 border-b-2 border-blue-700 bg-blue-50'
                        : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
                    }`}
                  >
                    Propuesta {tipo}
                  </button>
                ))}
              </div>
            </div>

            <div className="p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-slate-900">
                  Documentos ({documentosPorTipo.length})
                </h3>
                <button className="text-sm text-blue-600 hover:text-blue-700 font-medium">
                  + Agregar Documento
                </button>
              </div>

              {documentosPorTipo.length > 0 ? (
                <div className="space-y-2">
                  {documentosPorTipo.map(doc => (
                    <div
                      key={doc.id}
                      className="flex items-center justify-between py-4 px-4 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
                    >
                      <div className="flex items-center gap-3 flex-1">
                        <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center">
                          <FileText className="w-5 h-5 text-blue-600" />
                        </div>
                        <div className="flex-1">
                          <p className="text-sm font-medium text-slate-900">{doc.nombre}</p>
                          <div className="flex items-center gap-3 mt-1">
                            <span className="text-xs text-slate-500">{doc.tamaño}</span>
                            <span className="text-xs text-slate-400">
                              Subido: {new Intl.DateTimeFormat('es-MX', { day: '2-digit', month: 'short' }).format(doc.fechaSubida)}
                            </span>
                            {doc.salesforceId && (
                              <span className="text-xs text-green-600 flex items-center gap-1">
                                <CheckCircle className="w-3 h-3" />
                                Sync Salesforce
                              </span>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        {doc.verificado ? (
                          <div className="flex items-center gap-1 px-3 py-1 bg-green-100 text-green-700 rounded-full text-xs font-medium">
                            <CheckCircle className="w-3 h-3" />
                            Verificado
                          </div>
                        ) : (
                          <div className="flex items-center gap-1 px-3 py-1 bg-orange-100 text-orange-700 rounded-full text-xs font-medium">
                            <AlertTriangle className="w-3 h-3" />
                            Pendiente
                          </div>
                        )}
                        <button className="p-2 text-slate-600 hover:bg-slate-100 rounded-lg">
                          <Eye className="w-4 h-4" />
                        </button>
                        <button className="p-2 text-slate-600 hover:bg-slate-100 rounded-lg">
                          <Download className="w-4 h-4" />
                        </button>
                        <button className="p-2 text-red-600 hover:bg-red-50 rounded-lg">
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-12 border-2 border-dashed border-slate-200 rounded-lg">
                  <FolderTree className="w-12 h-12 text-slate-300 mx-auto mb-3" />
                  <p className="text-sm text-slate-600 mb-2">No hay documentos en esta categoría</p>
                  <button className="text-sm text-blue-600 hover:text-blue-700 font-medium">
                    Subir primer documento
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="col-span-4">
          <div className="bg-white rounded-xl border border-slate-200 py-6 px-6 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-slate-900">Checklist de Requisitos</h3>
              <div className="text-xs font-semibold text-slate-600">
                {requisitosBase.filter(r => r.verificado).length}/{requisitosBase.length}
              </div>
            </div>

            {requisitosNoVerificados.length > 0 && (
              <div className="mb-4 py-3 px-3 bg-orange-50 border border-orange-200 rounded-lg">
                <p className="text-xs font-semibold text-orange-900">
                  {requisitosNoVerificados.length} requisitos obligatorios pendientes
                </p>
              </div>
            )}

            <div className="space-y-3 max-h-[600px] overflow-y-auto pr-2">
              {requisitosBase.map(req => (
                <div
                  key={req.id}
                  className={`p-3 rounded-lg border ${
                    req.alertaCritica
                      ? 'border-red-300 bg-red-50'
                      : req.verificado
                      ? 'border-green-300 bg-green-50'
                      : 'border-slate-200 bg-white'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <div className="pt-0.5">
                      {req.verificado ? (
                        <CheckCircle className="w-5 h-5 text-green-600" />
                      ) : (
                        <XCircle className="w-5 h-5 text-slate-400" />
                      )}
                    </div>
                    <div className="flex-1">
                      <div className="flex items-start justify-between gap-2 mb-1">
                        <p className="text-sm font-medium text-slate-900">{req.descripcion}</p>
                        {req.esObligatorio && (
                          <span className="text-xs font-semibold text-red-600 flex-shrink-0">OBLIGATORIO</span>
                        )}
                      </div>
                      <p className="text-xs text-slate-600 mb-2">
                        {req.seccion}, Página {req.pagina}
                      </p>
                      {req.documentoAsociado && (
                        <div className="flex items-center gap-1 text-xs text-blue-600">
                          <FileText className="w-3 h-3" />
                          Doc. asociado: {req.documentoAsociado}
                        </div>
                      )}
                      {req.alertaCritica && (
                        <div className="flex items-center gap-1 mt-2 text-xs text-red-700 font-medium">
                          <AlertTriangle className="w-3 h-3" />
                          ALERTA: Causó descalificación en Ipejal
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="bg-slate-900 rounded-xl py-6 px-6 shadow-lg mt-6 text-white">
            <h3 className="text-sm font-semibold mb-3">Almacenamiento</h3>
            <div className="space-y-3">
              <div>
                <div className="flex items-center justify-between text-xs mb-2">
                  <span className="text-slate-300">OneDrive</span>
                  <span className="font-mono">563 GB / 1 TB</span>
                </div>
                <div className="w-full bg-slate-700 rounded-full h-2">
                  <div className="bg-orange-500 h-2 rounded-full" style={{ width: '56%' }}></div>
                </div>
              </div>
              <p className="text-xs text-slate-400">
                Libera espacio archivando licitaciones completadas
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
