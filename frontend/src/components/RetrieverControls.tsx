import React, { useState } from 'react';
import { Play, Square, Settings, Calendar, Users, RefreshCw, AlertCircle } from 'lucide-react';
import { StartJobParams } from '../types';

interface RetrieverControlsProps {
  isRunning: boolean;
  selectedCount: number;
  onStart: (params: StartJobParams) => Promise<void>;
  onStop: () => Promise<void>;
}

export const RetrieverControls: React.FC<RetrieverControlsProps> = ({
  isRunning,
  selectedCount,
  onStart,
  onStop,
}) => {
  const [mode, setMode] = useState<'full' | 'update'>('full');
  const [startDate, setStartDate] = useState('2000-07-28');
  const [endDate, setEndDate] = useState(new Date().toISOString().split('T')[0]);
  const [workers, setWorkers] = useState(3);
  const [providers, setProviders] = useState<string[]>(['kbs', 'vci']);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleStart = async () => {
    setErrorMessage(null);
    setIsSubmitting(true);
    try {
      await onStart({
        symbols: [], // Parent will supply selectedSymbols or 'ALL'
        mode,
        start_date: startDate,
        end_date: endDate || undefined,
        workers,
        providers,
      });
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to start collection run');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleStop = async () => {
    try {
      await onStop();
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to stop collection run');
    }
  };

  const setDatePreset = (preset: 'all' | '5y' | '1y' | 'ytd') => {
    const today = new Date();
    setEndDate(today.toISOString().split('T')[0]);
    if (preset === 'all') {
      setStartDate('2000-07-28');
    } else if (preset === '5y') {
      const d = new Date(today);
      d.setFullYear(today.getFullYear() - 5);
      setStartDate(d.toISOString().split('T')[0]);
    } else if (preset === '1y') {
      const d = new Date(today);
      d.setFullYear(today.getFullYear() - 1);
      setStartDate(d.toISOString().split('T')[0]);
    } else if (preset === 'ytd') {
      setStartDate(`${today.getFullYear()}-01-01`);
    }
  };

  const toggleProvider = (p: string) => {
    if (providers.includes(p)) {
      if (providers.length === 1) return; // Keep at least 1
      setProviders(providers.filter(x => x !== p));
    } else {
      setProviders([...providers, p]);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Settings className="w-5 h-5 text-emerald-400" />
          <h2 className="text-base font-semibold text-white">Retrieval Parameters</h2>
        </div>
        <span className="text-xs px-2.5 py-1 rounded-full bg-slate-800 text-slate-300 font-mono">
          {selectedCount} symbol{selectedCount !== 1 ? 's' : ''} queued
        </span>
      </div>

      {/* Mode toggle */}
      <div>
        <label className="text-xs font-semibold text-slate-400 block mb-1.5 uppercase tracking-wider">
          Collection Mode
        </label>
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            disabled={isRunning}
            onClick={() => setMode('full')}
            className={`px-3 py-2 rounded-lg text-xs font-medium border text-left transition-colors ${
              mode === 'full'
                ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300 font-semibold'
                : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
            }`}
          >
            <div className="font-bold">Full Backfill</div>
            <div className="text-[11px] text-slate-400 mt-0.5">Collect entire date window from scratch</div>
          </button>
          <button
            type="button"
            disabled={isRunning}
            onClick={() => setMode('update')}
            className={`px-3 py-2 rounded-lg text-xs font-medium border text-left transition-colors ${
              mode === 'update'
                ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300 font-semibold'
                : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
            }`}
          >
            <div className="font-bold">Incremental Update</div>
            <div className="text-[11px] text-slate-400 mt-0.5">Audit recent 14d & sync only missing rows</div>
          </button>
        </div>
      </div>

      {/* Date Range Pickers & Presets */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center space-x-1.5">
            <Calendar className="w-3.5 h-3.5" />
            <span>Date Range</span>
          </label>
          <div className="flex space-x-1 text-[11px]">
            <button
              type="button"
              onClick={() => setDatePreset('all')}
              className="px-1.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300"
            >
              HOSE (2000)
            </button>
            <button
              type="button"
              onClick={() => setDatePreset('5y')}
              className="px-1.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300"
            >
              5Y
            </button>
            <button
              type="button"
              onClick={() => setDatePreset('1y')}
              className="px-1.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300"
            >
              1Y
            </button>
            <button
              type="button"
              onClick={() => setDatePreset('ytd')}
              className="px-1.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300"
            >
              YTD
            </button>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[11px] text-slate-400 block mb-1">Start Date</label>
            <input
              type="date"
              value={startDate}
              disabled={isRunning}
              onChange={e => setStartDate(e.target.value)}
              className="w-full px-3 py-1.5 bg-slate-950 border border-slate-700/80 rounded-lg text-xs text-white focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </div>
          <div>
            <label className="text-[11px] text-slate-400 block mb-1">End Date</label>
            <input
              type="date"
              value={endDate}
              disabled={isRunning}
              onChange={e => setEndDate(e.target.value)}
              className="w-full px-3 py-1.5 bg-slate-950 border border-slate-700/80 rounded-lg text-xs text-white focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </div>
        </div>
      </div>

      {/* Workers & Providers */}
      <div className="grid grid-cols-2 gap-3 pt-1">
        <div>
          <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center space-x-1.5 mb-1.5">
            <Users className="w-3.5 h-3.5" />
            <span>Workers ({workers})</span>
          </label>
          <input
            type="range"
            min="1"
            max="6"
            step="1"
            value={workers}
            disabled={isRunning}
            onChange={e => setWorkers(parseInt(e.target.value, 10))}
            className="w-full accent-emerald-500"
          />
          <div className="flex justify-between text-[10px] text-slate-500 mt-0.5">
            <span>1 (Gentle)</span>
            <span>3 (Default)</span>
            <span>6 (Fast)</span>
          </div>
        </div>

        <div>
          <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">
            Vendors
          </label>
          <div className="flex space-x-2">
            <button
              type="button"
              disabled={isRunning}
              onClick={() => toggleProvider('kbs')}
              className={`flex-1 py-1.5 rounded-lg text-xs font-mono font-medium border text-center transition-colors ${
                providers.includes('kbs')
                  ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                  : 'bg-slate-950 text-slate-500 border-slate-800'
              }`}
            >
              KBS
            </button>
            <button
              type="button"
              disabled={isRunning}
              onClick={() => toggleProvider('vci')}
              className={`flex-1 py-1.5 rounded-lg text-xs font-mono font-medium border text-center transition-colors ${
                providers.includes('vci')
                  ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                  : 'bg-slate-950 text-slate-500 border-slate-800'
              }`}
            >
              VCI
            </button>
          </div>
        </div>
      </div>

      {/* Error message */}
      {errorMessage && (
        <div className="flex items-start space-x-2 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-xs text-red-400">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Action Buttons */}
      <div className="pt-2">
        {!isRunning ? (
          <button
            type="button"
            disabled={selectedCount === 0 || isSubmitting}
            onClick={handleStart}
            className="w-full flex items-center justify-center space-x-2 py-2.5 px-4 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:pointer-events-none text-white text-sm font-semibold rounded-lg shadow-md transition-colors"
          >
            {isSubmitting ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4 fill-white" />
            )}
            <span>Start Retrieval ({selectedCount} Selected)</span>
          </button>
        ) : (
          <button
            type="button"
            onClick={handleStop}
            className="w-full flex items-center justify-center space-x-2 py-2.5 px-4 bg-red-600 hover:bg-red-500 text-white text-sm font-semibold rounded-lg shadow-md transition-colors animate-pulse"
          >
            <Square className="w-4 h-4 fill-white" />
            <span>Stop Active Retrieval</span>
          </button>
        )}
      </div>
    </div>
  );
};
