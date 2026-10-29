import { NextResponse } from "next/server";

// Sin cookie de sesión no se entra: las páginas redirigen al login y las pasarelas responden 401.
// (La validez real de la sesión la comprueba cada pasarela en el servidor.)
export function middleware(req) {
  if (process.env.PANEL_USUARIO_DESARROLLO || req.cookies.has("cerebro_sesion")) return NextResponse.next();
  if (req.nextUrl.pathname.startsWith("/cerebro") || req.nextUrl.pathname.startsWith("/voz") || req.nextUrl.pathname.startsWith("/licitaciones-api")) {
    return NextResponse.json({ error: "Inicia sesión" }, { status: 401 });
  }
  return NextResponse.redirect(new URL("/auth/login", process.env.PANEL_URL || req.url));
}

// La subida de documentos al chat (hasta 25 MB en base64) no pasa por el middleware: Next recorta a 10 MB los cuerpos que lo atraviesan. No se pierde seguridad: la pasarela
// (app/cerebro/[...ruta]/route.js) responde 401 sin sesión válida, igual que el resto de rutas /cerebro.
export const config = { matcher: ["/((?!auth/|_next/|favicon.ico|cerebro/documentos/subir).*)"] };
