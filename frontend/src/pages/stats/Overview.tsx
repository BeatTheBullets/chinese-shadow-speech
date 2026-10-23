import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import type { StatsOverview } from '../../api/types'
import Shell from '../../components/Shell'
import ScoreCard from '../../components/stats/ScoreCard'
import Widget, { Bar } from '../../components/stats/Widget'
import { pct } from '../../lib/score'
import { HOW, UNIT, changeText, scoreText } from '../../lib/statsView'
import Card from '../../ui/Card'

const AREAS = [['characters', 'Characters'], ['tones', 'Tones'], ['sounds', 'Sounds']] as const

export default function Overview() {
  const [data, setData] = useState<StatsOverview | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const nav = useNavigate()
  useEffect(() => { api.stats.overview().then(setData).catch((e: unknown) => { setErr(e instanceof Error ? e.message : String(e)) }) }, [])

  let body
  if (err) body = <p className="text-bad">Could not load stats: {err}</p>
  else if (!data) body = <p className="text-fgdim">Loading…</p>
  else {
    const { scores, flow, weakest, activity, sentences, drills } = data
    const none = AREAS.every(([k]) => scores[k].n === 0)
    body = (
      <>
        {none && <p className="text-fgdim">Practise a few sentences to see your scores.</p>}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {AREAS.map(([k, title]) => <ScoreCard key={k} title={title} score={scores[k]} unit={UNIT[k]} how={HOW[k]} to={`/stats/${k}`} />)}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Widget title="Weakest characters" to="/stats/characters" allLabel="all characters" empty="No characters yet.">
            {weakest.characters.map((c) => (
              <div key={c.ch} className="flex items-center gap-3">
                <span className="font-hanzi text-xl text-fg">{c.ch}</span>
                <span className="text-sm text-fgdim">{c.pinyin}</span>
                <span className="ml-auto flex items-center gap-2"><Bar value={c.score} /><span className="text-sm text-fg w-8 text-right">{pct(c.score)}</span></span>
              </div>))}
          </Widget>
          <Widget title="Weakest tones" to="/stats/tones" allLabel="all tones" empty="No tones yet.">
            {weakest.tones.map((t) => (
              <div key={`${t.kind}-${t.key}`} className="flex items-center gap-3">
                <span className="text-sm text-fg">{t.label}</span>
                <span className="ml-auto flex items-center gap-2"><Bar value={t.mean} /><span className="text-sm text-fg w-8 text-right">{pct(t.mean)}</span></span>
              </div>))}
          </Widget>
          <Widget title="Weakest sounds" to="/stats/sounds" allLabel="all sounds" empty="No sounds yet.">
            {weakest.sounds.map((s) => (
              <div key={s.key} className="flex items-center gap-3">
                <span className="text-sm text-fg">{s.label}</span>
                <span className="text-xs text-fgdim">{`${s.slips} of ${s.chances}`}</span>
                <span className="ml-auto"><Bar value={s.rate} /></span>
              </div>))}
          </Widget>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <Card notched className="p-5">
            <section className="space-y-2">
              <h2 className="text-fg font-semibold">Flow</h2>
              {AREAS.map(([k, title]) => (
                <Link key={k} to={`/stats/${k}?mode=flow`} className="flex items-center gap-3 hover:bg-line/20">
                  <span className="text-sm text-fgdim">{title}</span>
                  <span className="ml-auto text-fg">{scoreText(flow[k].value)}</span>
                  <span className="text-xs text-fgdim w-10 text-right">{changeText(flow[k])}</span>
                </Link>))}
            </section>
          </Card>
          <Widget title="Activity" to="/stats/activity" allLabel="activity" empty="">
            <p className="text-sm text-fg">{`${Math.round(activity.minutes)} min · ${activity.takes} takes · ${activity.days} of 7 days`}</p>
          </Widget>
          <Widget title="Sentences to revisit" to="/stats/sentences" allLabel="all sentences" empty="No sentences yet.">
            {sentences.map((s) => (
              <button key={s.segment_id} type="button" onClick={() => nav(`/practice/${s.lesson_id}?idx=${s.idx}`)}
                className="flex items-center gap-3 w-full text-left hover:bg-line/20">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-fg">{s.text}</span>
                  <span className="block truncate text-xs text-fgdim">{s.lesson_title}</span>
                </span>
                <span className="text-sm text-fg">{pct(s.last)}</span>
              </button>))}
          </Widget>
          <Widget title="Drills" to="/stats/drills" allLabel="all drills" empty="No drills yet.">
            {drills.map((d) => <p key={d.id} className="text-sm text-fg">{`${d.label} ${pct(d.first_mean)} → ${pct(d.best_mean)}`}</p>)}
          </Widget>
        </div>
      </>
    )
  }
  return (
    <Shell>
      <main className="max-w-4xl mx-auto p-6 space-y-4">
        <h1 className="text-2xl text-fg">Stats</h1>
        {body}
      </main>
    </Shell>
  )
}
