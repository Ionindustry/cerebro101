import { Figtree } from "next/font/google";
import "./globals.css";
import Rail from "../componentes/Rail";

const figtree = Figtree({ subsets: ["latin"], weight: ["300", "400", "500", "600", "700"] });

export const metadata = { title: "Jarvis · Cerebro 101.cat" };

export default function Layout({ children }) {
  return (
    <html lang="es" className={figtree.className}>
      <body>
        <div className="marco">
          <Rail />
          <main className="principal">{children}</main>
        </div>
      </body>
    </html>
  );
}
