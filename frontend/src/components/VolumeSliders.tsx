export interface VolumeControls { reference: number; guide: number | null; onReference: (v: number) => void; onGuide: (v: number) => void }

// Speaker (reference) volume, and the guide level (shown only where it applies: guide null hides it). Values 0…1,
// sliders in %. Stacked rows for the Sound pop-up.
export default function VolumeSliders({ volume }: { volume: VolumeControls }) {
  const pct = (v: number) => Math.round(v * 100)
  const row = (label: string, title: string, v: number, on: (v: number) => void) => (
    <label className="block space-y-1" title={title}>
      <span className="flex items-center justify-between"><span className="text-fg">{label}</span><span>{pct(v)}%</span></span>
      {/* blur after a drag so Space/arrows go back to the page shortcuts */}
      <input type="range" className="w-full" aria-label={label} min={0} max={100} step={5} value={pct(v)}
        onChange={(e) => on(Number(e.target.value) / 100)} onPointerUp={(e) => e.currentTarget.blur()} />
    </label>)
  return (<>
    {row('Speaker volume', 'Volume of the speaker (the reference)', volume.reference, volume.onReference)}
    {volume.guide != null && row('Guide level', 'Reference level while you speak along, as a share of the speaker volume', volume.guide, volume.onGuide)}
  </>)
}
