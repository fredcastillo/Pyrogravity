import { OrbitControls } from '@react-three/drei'
import { Canvas, useFrame } from '@react-three/fiber'
import { AdditiveBlending, Color, IcosahedronGeometry, Vector3, type Group, type Points, type ShaderMaterial } from 'three'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { Experiment } from '../types'

interface GalaxySceneProps {
  experiments: Experiment[]
  selectedId: string
  onSelect: (id: string) => void
}

const flameVertex = `
  uniform float uTime;
  uniform float uTurbulence;
  varying vec2 vUv;
  varying vec3 vNormal;
  varying float vPulse;
  void main() {
    vUv = uv;
    vNormal = normalize(normalMatrix * normal);
    vec3 p = position;
    float wave = sin((p.x * 5.2) + uTime * 1.7) * 0.045;
    wave += sin((p.y * 6.6) - uTime * 2.1) * 0.035;
    wave += sin((p.z * 8.4) + uTime * 1.35) * 0.025;
    vPulse = wave;
    p += normal * wave * uTurbulence;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  }
`

const flameFragment = `
  uniform float uTime;
  uniform vec3 uHot;
  uniform vec3 uCool;
  uniform float uOpacity;
  varying vec2 vUv;
  varying vec3 vNormal;
  varying float vPulse;
  void main() {
    float fresnel = pow(1.0 - abs(dot(vNormal, vec3(0.0, 0.0, 1.0))), 2.1);
    float veins = sin(vUv.y * 24.0 + vUv.x * 13.0 - uTime * 2.5 + vPulse * 55.0);
    veins = smoothstep(0.15, 0.95, veins);
    vec3 color = mix(uCool, uHot, clamp(fresnel + veins * 0.42, 0.0, 1.0));
    float alpha = (0.24 + fresnel * 0.65 + veins * 0.18) * uOpacity;
    gl_FragColor = vec4(color, alpha);
  }
`

function FlameLayer({ scale, hot, cool, opacity, speed, turbulence }: { scale: number; hot: string; cool: string; opacity: number; speed: number; turbulence: number }) {
  const material = useRef<ShaderMaterial>(null)
  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uHot: { value: new Color(hot) },
    uCool: { value: new Color(cool) },
    uOpacity: { value: opacity },
    uTurbulence: { value: turbulence },
  }), [hot, cool, opacity, turbulence])

  useFrame(({ clock }) => {
    if (material.current) material.current.uniforms.uTime.value = clock.elapsedTime * speed
  })

  return (
    <mesh scale={[scale * 1.08, scale, scale * 0.94]} rotation={[0.12, 0, -0.2]}>
      <icosahedronGeometry args={[1, 7]} />
      <shaderMaterial ref={material} uniforms={uniforms} vertexShader={flameVertex} fragmentShader={flameFragment} transparent depthWrite={false} blending={AdditiveBlending} />
    </mesh>
  )
}

function Embers() {
  const points = useRef<Points>(null)
  const positions = useMemo(() => {
    const values = new Float32Array(270)
    for (let index = 0; index < 90; index += 1) {
      const angle = index * 2.39996
      const radius = 1.4 + ((index * 17) % 31) / 18
      values[index * 3] = Math.cos(angle) * radius
      values[index * 3 + 1] = Math.sin(angle * 1.3) * radius * 0.68
      values[index * 3 + 2] = Math.sin(angle) * radius * 0.55
    }
    return values
  }, [])

  useFrame(({ clock }) => {
    if (points.current) {
      points.current.rotation.y = clock.elapsedTime * 0.045
      points.current.rotation.z = Math.sin(clock.elapsedTime * 0.2) * 0.08
    }
  })

  return (
    <points ref={points}>
      <bufferGeometry><bufferAttribute attach="attributes-position" args={[positions, 3]} /></bufferGeometry>
      <pointsMaterial color="#ff9a42" size={0.035} transparent opacity={0.68} sizeAttenuation depthWrite={false} blending={AdditiveBlending} />
    </points>
  )
}

function ExperimentMeteorite({ experiment, index, active, onSelect }: { experiment: Experiment; index: number; active: boolean; onSelect: () => void }) {
  const group = useRef<Group>(null)
  const [hovered, setHovered] = useState(false)
  const seed = index + 1
  const rockColor = ['#3a332e', '#4b4540', '#302d2a', '#53483f', '#393a3b'][index % 5]
  const geometry = useMemo(() => {
    const shape = new IcosahedronGeometry(0.23 + (seed % 3) * 0.035, 4)
    const position = shape.attributes.position
    const vector = new Vector3()
    for (let vertex = 0; vertex < position.count; vertex += 1) {
      vector.fromBufferAttribute(position, vertex)
      const noise = Math.sin(vector.x * 19 + seed * 4.7) * Math.cos(vector.y * 17 - seed) * Math.sin(vector.z * 23 + seed * 2.3)
      const baseLength = vector.length()
      vector.normalize().multiplyScalar(baseLength + noise * 0.045)
      position.setXYZ(vertex, vector.x, vector.y, vector.z)
    }
    position.needsUpdate = true
    shape.computeVertexNormals()
    return shape
  }, [seed])

  useEffect(() => () => geometry.dispose(), [geometry])

  useFrame(({ clock, pointer }) => {
    if (!group.current) return
    const time = clock.elapsedTime * (0.09 + seed * 0.012) + seed * 1.27
    const radius = 1.62 + seed * 0.22
    group.current.position.set(
      Math.cos(time) * radius + pointer.x * 0.12,
      Math.sin(time * 1.18) * (0.85 + seed * 0.05) + pointer.y * 0.08,
      Math.sin(time) * 0.72 + (seed % 2 ? 0.18 : -0.28),
    )
    group.current.rotation.x = clock.elapsedTime * (0.11 + seed * 0.025)
    group.current.rotation.y = clock.elapsedTime * (0.16 + seed * 0.018)
    const targetScale = active ? 1.28 : hovered ? 1.16 : 1
    group.current.scale.lerp(new Vector3(targetScale, targetScale, targetScale), 0.08)
  })

  return (
    <group ref={group}>
      <mesh geometry={geometry} onClick={(event) => { event.stopPropagation(); onSelect() }} onPointerOver={(event) => { event.stopPropagation(); setHovered(true); document.body.style.cursor = 'pointer' }} onPointerOut={() => { setHovered(false); document.body.style.cursor = 'default' }} castShadow>
        <meshStandardMaterial color={active ? '#62564d' : rockColor} emissive={active ? '#39150a' : '#030303'} emissiveIntensity={active ? 0.2 : hovered ? 0.08 : 0.02} roughness={0.98} metalness={0.04} />
      </mesh>
      <mesh position={[0.08, 0.04, 0.2]} scale={[1, 0.7, 0.24]}>
        <sphereGeometry args={[0.065, 14, 10]} />
        <meshStandardMaterial color="#17191a" roughness={1} />
      </mesh>
      <mesh position={[-0.1, -0.07, 0.18]} scale={[1, 0.78, 0.2]}>
        <sphereGeometry args={[0.045, 12, 8]} />
        <meshStandardMaterial color="#202122" roughness={1} />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.31, 24, 24]} />
        <meshBasicMaterial color={experiment.color} transparent opacity={active ? 0.12 : hovered ? 0.075 : 0.025} depthWrite={false} blending={AdditiveBlending} />
      </mesh>
    </group>
  )
}

function CombustionChamber({ experiments, selectedId, onSelect }: GalaxySceneProps) {
  const rig = useRef<Group>(null)
  useFrame(({ clock }) => {
    if (rig.current) rig.current.rotation.y = Math.sin(clock.elapsedTime * 0.12) * 0.12
  })
  return (
    <>
      <ambientLight intensity={0.48} />
      <hemisphereLight args={['#9bdcff', '#24140d', 0.8]} />
      <pointLight position={[-2, 2, 3]} intensity={9} color="#ff742f" />
      <pointLight position={[2, -1, 2]} intensity={6} color="#25bfff" />
      <group ref={rig} position={[-0.15, 0, 0]}>
        <FlameLayer scale={1.23} hot="#ffb02e" cool="#ee391f" opacity={0.82} speed={1} turbulence={1.1} />
        <FlameLayer scale={0.92} hot="#fff0aa" cool="#1598ff" opacity={0.68} speed={1.35} turbulence={1.7} />
        <FlameLayer scale={0.55} hot="#ffffff" cool="#3fd7ff" opacity={0.7} speed={1.8} turbulence={2.2} />
        <Embers />
        <mesh><sphereGeometry args={[2.3, 64, 64]} /><meshPhysicalMaterial color="#8bd9ff" transparent opacity={0.045} roughness={0.05} metalness={0.05} transmission={0.78} thickness={0.15} depthWrite={false} /></mesh>
        <mesh rotation={[Math.PI / 2.25, 0.08, 0]}><torusGeometry args={[2.52, 0.025, 8, 150]} /><meshBasicMaterial color="#48cfff" transparent opacity={0.2} /></mesh>
        <mesh rotation={[Math.PI / 2.25, 0.08, 0]}><torusGeometry args={[2.68, 0.008, 6, 150]} /><meshBasicMaterial color="#ff7a35" transparent opacity={0.34} /></mesh>
        {experiments.map((experiment, index) => <ExperimentMeteorite key={experiment.id} experiment={experiment} index={index} active={experiment.id === selectedId} onSelect={() => onSelect(experiment.id)} />)}
      </group>
      <OrbitControls enablePan={false} minDistance={5.6} maxDistance={9} autoRotate autoRotateSpeed={0.16} />
    </>
  )
}

export function GalaxyScene(props: GalaxySceneProps) {
  return (
    <div className="galaxy-canvas combustion-canvas" aria-label="Cámara tridimensional interactiva de combustión en microgravedad">
      <Canvas camera={{ position: [0, 0.2, 7], fov: 47 }} dpr={[1, 1.45]} gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}>
        <CombustionChamber {...props} />
      </Canvas>
      <div className="combustion-readout"><span>LIVE VOLUME</span><b>4D FLOW / 120 FPS</b></div>
      <div className="galaxy-canvas__hint">Arrastra para inspeccionar · selecciona una sonda</div>
    </div>
  )
}
