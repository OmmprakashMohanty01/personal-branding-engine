"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function Sidebar() {
  const pathname = usePathname();

  const links = [
    { name: "Dashboard", href: "/" },
  ];

  return (
    <aside className="w-64 border-r border-gray-800 bg-gray-900/40 backdrop-blur-md flex flex-col h-full shrink-0">
      {/* Title / Branding */}
      <div className="p-6 border-b border-gray-800">
        <Link href="/">
          <span className="text-lg font-bold tracking-wider bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-500 bg-clip-text text-transparent block">
            Zero One Command Center
          </span>
        </Link>
      </div>

      {/* Navigation Links */}
      <nav className="flex-1 p-4 space-y-1">
        {links.map((link) => {
          const isActive = pathname === link.href;
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`flex items-center px-4 py-3 rounded-lg text-sm font-medium transition-all duration-200 ${
                isActive
                  ? "bg-indigo-600/25 border border-indigo-500/30 text-indigo-200"
                  : "text-gray-400 hover:bg-gray-800/40 hover:text-gray-200 border border-transparent"
              }`}
            >
              {link.name}
            </Link>
          );
        })}
      </nav>

      {/* Sidebar Footer */}
      <div className="p-6 border-t border-gray-800 text-[10px] text-gray-500">
        <p>© 2026 Personal Branding</p>
        <p className="mt-1">Powered by Render & Neon</p>
      </div>
    </aside>
  );
}
