import "./globals.css";

import type { Metadata } from "next";
import { ThemeProvider } from "next-themes";

import { ThemeToggle } from "@/components/ThemeToggle";

export const metadata: Metadata = {
  title: "Model Pricing — andrea-house",
  description: "Live OpenRouter token pricing vs. Kilo Code plan math",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen font-sans antialiased">
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem>
          <header className="border-b" style={{ borderColor: "rgb(var(--border))" }}>
            <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
              <a href="/" className="font-semibold tracking-tight">
                models.andrea-house.com
              </a>
              <nav className="flex items-center gap-4 text-sm">
                <a href="/" className="hover:underline">Dashboard</a>
                <a href="/trends" className="hover:underline">Trends</a>
                <a href="/about" className="hover:underline">About</a>
                <ThemeToggle />
              </nav>
            </div>
          </header>
          <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
          <footer
            className="mt-12 border-t py-6 text-center text-xs"
            style={{ borderColor: "rgb(var(--border))", color: "rgb(var(--muted))" }}
          >
            OpenRouter feed · Kilo Pass tier math · self-hosted on k8s-home
          </footer>
        </ThemeProvider>
      </body>
    </html>
  );
}
