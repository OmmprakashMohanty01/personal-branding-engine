import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import Sidebar from "@/components/Sidebar";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Zero One Command Center",
  description: "Premium SaaS dashboard for AI Personal Branding Engine",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased dark`}
    >
      <body className="h-full bg-gray-950 text-gray-100 flex overflow-hidden font-sans">
        {/* Sidebar Navigation */}
        <Sidebar />
        
        {/* Main Workspace Area */}
        <div className="flex-1 flex flex-col min-w-0 overflow-y-auto bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-indigo-950/20 via-gray-950 to-gray-950">
          {/* Top Header / Greeting */}
          <header className="border-b border-gray-900 bg-gray-950/50 backdrop-blur-md px-8 py-5 flex items-center justify-between sticky top-0 z-10">
            <span className="text-sm font-medium text-gray-400">
              Welcome back, <span className="text-gray-100 font-semibold">Ommprakash</span>.
            </span>
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-green-500 animate-pulse"></span>
              <span className="text-xs text-gray-400 font-medium">System Online</span>
            </div>
          </header>
          
          {/* View Container */}
          <main className="flex-1 p-8">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
