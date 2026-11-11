import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "satushy_session";

export function proxy(request: NextRequest) {
  if (request.cookies.has(SESSION_COOKIE)) return NextResponse.next();
  const login = new URL("/login", request.url);
  login.searchParams.set("next", request.nextUrl.pathname + request.nextUrl.search);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: [
    "/overview",
    "/dialogs",
    "/leads",
    "/products",
    "/bot",
    "/channels",
    "/balance",
    "/settings",
    "/setup",
  ],
};
