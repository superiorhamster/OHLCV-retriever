import React, { useState, useMemo } from 'react';
import { Search, X, Check, Globe, Tag, Layers, CheckSquare, Square, Info } from 'lucide-react';
import { UniverseSymbol } from '../types';

export type SelectionMode = 'single' | 'multiple' | 'all';

interface TickerSelectorProps {
  universe: UniverseSymbol[];
  selectedSymbols: string[];
  selectionMode: SelectionMode;
  onSelectionModeChange: (mode: SelectionMode) => void;
  onSelectedSymbolsChange: (symbols: string[]) => void;
}

const PRESETS = [
  { label: 'Top 5 Blue Chips', symbols: ['REE', 'FPT', 'HPG', 'VNM', 'VHM'] },
  { label: 'VN30 Sample', symbols: ['ACB', 'BID', 'CTG', 'FPT', 'GAS', 'HPG', 'MBB', 'MSN', 'MWG', 'SSI', 'TCB', 'VCB', 'VHM', 'VIC', 'VNM'] },
  { label: 'Historical Delistings', symbols: ['FLC', 'ROS', 'AMD', 'HAI', 'ART', 'KLF', 'GAB', 'TGG', 'BII', 'VKC', 'AGM', 'IBC', 'POM'] }
];

export const TickerSelector: React.FC<TickerSelectorProps> = ({
  universe,
  selectedSymbols,
  selectionMode,
  onSelectionModeChange,
  onSelectedSymbolsChange,
}) => {
  const [search, setSearch] = useState('');
  const [manualInput, setManualInput] = useState('');

  // Filtered universe
  const filteredSymbols = useMemo(() => {
    if (!search.trim()) return universe.slice(0, 50); // initial 50
    const q = search.trim().toUpperCase();
    return universe
      .filter(s => s.symbol.toUpperCase().includes(q) || s.company_name.toUpperCase().includes(q))
      .slice(0, 50);
  }, [universe, search]);

  const toggleSymbol = (sym: string) => {
    if (selectedSymbols.includes(sym)) {
      onSelectedSymbolsChange(selectedSymbols.filter(s => s !== sym));
    } else {
      onSelectedSymbolsChange([...selectedSymbols, sym]);
    }
  };

  const handleSingleSelect = (sym: string) => {
    onSelectedSymbolsChange([sym]);
  };

  const handleManualAdd = (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualInput.trim()) return;
    const added = manualInput
      .split(/[\s,;]+/)
      .map(s => s.trim().toUpperCase())
      .filter(s => s.length > 0);
    const merged = Array.from(new Set([...selectedSymbols, ...added]));
    onSelectedSymbolsChange(merged);
    setManualInput('');
  };

  const applyPreset = (symbols: string[]) => {
    const valid = symbols.filter(s => universe.some(u => u.symbol === s));
    onSelectedSymbolsChange(Array.from(new Set([...selectedSymbols, ...valid])));
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center space-x-2">
          <Layers className="w-5 h-5 text-emerald-400" />
          <h2 className="text-base font-semibold text-white">Target Tickers</h2>
        </div>

        {/* Mode Selector Tabs */}
        <div className="flex p-0.5 bg-slate-950 border border-slate-800 rounded-lg text-xs font-medium">
          <button
            type="button"
            onClick={() => {
              onSelectionModeChange('single');
              if (selectedSymbols.length > 1) onSelectedSymbolsChange([selectedSymbols[0]]);
              else if (selectedSymbols.length === 0 && universe.length > 0) onSelectedSymbolsChange(['FPT']);
            }}
            className={`px-3 py-1.5 rounded-md transition-colors ${
              selectionMode === 'single'
                ? 'bg-emerald-500 text-white font-semibold shadow-sm'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            1 Ticker
          </button>
          <button
            type="button"
            onClick={() => onSelectionModeChange('multiple')}
            className={`px-3 py-1.5 rounded-md transition-colors ${
              selectionMode === 'multiple'
                ? 'bg-emerald-500 text-white font-semibold shadow-sm'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Multiple Tickers
          </button>
          <button
            type="button"
            onClick={() => onSelectionModeChange('all')}
            className={`px-3 py-1.5 rounded-md transition-colors ${
              selectionMode === 'all'
                ? 'bg-emerald-500 text-white font-semibold shadow-sm'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            All HOSE ({universe.length})
          </button>
        </div>
      </div>

      {/* Mode 1: Single Ticker */}
      {selectionMode === 'single' && (
        <div className="space-y-3">
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-3 text-slate-400" />
            <input
              type="text"
              placeholder="Search ticker (e.g., FPT, REE, HPG)..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-9 pr-4 py-2 bg-slate-950 border border-slate-700/80 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500"
            />
          </div>

          {/* Quick choices / Selected ticker badge */}
          <div className="flex flex-wrap gap-2 items-center">
            <span className="text-xs text-slate-400">Selected:</span>
            {selectedSymbols.length > 0 ? (
              <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                {selectedSymbols[0]}
              </span>
            ) : (
              <span className="text-xs text-amber-400">None selected</span>
            )}
          </div>

          {/* Search results list */}
          <div className="max-h-48 overflow-y-auto space-y-1 pr-1 border border-slate-800/80 rounded-lg p-2 bg-slate-950/50">
            {filteredSymbols.map(s => {
              const isSelected = selectedSymbols[0] === s.symbol;
              return (
                <button
                  key={s.symbol}
                  type="button"
                  onClick={() => handleSingleSelect(s.symbol)}
                  className={`w-full flex items-center justify-between px-3 py-1.5 rounded-md text-xs transition-colors ${
                    isSelected
                      ? 'bg-emerald-500/20 text-emerald-200 border border-emerald-500/40 font-semibold'
                      : 'hover:bg-slate-800/70 text-slate-300'
                  }`}
                >
                  <div className="flex items-center space-x-2 truncate">
                    <span className="font-mono font-bold text-white w-12 text-left">{s.symbol}</span>
                    <span className="text-slate-400 truncate max-w-xs">{s.company_name}</span>
                  </div>
                  <div className="flex items-center space-x-2 shrink-0">
                    {s.has_data && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800">
                        {s.row_count} rows
                      </span>
                    )}
                    {s.status !== 'current' && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-950 text-amber-400 border border-amber-800">
                        Delisted
                      </span>
                    )}
                    {isSelected && <Check className="w-3.5 h-3.5 text-emerald-400 ml-1" />}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Mode 2: Multiple Tickers */}
      {selectionMode === 'multiple' && (
        <div className="space-y-4">
          {/* Quick Presets */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate-400">Presets:</span>
            {PRESETS.map(preset => (
              <button
                key={preset.label}
                type="button"
                onClick={() => applyPreset(preset.symbols)}
                className="text-xs px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors"
              >
                + {preset.label}
              </button>
            ))}
            {selectedSymbols.length > 0 && (
              <button
                type="button"
                onClick={() => onSelectedSymbolsChange([])}
                className="text-xs px-2 py-1 text-red-400 hover:text-red-300 ml-auto"
              >
                Clear all ({selectedSymbols.length})
              </button>
            )}
          </div>

          {/* Manual Input form */}
          <form onSubmit={handleManualAdd} className="flex gap-2">
            <input
              type="text"
              placeholder="Add tickers separated by comma (e.g., REE, FPT, HPG)..."
              value={manualInput}
              onChange={e => setManualInput(e.target.value)}
              className="flex-1 px-3 py-1.5 bg-slate-950 border border-slate-700/80 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
            <button
              type="submit"
              className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium rounded-lg border border-slate-700"
            >
              Add
            </button>
          </form>

          {/* Selected Chips */}
          <div className="min-h-12 max-h-32 overflow-y-auto p-2 bg-slate-950/70 border border-slate-800 rounded-lg flex flex-wrap gap-1.5 items-center">
            {selectedSymbols.length === 0 ? (
              <span className="text-xs text-slate-500 italic pl-1">No tickers selected yet. Use presets, manual input, or search below.</span>
            ) : (
              selectedSymbols.map(sym => (
                <span
                  key={sym}
                  className="inline-flex items-center space-x-1 pl-2 pr-1 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 text-xs font-mono font-medium"
                >
                  <span>{sym}</span>
                  <button
                    type="button"
                    onClick={() => toggleSymbol(sym)}
                    className="p-0.5 hover:bg-emerald-500/20 rounded text-emerald-400"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))
            )}
          </div>

          {/* Quick Search & Toggle List */}
          <div className="space-y-2">
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-2.5 text-slate-400" />
              <input
                type="text"
                placeholder="Filter universe to toggle..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="w-full pl-9 pr-3 py-1.5 bg-slate-950 border border-slate-700/80 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              />
            </div>

            <div className="max-h-40 overflow-y-auto grid grid-cols-2 sm:grid-cols-3 gap-1 p-2 bg-slate-950/40 border border-slate-800/80 rounded-lg">
              {filteredSymbols.map(s => {
                const checked = selectedSymbols.includes(s.symbol);
                return (
                  <button
                    key={s.symbol}
                    type="button"
                    onClick={() => toggleSymbol(s.symbol)}
                    className={`flex items-center space-x-2 px-2 py-1 rounded text-xs transition-colors text-left ${
                      checked
                        ? 'bg-emerald-500/20 text-emerald-200 border border-emerald-500/30'
                        : 'hover:bg-slate-800 text-slate-300'
                    }`}
                  >
                    {checked ? (
                      <CheckSquare className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                    ) : (
                      <Square className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                    )}
                    <span className="font-mono font-bold">{s.symbol}</span>
                    {s.has_data && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0"></span>}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Mode 3: All HOSE */}
      {selectionMode === 'all' && (
        <div className="p-4 bg-emerald-500/5 border border-emerald-500/20 rounded-lg space-y-3">
          <div className="flex items-start space-x-3">
            <Globe className="w-5 h-5 text-emerald-400 mt-0.5 shrink-0" />
            <div>
              <h4 className="text-sm font-semibold text-white">Full HOSE Universe Mode</h4>
              <p className="text-xs text-slate-300 mt-1 leading-relaxed">
                Will collect all <strong className="text-emerald-400 font-mono">{universe.length} symbols</strong> tracked in the master universe,
                including active companies and 13 official delisted stocks extracted from HOSE annual reports to eliminate survivorship bias.
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-2 text-xs text-slate-400 bg-slate-950/60 p-2.5 rounded-md border border-slate-800">
            <Info className="w-4 h-4 text-blue-400 shrink-0" />
            <span>Requests will be gracefully rate-limited (0.5s pacing) and cached as immutable SHA-256 JSON responses.</span>
          </div>
        </div>
      )}
    </div>
  );
};
