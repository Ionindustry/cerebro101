import { NextResponse } from "next/server";

// Sin cookie de sesión no se entra: las páginas redirigen al login y las pasarelas responden 401.
// (La validez real de la sesión la comprueba cada pasarela en el servidor.)
export function middleware(req) {
  if (process.env.PANEL_USUARIO_DESARROLLO || req.cookies.has("cerebro_sesion")) return NextResponse.next();
  if (req.nextUrl.pathname.startsWith("/cerebro") || req.nextUrl.pathname.startsWith("/voz")) {
    return NextResponse.json({ error: "Inicia sesión" }, { status: 401 });
  }
  return NextResponse.redirect(new URL("/auth/login", process.env.PANEL_URL || req.url));
}

export const config = { matcher: ["/((?!auth/|_next/|favicon.ico).*)"] };
