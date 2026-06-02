export type EstatusLicitacion =
  | 'Identificación'
  | 'Análisis de Factibilidad'
  | 'Armado de Propuestas'
  | 'Presentación'
  | 'Fallo';

export type TipoPropuesta = 'Técnica' | 'Legal/Administrativa' | 'Económica';

export type EmpresaPadron = 'Darovi' | 'Carelab' | 'Fretrade' | 'Qualys';

export interface Licitacion {
  id: string;
  numeroProcedimiento: string;
  dependencia: string;
  descripcion: string;
  estatus: EstatusLicitacion;
  fechaLimite: Date;
  plataforma: 'Licitacom' | 'ComprasMX' | 'Otra';
  prioridad: 'Alta' | 'Media' | 'Baja';
  valorEstimado: number;
  documentosCount: number;
  alertas: number;
}

export interface Padron {
  id: string;
  empresa: EmpresaPadron;
  dependencia: string;
  fechaInicio: Date;
  tiempoEstimado: string;
  progreso: number;
  estatus: 'En proceso' | 'Pendiente' | 'Completado' | 'Observaciones';
}

export interface Documento {
  id: string;
  nombre: string;
  tipo: TipoPropuesta;
  tamaño: string;
  fechaSubida: Date;
  verificado: boolean;
  ubicacionOneDrive: string;
  salesforceId?: string;
}

export interface RequisitoBase {
  id: string;
  seccion: string;
  pagina: number;
  descripcion: string;
  esObligatorio: boolean;
  verificado: boolean;
  documentoAsociado?: string;
  alertaCritica: boolean;
}

export interface AlertaIA {
  id: string;
  tipo: 'Ambigüedad' | 'Fecha Crítica' | 'Requisito Oculto' | 'Inconsistencia';
  severidad: 'Alta' | 'Media' | 'Baja';
  ubicacion: string;
  descripcion: string;
  textoOriginal: string;
  recomendacion: string;
}

export interface ItemCatalogo {
  id: string;
  claveCliente: string;
  descripcionCliente: string;
  claveDarovi?: string;
  descripcionDarovi?: string;
  coincidencia: number;
  validado: boolean;
  discrepancias: string[];
}

export interface RegistroSanitario {
  id: string;
  producto: string;
  clave: string;
  fabricante: string;
  registroSanitario: string;
  estatusCalidad: 'Aprobado' | 'Pendiente' | 'Faltante' | 'Inconsistencia';
  fechaVigencia?: Date;
  observaciones?: string;
}

export interface PreguntaAclaracion {
  id: string;
  area: 'Finanzas' | 'Tráfico' | 'Calidad' | 'Legal' | 'Operaciones';
  referenciaBase: string;
  pregunta: string;
  respondida: boolean;
  respuesta?: string;
  fechaCreacion: Date;
}

export interface TareaProduccion {
  id: string;
  tipo: 'Impresión' | 'Foliado' | 'Rúbrica' | 'Escaneo' | 'Empaquetado';
  licitacionId: string;
  totalHojas: number;
  progreso: number;
  responsable: string;
  verificado: boolean;
  observaciones?: string;
}
