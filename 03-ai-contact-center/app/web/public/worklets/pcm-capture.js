// AudioWorklet: captures microphone audio, resamples to 24 kHz mono PCM16 and posts 20 ms frames (480 samples) to the main thread.
class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super()
    this.ratio = sampleRate / 24000
    this.pos = 0
    this.pending = []
    this.frame = []
    this.tick = 0
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (!ch) return true
    let sumSq = 0
    for (let i = 0; i < ch.length; i++) sumSq += ch[i] * ch[i]
    // linear resampling (identity when the context already runs at 24 kHz)
    for (let i = 0; i < ch.length; i++) this.pending.push(ch[i])
    while (this.pos + 1 < this.pending.length) {
      const i0 = Math.floor(this.pos)
      const frac = this.pos - i0
      const s = this.pending[i0] * (1 - frac) + this.pending[i0 + 1] * frac
      this.frame.push(Math.max(-1, Math.min(1, s)))
      this.pos += this.ratio
      if (this.frame.length === 480) {
        const out = new Int16Array(480)
        for (let k = 0; k < 480; k++) out[k] = this.frame[k] < 0 ? this.frame[k] * 0x8000 : this.frame[k] * 0x7fff
        this.port.postMessage({ pcm: out.buffer }, [out.buffer])
        this.frame = []
      }
    }
    const drop = Math.floor(this.pos)
    if (drop > 0) {
      this.pending = this.pending.slice(drop)
      this.pos -= drop
    }
    if (++this.tick % 8 === 0) this.port.postMessage({ level: Math.sqrt(sumSq / ch.length) })
    return true
  }
}
registerProcessor('pcm-capture', PcmCapture)
