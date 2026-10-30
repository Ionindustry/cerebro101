// La fuente va DENTRO del paquete (no se descarga de Google al construir): el build no depende de una red externa, que fallaba y dejaba sin publicar la imagen del panel.
import "@fontsource-variable/figtree";
import "./globals.css";
import Rail from "../componentes/Rail";

export const metadata = { title: "Jarvis · Cerebro 101.cat" };

export default function Layout({ children }) {
  return (
    <html lang="es">
      <body>
        <div className="marco">
          <Rail />
          <main className="principal">{children}</main>
        </div>
      </body>
    </html>
  );
}
