import { useParams, Link } from 'react-router';
import { ofertas, proveedores, licitaciones } from '../data/mockData';
import { ArrowLeft, Download, FileText, TrendingUp, TrendingDown } from 'lucide-react';
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, Legend } from 'recharts';

export function ComparativaOfertas() {
  const { id } = useParams();
  const licitacion = licitaciones.find(l => l.id === id);
  const ofertasLicitacion = ofertas.filter(o => o.licitacionId === id);

  if (!licitacion) {
    return (
      <div className="text-center py-12">
        <p className="text-slate-600">Licitación no encontrada</p>
      </div>
    );
  }

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('es-CL', {
      style: 'currency',
      currency: 'CLP',
      minimumFractionDigits: 0,
    }).format(amount);
  };

  const precioMinimo = Math.min(...ofertasLicitacion.map(o => o.precio));
  const precioMaximo = Math.max(...ofertasLicitacion.map(o => o.precio));

  const getPrecioColor = (precio: number) => {
    if (precio === precioMinimo) return 'bg-green-50 text-green-900 font-semibold';
    if (precio > licitacion.presupuesto) return 'bg-red-50 text-red-900';
    return 'bg-white text-slate-900';
  };

  const getMetricColor = (value: number, metric: 'tiempoEntrega' | 'garantia' | 'calidad') => {
    const valores = ofertasLicitacion.map(o => o[metric]);
    const mejor = metric === 'tiempoEntrega' ? Math.min(...valores) : Math.max(...valores);
    const peor = metric === 'tiempoEntrega' ? Math.max(...valores) : Math.min(...valores);

    if (value === mejor) return 'bg-green-50 text-green-900 font-semibold';
    if (value === peor) return 'bg-yellow-50 text-yellow-900';
    return 'bg-white text-slate-900';
  };

  const top3Ofertas = [...ofertasLicitacion].sort((a, b) => a.precio - b.precio).slice(0, 3);

  const radarData = [
    {
      criterio: 'Precio',
      [proveedores.find(p => p.id === top3Ofertas[0]?.proveedorId)?.nombre || '']:
        Math.round((1 - (top3Ofertas[0]?.precio - precioMinimo) / (precioMaximo - precioMinimo)) * 100),
      [proveedores.find(p => p.id === top3Ofertas[1]?.proveedorId)?.nombre || '']:
        Math.round((1 - (top3Ofertas[1]?.precio - precioMinimo) / (precioMaximo - precioMinimo)) * 100),
      [proveedores.find(p => p.id === top3Ofertas[2]?.proveedorId)?.nombre || '']:
        Math.round((1 - (top3Ofertas[2]?.precio - precioMinimo) / (precioMaximo - precioMinimo)) * 100),
    },
    {
      criterio: 'Tiempo',
      [proveedores.find(p => p.id === top3Ofertas[0]?.proveedorId)?.nombre || '']:
        Math.round((1 - top3Ofertas[0]?.tiempoEntrega / 60) * 100),
      [proveedores.find(p => p.id === top3Ofertas[1]?.proveedorId)?.nombre || '']:
        Math.round((1 - top3Ofertas[1]?.tiempoEntrega / 60) * 100),
      [proveedores.find(p => p.id === top3Ofertas[2]?.proveedorId)?.nombre || '']:
        Math.round((1 - top3Ofertas[2]?.tiempoEntrega / 60) * 100),
    },
    {
      criterio: 'Calidad',
      [proveedores.find(p => p.id === top3Ofertas[0]?.proveedorId)?.nombre || '']: top3Ofertas[0]?.calidad || 0,
      [proveedores.find(p => p.id === top3Ofertas[1]?.proveedorId)?.nombre || '']: top3Ofertas[1]?.calidad || 0,
      [proveedores.find(p => p.id === top3Ofertas[2]?.proveedorId)?.nombre || '']: top3Ofertas[2]?.calidad || 0,
    },
    {
      criterio: 'Garantía',
      [proveedores.find(p => p.id === top3Ofertas[0]?.proveedorId)?.nombre || '']:
        Math.round((top3Ofertas[0]?.garantia / 60) * 100),
      [proveedores.find(p => p.id === top3Ofertas[1]?.proveedorId)?.nombre || '']:
        Math.round((top3Ofertas[1]?.garantia / 60) * 100),
      [proveedores.find(p => p.id === top3Ofertas[2]?.proveedorId)?.nombre || '']:
        Math.round((top3Ofertas[2]?.garantia / 60) * 100),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/licitaciones" className="p-2 hover:bg-slate-100 rounded-lg transition-colors">
            <ArrowLeft className="w-5 h-5 text-slate-600" />
          </Link>
          <div>
            <h2 className="text-2xl font-semibold text-slate-900">Comparativa de Ofertas</h2>
            <p className="text-slate-600 mt-1">{licitacion.id} - {licitacion.titulo}</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-50 transition-colors">
            <Download className="w-4 h-4" />
            Exportar Análisis
          </button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <p className="text-sm text-slate-600">Presupuesto Base</p>
          <p className="text-2xl font-semibold text-slate-900 mt-1">{formatCurrency(licitacion.presupuesto)}</p>
        </div>
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <p className="text-sm text-slate-600">Mejor Oferta</p>
          <div className="flex items-center gap-2 mt-1">
            <p className="text-2xl font-semibold text-green-700">{formatCurrency(precioMinimo)}</p>
            <TrendingDown className="w-5 h-5 text-green-600" />
          </div>
        </div>
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <p className="text-sm text-slate-600">Total Ofertas</p>
          <p className="text-2xl font-semibold text-slate-900 mt-1">{ofertasLicitacion.length}</p>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 p-6">
        <h3 className="text-lg font-semibold text-slate-900 mb-4">Análisis Top 3 Proveedores</h3>
        <ResponsiveContainer width="100%" height={400}>
          <RadarChart data={radarData}>
            <PolarGrid stroke="#e2e8f0" />
            <PolarAngleAxis dataKey="criterio" tick={{ fill: '#64748b', fontSize: 12 }} />
            <PolarRadiusAxis angle={90} domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 10 }} />
            <Radar
              name={proveedores.find(p => p.id === top3Ofertas[0]?.proveedorId)?.nombre}
              dataKey={proveedores.find(p => p.id === top3Ofertas[0]?.proveedorId)?.nombre || ''}
              stroke="#3b82f6"
              fill="#3b82f6"
              fillOpacity={0.3}
            />
            <Radar
              name={proveedores.find(p => p.id === top3Ofertas[1]?.proveedorId)?.nombre}
              dataKey={proveedores.find(p => p.id === top3Ofertas[1]?.proveedorId)?.nombre || ''}
              stroke="#10b981"
              fill="#10b981"
              fillOpacity={0.3}
            />
            <Radar
              name={proveedores.find(p => p.id === top3Ofertas[2]?.proveedorId)?.nombre}
              dataKey={proveedores.find(p => p.id === top3Ofertas[2]?.proveedorId)?.nombre || ''}
              stroke="#f59e0b"
              fill="#f59e0b"
              fillOpacity={0.3}
            />
            <Legend wrapperStyle={{ fontSize: '12px' }} />
          </RadarChart>
        </ResponsiveContainer>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-slate-50 border-b border-slate-200 sticky top-0">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider sticky left-0 bg-slate-50 z-10">
                  Criterio
                </th>
                {ofertasLicitacion.map((oferta) => {
                  const proveedor = proveedores.find(p => p.id === oferta.proveedorId);
                  return (
                    <th key={oferta.id} className="px-6 py-3 text-left border-l border-slate-200">
                      <div className="space-y-1">
                        <p className="text-sm font-semibold text-slate-900">{proveedor?.nombre}</p>
                        <p className="text-xs text-slate-500 font-normal">{proveedor?.rut}</p>
                        <div className="flex gap-1 mt-2">
                          {oferta.documentos.map((doc, idx) => (
                            <span key={idx} className="inline-flex items-center gap-1 px-2 py-1 bg-blue-50 text-blue-700 rounded text-xs">
                              <FileText className="w-3 h-3" />
                              {idx + 1}
                            </span>
                          ))}
                        </div>
                      </div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              <tr className="hover:bg-slate-50">
                <td className="px-6 py-4 font-medium text-slate-900 sticky left-0 bg-white">
                  Precio Total
                </td>
                {ofertasLicitacion.map((oferta) => (
                  <td key={oferta.id} className={`px-6 py-4 border-l border-slate-200 ${getPrecioColor(oferta.precio)}`}>
                    <div className="flex items-center justify-between">
                      <span className="font-medium">{formatCurrency(oferta.precio)}</span>
                      {oferta.precio > licitacion.presupuesto && (
                        <TrendingUp className="w-4 h-4 text-red-600" />
                      )}
                    </div>
                    <p className="text-xs text-slate-500 mt-1">
                      {oferta.precio > licitacion.presupuesto
                        ? `+${formatCurrency(oferta.precio - licitacion.presupuesto)}`
                        : `${formatCurrency(licitacion.presupuesto - oferta.precio)} bajo presupuesto`
                      }
                    </p>
                  </td>
                ))}
              </tr>

              <tr className="hover:bg-slate-50">
                <td className="px-6 py-4 font-medium text-slate-900 sticky left-0 bg-white">
                  Tiempo de Entrega
                </td>
                {ofertasLicitacion.map((oferta) => (
                  <td key={oferta.id} className={`px-6 py-4 border-l border-slate-200 ${getMetricColor(oferta.tiempoEntrega, 'tiempoEntrega')}`}>
                    <span className="font-medium">{oferta.tiempoEntrega} días</span>
                  </td>
                ))}
              </tr>

              <tr className="hover:bg-slate-50">
                <td className="px-6 py-4 font-medium text-slate-900 sticky left-0 bg-white">
                  Garantía
                </td>
                {ofertasLicitacion.map((oferta) => (
                  <td key={oferta.id} className={`px-6 py-4 border-l border-slate-200 ${getMetricColor(oferta.garantia, 'garantia')}`}>
                    <span className="font-medium">{oferta.garantia} meses</span>
                  </td>
                ))}
              </tr>

              <tr className="hover:bg-slate-50">
                <td className="px-6 py-4 font-medium text-slate-900 sticky left-0 bg-white">
                  Calificación Calidad
                </td>
                {ofertasLicitacion.map((oferta) => (
                  <td key={oferta.id} className={`px-6 py-4 border-l border-slate-200 ${getMetricColor(oferta.calidad, 'calidad')}`}>
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{oferta.calidad}/100</span>
                      <div className="w-24 bg-slate-200 rounded-full h-2">
                        <div
                          className="bg-blue-600 h-2 rounded-full"
                          style={{ width: `${oferta.calidad}%` }}
                        ></div>
                      </div>
                    </div>
                  </td>
                ))}
              </tr>

              {ofertasLicitacion[0]?.items.map((item, idx) => (
                <tr key={item.id} className="hover:bg-slate-50">
                  <td className="px-6 py-4 sticky left-0 bg-white">
                    <p className="font-medium text-slate-900">{item.descripcion}</p>
                    <p className="text-xs text-slate-500 mt-1">Cantidad: {item.cantidad}</p>
                  </td>
                  {ofertasLicitacion.map((oferta) => {
                    const ofertaItem = oferta.items[idx];
                    return (
                      <td key={oferta.id} className="px-6 py-4 border-l border-slate-200">
                        <div className="space-y-1">
                          <p className="text-sm font-medium text-slate-900">{formatCurrency(ofertaItem?.precioUnitario || 0)}</p>
                          <p className="text-xs text-slate-500">Total: {formatCurrency(ofertaItem?.total || 0)}</p>
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
