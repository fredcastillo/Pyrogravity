import { OrbitControls } from '@react-three/drei'
import { Canvas, useFrame } from '@react-three/fiber'
import { AdditiveBlending, Color, type Group, type Points, type ShaderMaterial } from 'three'
import { useMemo, useRef, useState } from 'react'
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

function ExperimentProbe({ experiment, active, onSelect }: { experiment: Experiment; active: boolean; onSelect: () => void }) {
  const [hovered, setHovered] = useState(false)
  const position: [number, number, number] = [experiment.position[0] * 0.72, experiment.position[1] * 0.62, experiment.position[2] * 0.45]
  return (
    <group position={position}>
      <mesh onClick={(event) => { event.stopPropagation(); onSelect() }} onPointerOver={(event) => { event.stopPropagation(); setHovered(true); document.body.style.cursor = 'pointer' }} onPointerOut={() => { setHovered(false); document.body.style.cursor = 'default' }} scale={active || hovered ? 1.25 : 1}>
        <octahedronGeometry args={[0.16, 0]} />
        <meshStandardMaterial color={experiment.color} emissive={experiment.color} emissiveIntensity={active ? 4 : 2} roughness={0.18} metalness={0.5} />
      </mesh>
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[active ? 0.32 : 0.24, 0.008, 6, 48]} />
        <meshBasicMaterial color={experiment.color} transparent opacity={active ? 0.75 : 0.25} />
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
      <ambientLight intensity={0.35} />
      <pointLight position={[-2, 2, 3]} intensity={24} color="#ff742f" />
      <pointLight position={[2, -1, 2]} intensity={14} color="#25bfff" />
      <group ref={rig} position={[-0.15, 0, 0]}>
        <FlameLayer scale={1.23} hot="#ffb02e" cool="#ee391f" opacity={0.82} speed={1} turbulence={1.1} />
        <FlameLayer scale={0.92} hot="#fff0aa" cool="#1598ff" opacity={0.68} speed={1.35} turbulence={1.7} />
        <FlameLayer scale={0.55} hot="#ffffff" cool="#3fd7ff" opacity={0.7} speed={1.8} turbulence={2.2} />
        <Embers />
        <mesh><sphereGeometry args={[2.3, 64, 64]} /><meshPhysicalMaterial color="#8bd9ff" transparent opacity={0.045} roughness={0.05} metalness={0.05} transmission={0.78} thickness={0.15} depthWrite={false} /></mesh>
        <mesh rotation={[Math.PI / 2.25, 0.08, 0]}><torusGeometry args={[2.52, 0.025, 8, 150]} /><meshBasicMaterial color="#48cfff" transparent opacity={0.2} /></mesh>
        <mesh rotation={[Math.PI / 2.25, 0.08, 0]}><torusGeometry args={[2.68, 0.008, 6, 150]} /><meshBasicMaterial color="#ff7a35" transparent opacity={0.34} /></mesh>
        {experiments.map((experiment) => <ExperimentProbe key={experiment.id} experiment={experiment} active={experiment.id === selectedId} onSelect={() => onSelect(experiment.id)} />)}
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
