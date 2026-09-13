import { useEffect, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Disc3, Headphones, Pause, Play, SkipBack, SkipForward, Speaker } from 'lucide-react'
import { executeSpotifyCommand, getSpotifyDevices, type SpotifyCommand } from '../../lib/api'
import { beginAuthorization } from '../../lib/platform'
import type { ProviderHealth, SpotifyDevice, SpotifyPlaybackView } from '../../types/livepulse'
import type { SurfaceSnapshot } from '../../hooks/useProviderSurfaces'

function usePlaybackProgress(snapshot: SpotifyPlaybackView | null) {
  const [elapsed, setElapsed] = useState(snapshot?.playback?.progress_ms ?? 0)
  const observedAt = snapshot?.observed_at
  const progressMs = snapshot?.playback?.progress_ms
  const durationMs = snapshot?.playback?.duration_ms
  const isPlaying = snapshot?.playback?.is_playing
  useEffect(() => {
    const initial = progressMs ?? 0
    const observed = observedAt ? Date.parse(observedAt) : Date.now()
    const starting = Math.min(durationMs ?? Infinity, initial + (isPlaying ? Math.max(0, Date.now() - observed) : 0))
    setElapsed(starting)
    if (!isPlaying) return
    const timer = window.setInterval(() => setElapsed(Math.min(durationMs ?? Infinity, initial + Math.max(0, Date.now() - observed))), 1000)
    return () => window.clearInterval(timer)
  }, [observedAt, progressMs, durationMs, isPlaying])
  return elapsed
}

function formatTime(ms: number) {
  const total = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

function trustedArtwork(value: string | null | undefined) {
  if (!value) return null
  try {
    const url = new URL(value)
    if (url.protocol !== 'https:' || !(url.hostname.endsWith('.scdn.co') || url.hostname.endsWith('.spotifycdn.com'))) return null
    return url.href
  } catch { return null }
}

export function SpotifyCapsule({ snapshot, provider }: { snapshot: SurfaceSnapshot<SpotifyPlaybackView>; provider?: ProviderHealth }) {
  const playbackView = snapshot.value?.playback
  const elapsed = usePlaybackProgress(snapshot.value)
  const reduceMotion = useReducedMotion()
  const [pending, setPending] = useState<SpotifyCommand | null>(null)
  const [message, setMessage] = useState('')
  const [devices, setDevices] = useState<SpotifyDevice[]>([])
  const [deviceMenu, setDeviceMenu] = useState(false)
  const [devicesLoading, setDevicesLoading] = useState(false)
  useEffect(() => {
    const url = new URL(window.location.href)
    const result = url.searchParams.get('spotify')
    if (result === 'connected') {
      setMessage('Spotify connected')
    } else if (result === 'error') {
      const reason = url.searchParams.get('reason')
      setMessage(reason === 'authorization_denied'
        ? 'Spotify authorization was denied. You can try connecting again.'
        : reason === 'state_invalid'
          ? 'Spotify authorization could not be verified. Please start again.'
          : reason === 'authorization_incomplete'
            ? 'Spotify authorization was incomplete. Please try again.'
            : 'Spotify connection could not be completed. Please try again.')
    } else {
      return
    }
    url.searchParams.delete('spotify')
    url.searchParams.delete('reason')
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
  }, [])
  const duration = playbackView?.duration_ms ?? 0
  const progress = duration > 0 ? Math.min(100, elapsed / duration * 100) : 0
  const artists = playbackView?.artists?.join(', ')
  const artworkUrl = trustedArtwork(playbackView?.artwork_url)
  const command = async (action: SpotifyCommand, deviceId?: string) => {
    setPending(action)
    setMessage('')
    try {
      const result = await executeSpotifyCommand(action, deviceId ? { device_id: deviceId } : undefined)
      setMessage(result.success ? action === 'spotify.transfer_device' ? 'Playback moved to selected device' : 'Playback command sent' : result.message || 'Spotify could not complete that command')
      window.dispatchEvent(new CustomEvent('livepulse:refresh-provider-surfaces', { detail: 'spotify' }))
    } catch {
      setMessage('Spotify is not available right now')
    } finally {
      window.setTimeout(() => setPending(null), 300)
    }
  }
  const openDevices = async () => {
    if (deviceMenu) { setDeviceMenu(false); return }
    setDeviceMenu(true)
    setDevicesLoading(true)
    try { setDevices(await getSpotifyDevices()) } catch { setDevices([]); setMessage('Spotify devices could not be loaded') } finally { setDevicesLoading(false) }
  }
  const commandBlocked = ['disconnected', 'auth_failure', 'provider_failure', 'unavailable', 'rate_limited'].includes(provider?.status ?? '')
  const available = Boolean(snapshot.available && playbackView && provider?.configured !== false && !commandBlocked)
  const canInspectDevices = Boolean(provider?.configured && !commandBlocked)
  const providerLabel = provider?.configured === false ? 'NOT CONFIGURED'
    : provider?.status === 'disconnected' ? 'DISCONNECTED'
      : provider?.status === 'stale' ? 'STALE'
        : provider?.status === 'auth_failure' ? 'RECONNECT REQUIRED'
          : provider?.status === 'rate_limited' ? 'RATE LIMITED'
            : provider?.status === 'provider_failure' || provider?.status === 'unavailable' || provider?.status === 'degraded' ? 'UNAVAILABLE'
              : provider?.status === 'connecting' || provider?.status === 'unknown' ? 'CONNECTING'
                : playbackView?.is_playing ? 'PLAYING' : playbackView ? 'PAUSED' : snapshot.loading ? 'CONNECTING' : snapshot.available ? 'READY' : 'UNAVAILABLE'
  const title = playbackView?.item_name ?? (snapshot.loading ? 'Connecting to Spotify' : provider?.configured === false ? 'Spotify is not configured' : snapshot.available ? 'Nothing is playing' : 'Spotify is unavailable')
  const subtitle = playbackView ? [artists, playbackView.album_name ?? playbackView.show_name].filter(Boolean).join(' · ') : snapshot.loading ? 'Resolving playback state' : provider?.configured === false ? 'Local Spotify OAuth setup is required to enable playback' : snapshot.available ? 'No active playback on the connected account' : 'Playback state is unavailable'
  const accentStyle = artworkUrl ? { '--album-artwork': `url("${artworkUrl}")` } as React.CSSProperties : undefined

  return <section className={`spotify-capsule${playbackView?.is_playing ? ' spotify-playing' : ''}`} aria-label="Spotify playback" id="spotify" style={accentStyle}>
    <div className="spotify-artwork" aria-hidden="true">{artworkUrl ? <img src={artworkUrl} alt="" loading="lazy" referrerPolicy="no-referrer" /> : <Disc3 size={26} strokeWidth={1.4} />}<i /></div>
    <AnimatePresence mode="wait" initial={false}>
      <motion.div className="spotify-copy" key={playbackView?.item_id ?? title} initial={reduceMotion ? false : { opacity: .65, y: 3 }} animate={{ opacity: 1, y: 0 }} exit={reduceMotion ? undefined : { opacity: 0, y: -2 }} transition={{ duration: reduceMotion ? 0 : .22 }}>
        <div className="spotify-topline"><span>LISTENING</span><span className={`play-state${playbackView?.is_playing && providerLabel === 'PLAYING' ? ' is-playing' : ''}`}>{providerLabel}</span></div>
        <strong title={title}>{title}</strong><span title={subtitle}>{subtitle || 'Playback state unavailable'}</span>
        {provider?.configured && ['disconnected', 'auth_failure'].includes(provider.status) && <button className="spotify-connect" type="button" onClick={() => void beginAuthorization('/api/v1/providers/spotify/oauth/start')}>Connect Spotify</button>}
        <div className="spotify-progress"><div role="progressbar" aria-label="Track progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress)}><i style={{ width: `${progress}%` }} /></div><small>{playbackView ? `${formatTime(elapsed)} / ${formatTime(duration)}` : provider?.configured === false ? 'Not configured' : snapshot.available ? 'No active track' : '—'}</small></div>
        {message && <span className="spotify-feedback" role="status">{message}</span>}
      </motion.div>
    </AnimatePresence>
    <div className="spotify-device-container"><button className="spotify-device" type="button" onClick={() => void openDevices()} disabled={!canInspectDevices} aria-label={`Playback device: ${playbackView?.device_name ?? 'No active device'}`} aria-expanded={deviceMenu}><Speaker size={15} aria-hidden="true" /><span>{playbackView?.device_name ?? (provider?.configured === false ? 'Not configured' : snapshot.available ? 'No active device' : 'Spotify')}</span><i>⌄</i></button>{deviceMenu && <div className="spotify-device-menu" role="listbox" aria-label="Spotify Connect devices">{devicesLoading ? <span>Checking devices…</span> : devices.length ? devices.map((device) => <button type="button" key={device.id ?? device.name} role="option" aria-selected={Boolean(device.is_active)} disabled={!device.id || device.is_restricted || pending !== null} onClick={() => { if (device.id) void command('spotify.transfer_device', device.id); setDeviceMenu(false) }}><span>{device.name}</span><small>{device.is_active ? 'ACTIVE' : device.type}</small></button>) : <span>No available Spotify Connect devices</span>}</div>}</div>
    <div className="spotify-controls" aria-label="Playback controls"><button type="button" aria-label="Previous track" disabled={!available || pending !== null} onClick={() => void command('spotify.previous')}><SkipBack size={15} fill="currentColor" /></button><button className="spotify-play-toggle" type="button" aria-label={playbackView?.is_playing ? 'Pause playback' : 'Start playback'} disabled={!available || pending !== null} onClick={() => void command(playbackView?.is_playing ? 'spotify.pause' : 'spotify.play')}>{playbackView?.is_playing ? <Pause size={16} fill="currentColor" /> : <Play size={16} fill="currentColor" />}</button><button type="button" aria-label="Next track" disabled={!available || pending !== null} onClick={() => void command('spotify.next')}><SkipForward size={15} fill="currentColor" /></button></div>
    <span className="spotify-headphones" aria-hidden="true"><Headphones size={14} /></span>
  </section>
}
