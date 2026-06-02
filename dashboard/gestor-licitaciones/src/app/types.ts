export type EstadoLicitacion = 'Borrador' | 'Publicada' | 'En Evaluación' | 'Cerrada' | 'Adjudicada';

export interface Licitacion {
  id: string;
  titulo: string;
  descripcion: string;
  estado: EstadoLicitacion;
  fechaPublicacion: Date;
  fechaCierre: Date;
  presupuesto: number;
  ofertas: number;
  progreso: number;
  urgente?: boolean;
}

export interface Proveedor {
  id: string;
  nombre: string;
  rut: string;
  email: string;
}

export interface Oferta {
  id: string;
  proveedorId: string;
  licitacionId: string;
  precio: number;
  tiempoEntrega: number;
  garantia: number;
  calidad: number;
  items: ItemOferta[];
  documentos: string[];
}

export interface ItemOferta {
  id: string;
  descripcion: string;
  cantidad: number;
  precioUnitario: number;
  total: number;
}

export interface Mensaje {
  id: string;
  proveedorId: string;
  licitacionId: string;
  fecha: Date;
  pregunta: string;
  respuesta?: string;
  publico: boolean;
  adjuntos: string[];
}
