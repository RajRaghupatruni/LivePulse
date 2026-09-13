import { useState } from 'react'
import { ArrowUpRight, Check, ExternalLink } from 'lucide-react'
import { externalTargetUrl, saveExternalTargetUrl } from '../../lib/platform'

type ConfigurableTarget = 'portfolio' | 'strata'

export function LaunchDestinationSettings() {
  const [values, setValues] = useState<Record<ConfigurableTarget, string>>({
    portfolio: externalTargetUrl('portfolio') ?? '',
    strata: externalTargetUrl('strata') ?? '',
  })
  const [messages, setMessages] = useState<Partial<Record<ConfigurableTarget, string>>>({})
  const save = (target: ConfigurableTarget) => {
    const valid = saveExternalTargetUrl(target, values[target])
    setMessages((current) => ({ ...current, [target]: valid ? values[target].trim() ? 'Saved for this LivePulse profile' : 'Removed from Quick Launch' : 'Enter a valid HTTP(S) URL' }))
  }
  return <section className="launch-settings" aria-labelledby="launch-settings-title">
    <header><span className="surface-overline">EXTERNAL DESTINATIONS</span><h3 id="launch-settings-title">Quick Launch</h3><p>Portfolio and Strata appear in the launcher only after you add their URLs.</p></header>
    {(['portfolio', 'strata'] as const).map((target) => <form className="launch-setting-row" key={target} onSubmit={(event) => { event.preventDefault(); save(target) }}>
      <label htmlFor={`launch-${target}`}><ExternalLink size={15} aria-hidden="true" /><span>{target === 'portfolio' ? 'Portfolio' : 'Strata'}</span></label>
      <input id={`launch-${target}`} type="url" inputMode="url" placeholder="https://" value={values[target]} onChange={(event) => setValues((current) => ({ ...current, [target]: event.target.value }))} />
      <button type="submit"><Check size={13} /> Save</button>
      {messages[target] && <small role="status">{messages[target]}</small>}
    </form>)}
    <footer><ArrowUpRight size={13} /> Destinations open through the active platform service.</footer>
  </section>
}
