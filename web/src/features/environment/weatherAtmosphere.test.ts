import { describe, expect, it } from 'vitest'
import { weatherAtmosphere, weatherTimeOfDay } from './weatherAtmosphere'

describe('selected-location atmosphere', () => {
  it('uses the selected place timezone rather than the computer clock timezone', () => {
    const instant = new Date('2026-09-13T16:00:00.000Z')
    expect(weatherTimeOfDay('America/Chicago', instant)).toBe('day')
    expect(weatherTimeOfDay('Asia/Tokyo', instant)).toBe('night')
  })

  it('falls back to system local time when there is no selected timezone', () => {
    const instant = new Date(2026, 8, 13, 12, 0)
    expect(weatherTimeOfDay(null, instant)).toBe('day')
    expect(weatherTimeOfDay('Invalid/Timezone', instant)).toBe('day')
  })

  it('maps only observed weather categories into restrained atmosphere tones', () => {
    expect(weatherAtmosphere('clear')).toBe('clear')
    expect(weatherAtmosphere('rain')).toBe('rain')
    expect(weatherAtmosphere('fog')).toBe('fog')
    expect(weatherAtmosphere('thunderstorm')).toBe('thunderstorm')
    expect(weatherAtmosphere('unknown')).toBe('')
  })
})
