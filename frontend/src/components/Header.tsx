import React from 'react';
import { Activity, Database, CheckCircle2, AlertTriangle, Layers } from 'lucide-react';
import { RetrieverStatus } from '../types';

interface HeaderProps {
  status: RetrieverStatus | null;
  totalUniverse: number;
  withDataCount: number;
}

export const Header: React.FC<HeaderProps> = ({ status, totalUniverse, withDataCount }) => {
  const isRunning = status?.is_running ?? false;

  return (
    <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur-md sticky top-0 z-30">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="p-2 bg-emerald-500/10 border border-emerald-500/20 rounded-lg text-emerald-400">
            <Activity className="w-6 h-6 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="text-lg font-bold tracking-tight text-white">HOSE OHLCV Retriever</h1>
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
                v2.0
              </span>
            </div>
            <p className="text-xs text-slate-400">Auditable, Free-Source Historical Vietnamese Equities Data</p>
          </div>
        </div>

        <div className="flex items-center space-x-4">
          {/* Universe & Local Stats */}
          <div className="hidden md:flex items-center space-x-3 text-xs">
            <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded-md bg-slate-800/80 border border-slate-700/60 text-slate-300">
              <Layers className="w-3.5 h-3.5 text-slate-400" />
              <span>Universe: <strong className="text-white">{totalUniverse}</strong></span>
            </div>
            <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded-md bg-slate-800/80 border border-slate-700/60 text-slate-300">
              <Database className="w-3.5 h-3.5 text-emerald-400" />
              <span>Retrieved: <strong className="text-emerald-400">{withDataCount}</strong></span>
            </div>
          </div>

          {/* Engine Status Badge */}
          <div className="flex items-center space-x-2">
            {isRunning ? (
              <div className="flex items-center space-x-1.5 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/30 text-blue-400 text-xs font-medium animate-pulse">
                <span className="w-2 h-2 rounded-full bg-blue-400"></span>
                <span>Collecting: {status?.active_symbols.join(', ') || 'In Progress'}</span>
              </div>
            ) : (
              <div className="flex items-center space-x-1.5 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-medium">
                <CheckCircle2 className="w-3.5 h-3.5" />
                <span>Engine Ready</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
};
