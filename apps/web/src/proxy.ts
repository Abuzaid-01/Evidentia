import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

/**
 * Next.js 16 "proxy" (formerly middleware). With Clerk enabled, every page except sign-in requires
 * a session. In local dev mode, identity is handled client-side and the API enforces access.
 */
const isPublic = createRouteMatcher(["/sign-in(.*)", "/sign-up(.*)"]);

export default process.env.NEXT_PUBLIC_AUTH_MODE === "clerk"
  ? clerkMiddleware(async (auth, request) => {
      if (!isPublic(request)) await auth.protect();
    })
  : () => NextResponse.next();

export const config = {
  matcher: ["/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)"],
};
