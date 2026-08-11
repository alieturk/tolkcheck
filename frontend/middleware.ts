import { NextRequest, NextResponse } from "next/server";

// UX-only redirect: bounces obviously-logged-out visitors to /login before
// they hit a page that will just 401. This does NOT verify the token's
// signature/expiry (that would require duplicating SECRET_KEY into the
// frontend) — the backend's get_current_user dependency remains the actual
// security boundary regardless of what this middleware does or doesn't catch.
const AUTH_COOKIE_NAME = "tolkcheck_session";

export function middleware(request: NextRequest) {
  const hasCookie = request.cookies.has(AUTH_COOKIE_NAME);
  if (!hasCookie) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", request.nextUrl.pathname);
    return NextResponse.redirect(loginUrl);
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    // Exclude the entire /api/backend proxy prefix, not just the login call:
    // API requests must always reach FastAPI (the real auth boundary) so
    // lib/api.ts can handle a 401 cleanly, rather than being intercepted here
    // and redirected to the /login *page* (which would break res.json()
    // parsing on the client for any request racing a just-cleared cookie).
    "/((?!login|api/backend|_next/static|_next/image|favicon.ico).*)",
  ],
};
