import { concat, downsample, encodeWav16, sliceSamples, tail } from './pcm'

const WORKLET_URL = `${import.meta.env.BASE_URL}worklets/pcm-capture.js`

export class Recorder {
  private ctx: AudioContext
  private chunks: Float32Array[] = []
  private node: AudioWorkletNode | null = null
  private src: MediaStreamAudioSourceNode | null = null
  private stream: MediaStream | null = null
  private _start = 0
  private loaded = false
  constructor(ctx: AudioContext) { this.ctx = ctx }
  get sampleRate() { return this.ctx.sampleRate }
  get startTime() { return this._start }

  async start() {
    if (this.node) throw new Error('Recorder already started')
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('Microphone is not available in this browser')
    if (this.ctx.state === 'suspended') await this.ctx.resume()
    if (!this.loaded) { await this.ctx.audioWorklet.addModule(WORKLET_URL); this.loaded = true }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } })
    } catch (e) {
      throw new Error(micErrorMessage(e))
    }
    try {
      this.src = this.ctx.createMediaStreamSource(this.stream)
      this.node = new AudioWorkletNode(this.ctx, 'pcm-capture')
      this.chunks = []
      this._start = 0
      this.node.port.onmessage = (e) => {
        const chunk = e.data as Float32Array
        if (!this._start) this._start = this.ctx.currentTime - chunk.length / this.ctx.sampleRate
        this.chunks.push(chunk)
      }
      this.src.connect(this.node)
    } catch (e) {
      this.release()
      throw e
    }
  }
  snapshot(): Float32Array { return concat(this.chunks) }
  stop(): Float32Array {
    this.release()
    return this.snapshot()
  }
  slice(t0: number, t1: number): Float32Array { return sliceSamples(this.snapshot(), this._start, this.ctx.sampleRate, t0, t1) }
  // The most recent n samples, cheap enough for the live waveform on a long recording.
  tail(n: number): Float32Array { return tail(this.chunks, n) }

  private release() {
    if (this.node) this.node.port.onmessage = null
    this.src?.disconnect(); this.node?.disconnect(); this.stream?.getTracks().forEach((t) => t.stop())
    this.src = this.node = this.stream = null
  }
}

function micErrorMessage(e: unknown): string {
  const name = e instanceof DOMException ? e.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'Microphone permission was denied'
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'No microphone was found'
  if (name === 'NotReadableError') return 'The microphone is in use by another application'
  return e instanceof Error && e.message ? `Could not open the microphone: ${e.message}` : 'Could not open the microphone'
}

export const toWav16k = (samples: Float32Array, sr: number) => encodeWav16(downsample(samples, sr, 16000), 16000)
