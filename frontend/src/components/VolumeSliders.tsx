export interface VolumeControls { reference: number; guide: number | null; onReference: (v: number) => void; onGuide: (v: number) => void }

// Reference volume, and the guide level (shown only where it applies: guide null hides it). Values 0…1, sliders in %.
export default function VolumeSliders({ volume }: { volume: VolumeControls }) {
  const pct = (v: number) => Math.round(v * 100)
  return (<>
    {/* blur after a drag so Space/arrows go back to the page shortcuts */}
    <label className="text-xs text-fgdim flex items-center gap-1" title="Reference volume">🔊 {pct(volume.reference)}%
      <input type="range" aria-label="Reference volume" min={0} max={100} step={5} value={pct(volume.reference)}
        onChange={(e) => volume.onReference(Number(e.target.value) / 100)} onPointerUp={(e) => e.currentTarget.blur()} /></label>
    {volume.guide != null && (
      <label className="text-xs text-fgdim flex items-center gap-1" title="Reference level while you speak along, as a share of the reference volume">guide {pct(volume.guide)}%
        <input type="range" aria-label="Guide level" min={0} max={100} step={5} value={pct(volume.guide)}
          onChange={(e) => volume.onGuide(Number(e.target.value) / 100)} onPointerUp={(e) => e.currentTarget.blur()} /></label>)}
  </>)
}
