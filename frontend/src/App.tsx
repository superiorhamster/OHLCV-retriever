import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Header } from './components/Header';
import { TickerSelector, SelectionMode } from './components/TickerSelector';
import { RetrieverControls } from './components/RetrieverControls';
import { LiveProgress } from './components/LiveProgress';
import { DataPreviewer } from './components/DataPreviewer';
import { UniverseSymbol, RetrieverStatus, StartJobParams } from './types';
import { fetchUniverse, fetchRetrieverStatus, startRetriever, stopRetriever } from './api';

export const App: React.FC = () => {
  const [universe, setUniverse] = useState<UniverseSymbol[]>([]);
  const [status, setStatus] = useState<RetrieverStatus | null>(null);
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>(['FPT']);
  const [selectionMode, setSelectionMode] = useState<SelectionMode>('single');
  const [previewSymbol, setPreviewSymbol] = useState<string>('FPT');
  const [loadingUniverse, setLoadingUniverse] = useState(true);

  const prevIsRunning = useRef(false);

  // Load universe
  const loadUniverse = useCallback(async () => {
    try {
      const data = await fetchUniverse();
      setUniverse(data.symbols);
      // If no preview symbol selected or current preview not in list, default to first retrieved
      const retrieved = data.symbols.filter(s => s.has_data);
      if (retrieved.length > 0 && !data.symbols.some(s => s.symbol === previewSymbol && s.has_data)) {
        setPreviewSymbol(retrieved[0].symbol);
      }
    } catch (err) {
      console.error('Failed to load universe:', err);
    } finally {
      setLoadingUniverse(false);
    }
  }, [previewSymbol]);

  // Load status
  const loadStatus = useCallback(async () => {
    try {
      const st = await fetchRetrieverStatus();
      setStatus(st);

      // Detect transition from running to idle: reload universe to get updated data counts!
      if (prevIsRunning.current && !st.is_running) {
        loadUniverse();
      }
      prevIsRunning.current = st.is_running;
    } catch (err) {
      console.error('Failed to load status:', err);
    }
  }, [loadUniverse]);

  // Initial load
  useEffect(() => {
    loadUniverse();
    loadStatus();
  }, [loadUniverse, loadStatus]);

  // Polling loop for status
  useEffect(() => {
    const interval = status?.is_running ? 1500 : 5000;
    const timer = setInterval(() => {
      loadStatus();
    }, interval);

    return () => clearInterval(timer);
  }, [status?.is_running, loadStatus]);

  // Handle start retrieval
  const handleStart = async (params: StartJobParams) => {
    const targetSymbols = selectionMode === 'all' ? 'ALL' : selectedSymbols;
    if (selectionMode !== 'all' && selectedSymbols.length === 0) {
      throw new Error('Please select at least one ticker.');
    }

    await startRetriever({
      ...params,
      symbols: targetSymbols,
    });

    // Immediate status check
    await loadStatus();
  };

  // Handle stop retrieval
  const handleStop = async () => {
    await stopRetriever();
    await loadStatus();
  };

  const isRunning = status?.is_running ?? false;
  const targetCount = selectionMode === 'all' ? universe.length : selectedSymbols.length;
  const withDataCount = universe.filter(s => s.has_data).length;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Header
        status={status}
        totalUniverse={universe.length}
        withDataCount={withDataCount}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {loadingUniverse ? (
          <div className="py-20 text-center space-y-3">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-emerald-500 mx-auto"></div>
            <p className="text-sm text-slate-400">Loading HOSE Master Universe & Data Cache...</p>
          </div>
        ) : (
          <>
            {/* Top Grid: Ticker Selector & Retriever Controls */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              <div className="lg:col-span-7">
                <TickerSelector
                  universe={universe}
                  selectedSymbols={selectedSymbols}
                  selectionMode={selectionMode}
                  onSelectionModeChange={setSelectionMode}
                  onSelectedSymbolsChange={setSelectedSymbols}
                />
              </div>

              <div className="lg:col-span-5">
                <RetrieverControls
                  isRunning={isRunning}
                  selectedCount={targetCount}
                  onStart={handleStart}
                  onStop={handleStop}
                />
              </div>
            </div>

            {/* Middle Section: Live Progress & Terminal Logs */}
            <LiveProgress status={status} />

            {/* Bottom Section: Data Previewer (Head / Tail / Table / Chart) */}
            <DataPreviewer
              universe={universe}
              selectedSymbol={previewSymbol}
              onSelectSymbol={setPreviewSymbol}
            />
          </>
        )}
      </main>

      <footer className="border-t border-slate-900 py-4 text-center text-xs text-slate-600">
        HOSE OHLCV Retriever v2.0 • Auditable historical data with survivorship-bias mitigation
      </footer>
    </div>
  );
};
export default App;
