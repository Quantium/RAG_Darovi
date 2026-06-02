import { createContext, useContext, useState, ReactNode } from 'react';

export type FuenteDatos = 'Laboratorios' | 'Licitaciones' | 'SSJAL';

interface FuenteContextType {
  fuenteSeleccionada: FuenteDatos;
  setFuenteSeleccionada: (fuente: FuenteDatos) => void;
}

const FuenteContext = createContext<FuenteContextType | undefined>(undefined);

export function FuenteProvider({ children }: { children: ReactNode }) {
  const [fuenteSeleccionada, setFuenteSeleccionada] = useState<FuenteDatos>('Licitaciones');

  return (
    <FuenteContext.Provider value={{ fuenteSeleccionada, setFuenteSeleccionada }}>
      {children}
    </FuenteContext.Provider>
  );
}

export function useFuente() {
  const context = useContext(FuenteContext);
  if (context === undefined) {
    throw new Error('useFuente debe usarse dentro de un FuenteProvider');
  }
  return context;
}
