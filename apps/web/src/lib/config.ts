export type AuthMode = "clerk" | "dev";

export const config = {
  apiBaseUrl: (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, ""),
  authMode: (process.env.NEXT_PUBLIC_AUTH_MODE === "clerk" ? "clerk" : "dev") as AuthMode,
  clerkPublishableKey: process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ?? "",
};
