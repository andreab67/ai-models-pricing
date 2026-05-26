import "./globals.css";

import type { Metadata } from "next";
import Link from "next/link";
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
          <header className="border-b border-border">
            <div className="mx-auto flex max-w-[1600px] items-center justify-between px-4 py-3">
              <Link href="/" className="font-semibold tracking-tight">
                models.andrea-house.com
              </Link>
              <nav className="flex items-center gap-4 text-sm">
                <Link href="/" className="hover:underline">Dashboard</Link>
                <Link href="/trends" className="hover:underline">All Models</Link>
                <Link href="/about" className="hover:underline">About</Link>
                <ThemeToggle />
              </nav>
            </div>
          </header>
          <main className="mx-auto max-w-[1600px] px-4 py-6">{children}</main>
          <footer className="mt-12 border-t border-border py-6 text-center text-xs text-muted">
            OpenRouter feed · Kilo Pass tier math · self-hosted on k8s-home
          </footer>
        </ThemeProvider>
      </body>
    </html>
  );
}
