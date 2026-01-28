import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Sidebar } from "@/components/layout/Sidebar";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-display",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "Antikythera F1 Video Generator",
  description: "Automated video generation system for satirical F1 commentary videos",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <body className="min-h-screen bg-deep-space font-display text-white antialiased">
        {/* Background effects */}
        <div className="fixed inset-0 -z-10">
          <div className="absolute inset-0 bg-cyber-gradient" />
          <div className="absolute left-1/4 top-0 h-[500px] w-[500px] rounded-full bg-neon-cyan/5 blur-3xl" />
          <div className="absolute right-1/4 bottom-0 h-[500px] w-[500px] rounded-full bg-racing-red/5 blur-3xl" />
          <div className="absolute inset-0 bg-[url('/grid.svg')] bg-repeat opacity-[0.02]" />
        </div>

        <Sidebar />
        <main className="min-h-screen pl-64">
          <div className="p-8">
            {children}
          </div>
        </main>
      </body>
    </html>
  );
}
