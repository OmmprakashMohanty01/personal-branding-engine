import Link from "next/link";

export default function Home() {
  return (
    <div className="max-w-4xl mx-auto mt-12 text-center">
      <div className="border border-gray-800 bg-gray-900/30 backdrop-blur-md rounded-2xl p-12 shadow-2xl relative overflow-hidden">
        {/* Decorative gradient overlay */}
        <div className="absolute -top-24 -left-24 w-48 h-48 bg-indigo-500/10 rounded-full blur-3xl"></div>
        <div className="absolute -bottom-24 -right-24 w-48 h-48 bg-purple-500/10 rounded-full blur-3xl"></div>

        <h1 className="text-3xl font-bold tracking-tight text-white mb-4">
          Dashboard Overview
        </h1>
        
        <p className="text-gray-400 max-w-lg mx-auto mb-8 leading-relaxed">
          The command center dashboard analytics metrics and performance highlights are currently under construction. Please navigate to the Approvals pipeline to curate, optimize, and publish generated brand assets.
        </p>

        <Link
          href="/approvals"
          className="inline-flex items-center justify-center px-6 py-3 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 text-white transition-all duration-200 shadow-lg shadow-indigo-600/20 active:scale-95"
        >
          Go to Approvals
        </Link>
      </div>
    </div>
  );
}
