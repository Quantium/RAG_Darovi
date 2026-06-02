import { createBrowserRouter } from "react-router";
import { RootPharma } from "./components/pharma/RootPharma";
import { Dashboard } from "./components/pharma/Dashboard";
import { Expediente } from "./components/pharma/Expediente";
import { AsistenteIA } from "./components/pharma/AsistenteIA";
import { Homologacion } from "./components/pharma/Homologacion";
import { Minimaster } from "./components/pharma/Minimaster";
import { JuntasAclaraciones } from "./components/pharma/JuntasAclaraciones";
import { ControlProduccion } from "./components/pharma/ControlProduccion";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: RootPharma,
    children: [
      { index: true, Component: Dashboard },
      { path: "expediente/:id", Component: Expediente },
      { path: "asistente-ia/:id", Component: AsistenteIA },
      { path: "homologacion/:id", Component: Homologacion },
      { path: "minimaster/:id", Component: Minimaster },
      { path: "juntas/:id", Component: JuntasAclaraciones },
      { path: "produccion/:id", Component: ControlProduccion },
    ],
  },
]);
