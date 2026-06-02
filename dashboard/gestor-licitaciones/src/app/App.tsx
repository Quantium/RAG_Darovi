import { RouterProvider } from 'react-router';
import { router } from './routes';
import { FuenteProvider } from './context/FuenteContext';

export default function App() {
  return (
    <FuenteProvider>
      <RouterProvider router={router} />
    </FuenteProvider>
  );
}