'use client';

import { useState, useCallback, useRef } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// ─── Types ────────────────────────────────────────────────
interface CharConf { char: string; confidence: number; uncertain: boolean; position: number; }
interface BBox { x1: number; y1: number; x2: number; y2: number; }
interface TagResult {
  normalized_string: string;
  raw_string: string;
  mean_confidence: number;
  character_confidences: CharConf[];
  uncertain_positions: number[];
  bounding_box: BBox;
}
interface AttrResult {
  class_label: string;
  confidence: number;
  is_safety_relevant: boolean;
}
interface InferenceResult {
  job_id: string;
  status: string;
  inspection_id?: string;
  asset_id?: string;
  tags: TagResult[];
  attributes: AttrResult[];
  overall_confidence: number;
  flags: string[];
}
interface Asset {
  id: string;
  normalized_tag: string;
  asset_type: string;
  status: string;
  consensus_score: number;
  location?: { lat: number; lon: number };
}

// ─── Status Helpers ───────────────────────────────────────
const STATUS_COLOR: Record<string, string> = {
  verified: 'bg-green-100 text-green-800 border-green-200',
  active: 'bg-blue-100 text-blue-800 border-blue-200',
  pending: 'bg-yellow-100 text-yellow-800 border-yellow-200',
  disputed: 'bg-red-100 text-red-800 border-red-200',
};

const ATTR_LABELS: Record<string, string> = {
  vegetation_contact: '🌿 Vegetation Contact',
  guy_wire: '〰️ Guy Wire',
  crossarm: '📐 Crossarm',
  transformer: '⚡ Transformer',
  safety_equipment: '🦺 Safety Equipment',
  structural_damage: '⚠️ Structural Damage',
  safety_equipment_missing: '🚨 Safety Equipment Missing',
};

function ConfidenceMeter({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = pct >= 80 ? 'bg-green-500' : pct >= 60 ? 'bg-yellow-500' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
        <div className={`h-full ${color} transition-all duration-500`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-sm font-mono font-semibold text-gray-700 w-10">{pct}%</span>
    </div>
  );
}

function TagDisplay({ tag }: { tag: TagResult }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <h4 className="font-semibold text-gray-700">Detected Tag</h4>
        <span className="text-xs text-gray-400">raw: {tag.raw_string}</span>
      </div>
      <div className="flex flex-wrap gap-0.5 mb-3 font-mono text-xl">
        {tag.character_confidences.map((c, i) => (
          <span
            key={i}
            title={`${c.char}: ${Math.round(c.confidence * 100)}% confidence`}
            className={`px-1 rounded text-center cursor-help ${
              c.uncertain
                ? 'bg-amber-200 text-amber-900 border border-amber-400'
                : 'bg-gray-50 text-gray-900'
            }`}
          >
            {c.char}
          </span>
        ))}
      </div>
      {tag.uncertain_positions.length > 0 && (
        <p className="text-xs text-amber-600 mb-2">
          ⚠️ Amber characters are uncertain — please verify
        </p>
      )}
      <ConfidenceMeter score={tag.mean_confidence} />
    </div>
  );
}

export default function Home() {
  const [tab, setTab] = useState<'inspect' | 'assets'>('inspect');
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<InferenceResult | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [assetsLoading, setAssetsLoading] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validationDone, setValidationDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setFile(f);
    setResult(null);
    setValidationDone(null);
    setError(null);
    const reader = new FileReader();
    reader.onload = (ev) => setPreview(ev.target?.result as string);
    reader.readAsDataURL(f);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f && f.type.startsWith('image/')) {
      setFile(f);
      setResult(null);
      setError(null);
      const reader = new FileReader();
      reader.onload = (ev) => setPreview(ev.target?.result as string);
      reader.readAsDataURL(f);
    }
  }, []);

  const runInspection = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const uploadRes = await fetch(`${API_URL}/api/v1/inspections/upload`, {
        method: 'POST',
        body: formData,
      });
      if (!uploadRes.ok) throw new Error(`Upload failed: ${uploadRes.statusText}`);
      const { job_id, poll_url } = await uploadRes.json();

      // Poll for result
      let attempts = 0;
      while (attempts < 30) {
        await new Promise(r => setTimeout(r, 1500));
        const pollRes = await fetch(`${API_URL}${poll_url}`);
        const job = await pollRes.json();

        if (job.status === 'complete' || job.status === 'no_tag_detected') {
          // Fetch full result with tags
          const fullRes = await fetch(`${API_URL}/api/v1/jobs/${job_id}`);
          const full = await fullRes.json();
          setResult(full);
          setLoading(false);
          return;
        }
        if (job.status === 'failed') {
          throw new Error('Inference failed. Check server logs.');
        }
        attempts++;
      }
      throw new Error('Timed out waiting for result');
    } catch (e: any) {
      setError(e.message);
      setLoading(false);
    }
  };

  const submitValidation = async (action: 'confirm' | 'dispute' | 'edit', correctedTag?: string) => {
    if (!result?.inspection_id) return;
    setValidating(true);
    try {
      const body: any = { action };
      if (action === 'edit' && correctedTag) body.corrected_tag = correctedTag;

      const res = await fetch(`${API_URL}/api/v1/inspections/${result.inspection_id}/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (res.ok) {
        setValidationDone(
          `${action === 'confirm' ? '✅ Confirmed' : action === 'dispute' ? '❌ Disputed' : '✏️ Edit submitted'}! New consensus: ${Math.round(data.new_consensus_score * 100)}%`
        );
      } else {
        setValidationDone(data.detail || 'Already validated');
      }
    } catch (e) {
      setValidationDone('Validation failed');
    }
    setValidating(false);
  };

  const loadAssets = async () => {
    setAssetsLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/assets`);
      const data = await res.json();
      setAssets(data);
    } catch {
      setAssets([]);
    }
    setAssetsLoading(false);
  };

  const handleTabChange = (t: 'inspect' | 'assets') => {
    setTab(t);
    if (t === 'assets') loadAssets();
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
              <span className="text-white font-bold text-sm">P</span>
            </div>
            <div>
              <h1 className="font-bold text-gray-900">PolePad AI</h1>
              <p className="text-xs text-gray-500">Infrastructure Verification</p>
            </div>
          </div>
          <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
            {(['inspect', 'assets'] as const).map(t => (
              <button
                key={t}
                onClick={() => handleTabChange(t)}
                className={`px-4 py-1.5 rounded-md text-sm font-medium transition-all ${
                  tab === t ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {t === 'inspect' ? '📸 New Inspection' : '🗂 Asset Registry'}
              </button>
            ))}
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        {/* ─── INSPECTION TAB ─── */}
        {tab === 'inspect' && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Upload */}
            <div>
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Upload Pole Photo</h2>
              <div
                onDrop={handleDrop}
                onDragOver={e => e.preventDefault()}
                onClick={() => fileInput.current?.click()}
                className="border-2 border-dashed border-gray-300 rounded-xl p-8 text-center cursor-pointer hover:border-blue-400 hover:bg-blue-50 transition-all"
              >
                {preview ? (
                  <img src={preview} alt="Preview" className="max-h-64 mx-auto rounded-lg object-contain" />
                ) : (
                  <div>
                    <p className="text-4xl mb-2">📷</p>
                    <p className="text-gray-600 font-medium">Drop an image or click to upload</p>
                    <p className="text-gray-400 text-sm mt-1">JPEG, PNG, WEBP up to 20MB</p>
                  </div>
                )}
                <input ref={fileInput} type="file" accept="image/*" onChange={handleFileChange} className="hidden" />
              </div>

              {file && (
                <button
                  onClick={runInspection}
                  disabled={loading}
                  className="w-full mt-4 bg-blue-600 text-white py-3 rounded-xl font-semibold hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {loading ? '🔍 Analyzing...' : '🚀 Run AI Inspection'}
                </button>
              )}

              {error && (
                <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
                  {error}
                </div>
              )}

              {loading && (
                <div className="mt-3 p-3 bg-blue-50 border border-blue-200 rounded-lg text-blue-700 text-sm flex items-center gap-2">
                  <span className="animate-spin">⚙️</span>
                  Running YOLO detection and OCR pipeline...
                </div>
              )}
            </div>

            {/* Results */}
            <div>
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Inspection Results</h2>

              {!result && !loading && (
                <div className="border border-gray-200 rounded-xl p-8 text-center text-gray-400">
                  <p className="text-3xl mb-2">🔎</p>
                  <p>Results appear here after inspection</p>
                </div>
              )}

              {result && (
                <div className="space-y-4">
                  {/* Overall confidence */}
                  <div className="bg-white border border-gray-200 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="font-semibold text-gray-700">Overall Confidence</h4>
                      <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${STATUS_COLOR['active']}`}>
                        {result.status}
                      </span>
                    </div>
                    <ConfidenceMeter score={result.overall_confidence} />
                  </div>

                  {/* Tags */}
                  {result.tags?.map((tag, i) => (
                    <TagDisplay key={i} tag={tag} />
                  ))}

                  {result.status === 'no_tag_detected' && (
                    <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-yellow-800">
                      <p className="font-semibold">No tag detected</p>
                      <p className="text-sm mt-1">Try a closer photo with better lighting.</p>
                    </div>
                  )}

                  {/* Attributes */}
                  {result.attributes?.length > 0 && (
                    <div className="bg-white border border-gray-200 rounded-lg p-4">
                      <h4 className="font-semibold text-gray-700 mb-3">Infrastructure Attributes</h4>
                      <div className="space-y-2">
                        {result.attributes.map((attr, i) => (
                          <div key={i} className={`flex items-center justify-between p-2 rounded-lg ${attr.is_safety_relevant ? 'bg-red-50 border border-red-200' : 'bg-gray-50'}`}>
                            <span className="text-sm">
                              {attr.is_safety_relevant && '🚨 '}
                              {ATTR_LABELS[attr.class_label] || attr.class_label}
                            </span>
                            <span className="text-xs text-gray-500 font-mono">
                              {Math.round(attr.confidence * 100)}%
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Validation */}
                  {result.inspection_id && !validationDone && (
                    <div className="bg-white border border-gray-200 rounded-lg p-4">
                      <h4 className="font-semibold text-gray-700 mb-3">Validate This Result</h4>
                      <div className="flex gap-2">
                        <button
                          onClick={() => submitValidation('confirm')}
                          disabled={validating}
                          className="flex-1 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600 disabled:opacity-50 text-sm font-medium"
                        >
                          ✅ Confirm
                        </button>
                        <button
                          onClick={() => submitValidation('dispute')}
                          disabled={validating}
                          className="flex-1 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600 disabled:opacity-50 text-sm font-medium"
                        >
                          ❌ Dispute
                        </button>
                      </div>
                    </div>
                  )}

                  {validationDone && (
                    <div className="bg-green-50 border border-green-200 rounded-lg p-3 text-green-800 text-sm">
                      {validationDone}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ─── ASSETS TAB ─── */}
        {tab === 'assets' && (
          <div>
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-semibold text-gray-900">Asset Registry</h2>
              <button onClick={loadAssets} className="text-sm text-blue-600 hover:underline">↻ Refresh</button>
            </div>

            {assetsLoading && (
              <div className="text-center py-12 text-gray-400">Loading assets...</div>
            )}

            {!assetsLoading && assets.length === 0 && (
              <div className="text-center py-12 text-gray-400">
                <p className="text-3xl mb-2">🗂</p>
                <p>No assets yet. Run an inspection to get started.</p>
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {assets.map(asset => (
                <div key={asset.id} className="bg-white border border-gray-200 rounded-xl p-4 hover:shadow-md transition-shadow">
                  <div className="flex items-start justify-between mb-2">
                    <code className="font-mono font-bold text-gray-900 text-lg">{asset.normalized_tag}</code>
                    <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${STATUS_COLOR[asset.status] || STATUS_COLOR.pending}`}>
                      {asset.status}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500 mb-3 capitalize">{asset.asset_type.replace('_', ' ')}</p>
                  <div className="mb-2">
                    <p className="text-xs text-gray-400 mb-1">Consensus Score</p>
                    <ConfidenceMeter score={asset.consensus_score} />
                  </div>
                  {asset.location?.lat && (
                    <p className="text-xs text-gray-400 mt-2">
                      📍 {asset.location.lat.toFixed(4)}, {asset.location.lon.toFixed(4)}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
