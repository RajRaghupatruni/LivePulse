export type WeatherTimeOfDay = 'dawn' | 'day' | 'dusk' | 'night'

export function weatherTimeOfDay(timezone: string | null | undefined, now = new Date()): WeatherTimeOfDay {
  let hour = now.getHours()
  if (timezone) {
    try {
      const localHour = new Intl.DateTimeFormat('en-US', {
        timeZone: timezone,
        hour: '2-digit',
        hourCycle: 'h23',
      }).formatToParts(now).find((part) => part.type === 'hour')?.value
      if (localHour !== undefined) hour = Number(localHour)
    } catch {
      // An unavailable IANA timezone falls back to the user's system clock.
    }
  }
  if (hour >= 6 && hour < 10) return 'dawn'
  if (hour >= 10 && hour < 17) return 'day'
  if (hour >= 17 && hour < 20) return 'dusk'
  return 'night'
}

export function weatherAtmosphere(category: string | undefined): string {
  if (category === 'drizzle' || category === 'rain' || category === 'snow' || category === 'fog' || category === 'thunderstorm') {
    return category
  }
  if (category === 'cloudy') return 'cloudy'
  if (category === 'clear') return 'clear'
  return ''
}
