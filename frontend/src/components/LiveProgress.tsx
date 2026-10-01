import React, { useState, useEffect, useRef } from 'react';
import { Terminal, CheckCircle2, Clock, AlertTriangle, XCircle, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react';
import { RetrieverStatus } from '../types';

interface LiveProgressProps {
  status: RetrieverStatus | null;
}

export const LiveProgress: React.FC<LiveProgressProps> = ({ status }) => {
  const [logsExpanded, setLogsExpanded] = useState(true);
  const logContainerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll logs to bottom
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [status?.logs]);

  if (!status) return null;

  const total = status.total_targets || 1;
  const done = status.counts.DONE || 0;
  const partial = status.counts.PARTIAL || 0;
  const failed = status.counts.FAILED || 0;
  const running = status.counts.RUNNING || 0;
  const pending = status.counts.PENDING || 0;

  const finishedCount = done + partial + failed;
  const percent = status.total_targets > 0 ? Math.min(100, Math.round((finishedCount / total) * 100)) : (status.is_running ? 50 : 100);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Terminal className="w-5 h-5 text-emerald-400" />
          <h2 className="text-base font-semibold text-white">Execution Progress</h2>
        </div>
        <div className="flex items-center space-x-2 text-xs">
          <span className="text-slate-400">Run ID:</span>
          <span className="font-mono text-emerald-300 font-medium px-2 py-0.5 rounded bg-slate-950 border border-slate-800">
            {status.run_id}
          </span>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="space-y-1.5">
        <div className="flex justify-between text-xs">
          <span className="text-slate-400 font-medium">
            {status.is_running ? (
              <span className="flex items-center space-x-1.5 text-blue-400 font-semibold animate-pulse">
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                <span>Collecting: {finishedCount} / {total} tickers ({percent}%)</span>
              </span>
            ) : (
              <span>Completed ({finishedCount} / {total} tickers)</span>
            )}
          </span>
          <span className="font-mono text-white font-bold">{percent}%</span>
        </div>
        <div className="w-full h-2.5 bg-slate-950 rounded-full overflow-hidden border border-slate-800">
          <div
            className={`h-full transition-all duration-300 ${
              status.is_running ? 'bg-gradient-to-r from-emerald-500 to-blue-500' : 'bg-emerald-500'
            }`}
            style={{ width: `${percent}%` }}
          ></div>
        </div>
      </div>

      {/* Counts Badges */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
        <div className="p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-center">
          <div className="text-[10px] text-emerald-400 uppercase font-semibold flex items-center justify-center space-x-1">
            <CheckCircle2 className="w-3 h-3" />
            <span>Done</span>
          </div>
          <div className="text-lg font-bold font-mono text-emerald-300 mt-0.5">{done}</div>
        </div>

        <div className="p-2.5 rounded-lg bg-blue-500/10 border border-blue-500/20 text-center">
          <div className="text-[10px] text-blue-400 uppercase font-semibold flex items-center justify-center space-x-1">
            <RefreshCw className={`w-3 h-3 ${running > 0 ? 'animate-spin' : ''}`} />
            <span>Running</span>
          </div>
          <div className="text-lg font-bold font-mono text-blue-300 mt-0.5">{running}</div>
        </div>

        <div className="p-2.5 rounded-lg bg-slate-800/60 border border-slate-700/60 text-center">
          <div className="text-[10px] text-slate-400 uppercase font-semibold flex items-center justify-center space-x-1">
            <Clock className="w-3 h-3" />
            <span>Pending</span>
          </div>
          <div className="text-lg font-bold font-mono text-slate-300 mt-0.5">{pending}</div>
        </div>

        <div className="p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-center">
          <div className="text-[10px] text-amber-400 uppercase font-semibold flex items-center justify-center space-x-1">
            <AlertTriangle className="w-3 h-3" />
            <span>Partial</span>
          </div>
          <div className="text-lg font-bold font-mono text-amber-300 mt-0.5">{partial}</div>
        </div>

        <div className="p-2.5 rounded-lg bg-red-500/10 border border-red-500/20 text-center col-span-2 sm:col-span-1">
          <div className="text-[10px] text-red-400 uppercase font-semibold flex items-center justify-center space-x-1">
            <XCircle className="w-3 h-3" />
            <span>Failed</span>
          </div>
          <div className="text-lg font-bold font-mono text-red-300 mt-0.5">{failed}</div>
        </div>
      </div>

      {/* Active Symbols */}
      {status.active_symbols.length > 0 && (
        <div className="flex items-center space-x-2 text-xs">
          <span className="text-slate-400">In-Flight:</span>
          <div className="flex flex-wrap gap-1">
            {status.active_symbols.map(sym => (
              <span
                key={sym}
                className="px-2 py-0.5 rounded bg-blue-500/20 text-blue-300 border border-blue-500/40 font-mono font-bold text-[11px] animate-pulse"
              >
                {sym}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Live Log Console */}
      <div className="border border-slate-800 rounded-lg overflow-hidden bg-slate-950">
        <button
          type="button"
          onClick={() => setLogsExpanded(!logsExpanded)}
          className="w-full flex items-center justify-between px-3 py-2 bg-slate-900/60 hover:bg-slate-900 border-b border-slate-800 text-xs font-medium text-slate-300"
        >
          <div className="flex items-center space-x-2">
            <Terminal className="w-3.5 h-3.5 text-slate-400" />
            <span>Live Collector Output ({status.logs.length} lines)</span>
          </div>
          {logsExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>

        {logsExpanded && (
          <div
            ref={logContainerRef}
            className="p-3 font-mono text-[11px] h-44 overflow-y-auto space-y-1 bg-black/40 text-slate-300 select-text"
          >
            {status.logs.length === 0 ? (
              <div className="text-slate-600 italic">No output received yet. Start a retrieval job to view live logs.</div>
            ) : (
              status.logs.map((log, idx) => {
                let colorClass = 'text-slate-300';
                if (log.level === 'WARNING') colorClass = 'text-amber-400';
                else if (log.level === 'ERROR') colorClass = 'text-red-400';
                else if (log.level === 'INFO') colorClass = 'text-emerald-400/90';

                return (
                  <div key={idx} className="leading-tight flex space-x-2 hover:bg-slate-900/40 rounded px-1">
                    <span className="text-slate-600 shrink-0">{log.time}</span>
                    <span className={`shrink-0 font-bold w-14 ${colorClass}`}>[{log.level}]</span>
                    <span className="text-slate-300 break-all">{log.message}</span>
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>
    </div>
  );
};
