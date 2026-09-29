import { AuthGate } from "@/components/layout/auth-gate";
import { Sidebar } from "@/components/layout/sidebar";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <AuthGate>
      <div className="flex min-h-screen">
        <Sidebar />
        <main className="min-w-0 flex-1 px-8 py-8">
          <div className="mx-auto max-w-7xl">{children}</div>
        </main>
      </div>
    </AuthGate>
  );
}
