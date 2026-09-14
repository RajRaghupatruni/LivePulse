import { Canvas, useFrame } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'

type Props = {
  count: number
  dpr: number
  frameLoop: 'always' | 'demand'
  reducedMotion: boolean
  weather: string
  degraded: boolean
  eventIntensity?: 'subtle' | 'moderate' | 'strong' | null
  onProfileSample: (fps: number) => void
}
type SceneProps = Omit<Props, 'dpr' | 'frameLoop'>

function seededPositions(count: number) {
  let seed = 0x4c50554c
  const random = () => {
    seed = (seed * 1664525 + 1013904223) >>> 0
    return seed / 0x1_0000_0000
  }
  const positions = new Float32Array(count * 3)
  for (let i = 0; i < count; i += 1) {
    positions[i * 3] = (random() - 0.5) * 30
    positions[i * 3 + 1] = (random() - 0.5) * 15
    positions[i * 3 + 2] = -1 - random() * 11
  }
  return positions
}

function weatherColor(weather: string) {
  if (['rain', 'drizzle', 'cloudy', 'overcast', 'fog'].includes(weather)) return '#a4bfca'
  if (weather === 'snow') return '#c0dfe5'
  if (weather === 'thunderstorm') return '#91a7b7'
  return '#75cfdd'
}

function AtmosphereScene({ count, reducedMotion, weather, degraded, eventIntensity, onProfileSample }: SceneProps) {
  const field = useRef<THREE.Group>(null)
  const points = useRef<THREE.Points>(null)
  const pointsMaterial = useRef<THREE.PointsMaterial>(null)
  const pointer = useRef(new THREE.Vector2())
  const performance = useRef({ elapsed: 0, frames: 0 })
  const geometry = useMemo(() => {
    const value = new THREE.BufferGeometry()
    value.setAttribute('position', new THREE.BufferAttribute(seededPositions(count), 3))
    return value
  }, [count])
  const networkGeometry = useMemo(() => {
    const value = new THREE.BufferGeometry()
    value.setAttribute('position', new THREE.Float32BufferAttribute([-14, 1.2, 0, -8, -0.8, -0.1, -8, -0.8, -0.1, -2.2, 0.2, -0.2, 6, 1.8, -0.35, 11, -0.5, -0.4, 11, -0.5, -0.4, 14, 0.9, -0.6], 3))
    return value
  }, [])
  const rainGeometry = useMemo(() => {
    if (weather !== 'rain' && weather !== 'drizzle' && weather !== 'thunderstorm') return null
    const seedPositions = seededPositions(30)
    const positions = new Float32Array(seedPositions.length * 2)
    for (let i = 0; i < seedPositions.length / 3; i += 1) {
      const source = i * 3
      const target = i * 6
      positions[target] = seedPositions[source]
      positions[target + 1] = seedPositions[source + 1]
      positions[target + 2] = seedPositions[source + 2]
      positions[target + 3] = seedPositions[source] + 0.075
      positions[target + 4] = seedPositions[source + 1] - 0.38
      positions[target + 5] = seedPositions[source + 2]
    }
    const value = new THREE.BufferGeometry()
    value.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    return value
  }, [weather])
  useEffect(() => () => geometry.dispose(), [geometry])
  useEffect(() => () => networkGeometry.dispose(), [networkGeometry])
  useEffect(() => () => rainGeometry?.dispose(), [rainGeometry])
  const color = degraded ? '#d1a56f' : weatherColor(weather)
  const targetOpacity = eventIntensity === 'strong' ? 0.22 : eventIntensity === 'moderate' ? 0.14 : 0.085

  useEffect(() => {
    const onPointer = (event: PointerEvent) => {
      if (event.pointerType && event.pointerType !== 'mouse') return
      pointer.current.set((event.clientX / Math.max(window.innerWidth, 1) - 0.5) * 2, (event.clientY / Math.max(window.innerHeight, 1) - 0.5) * -2)
    }
    window.addEventListener('pointermove', onPointer, { passive: true })
    return () => window.removeEventListener('pointermove', onPointer)
  }, [])

  useFrame((_, delta) => {
    if (reducedMotion) return
    const safeDelta = Math.min(delta, 0.06)
    if (field.current) {
      field.current.rotation.x = THREE.MathUtils.damp(field.current.rotation.x, pointer.current.y * 0.009, 1.2, safeDelta)
      field.current.rotation.y = THREE.MathUtils.damp(field.current.rotation.y, pointer.current.x * 0.014, 1.2, safeDelta)
    }
    if (points.current) points.current.position.y = Math.sin(performance.current.elapsed * 0.18) * 0.055
    if (pointsMaterial.current) pointsMaterial.current.opacity = THREE.MathUtils.damp(pointsMaterial.current.opacity, targetOpacity, 1.4, safeDelta)
    if (weather === 'snow' && geometry.attributes.position) {
      const positions = geometry.attributes.position.array as Float32Array
      for (let i = 0; i < positions.length; i += 3) {
        positions[i] += safeDelta * 0.012
        positions[i + 1] -= safeDelta * 0.19
        if (positions[i + 1] < -7.5) positions[i + 1] = 7.5
      }
      geometry.attributes.position.needsUpdate = true
    }
    if (rainGeometry) {
      const positions = rainGeometry.attributes.position.array as Float32Array
      for (let i = 0; i < positions.length; i += 6) {
        positions[i + 1] -= safeDelta * 2.2
        positions[i + 4] -= safeDelta * 2.2
        if (positions[i + 1] < -7.5) {
          const resetY = 7.5 + ((i * 17) % 13) * 0.12
          positions[i + 1] = resetY
          positions[i + 4] = resetY - 0.38
        }
      }
      rainGeometry.attributes.position.needsUpdate = true
    }

    performance.current.elapsed += safeDelta
    performance.current.frames += 1
    if (performance.current.elapsed >= 2.5) {
      onProfileSample(performance.current.frames / performance.current.elapsed)
      performance.current.elapsed = 0
      performance.current.frames = 0
    }
  })

  return <group ref={field}>
    <points ref={points} geometry={geometry} frustumCulled={false}>
      <pointsMaterial ref={pointsMaterial} color={color} size={1.35} sizeAttenuation transparent opacity={targetOpacity} depthWrite={false} toneMapped={false} />
    </points>
    <group rotation={[0.08, -0.12, 0.03]}>
      <lineSegments geometry={networkGeometry} position={[-1.2, 0.15, -6]}>
        <lineBasicMaterial color={color} transparent opacity={degraded ? 0.1 : 0.065} depthWrite={false} toneMapped={false} />
      </lineSegments>
    </group>
    {rainGeometry && <lineSegments geometry={rainGeometry}>
      <lineBasicMaterial color={color} transparent opacity={weather === 'thunderstorm' ? 0.12 : 0.085} depthWrite={false} toneMapped={false} />
    </lineSegments>}
  </group>
}

export function WorldCanvas({ count, dpr, frameLoop, ...sceneProps }: Props) {
  return <Canvas className="environment-world-canvas" dpr={Math.min(window.devicePixelRatio || 1, dpr)} frameloop={frameLoop} camera={{ position: [0, 0, 15], fov: 48 }} gl={{ alpha: true, antialias: false, powerPreference: 'low-power', preserveDrawingBuffer: false }} fallback={null}>
    <AtmosphereScene count={count} {...sceneProps} />
  </Canvas>
}
