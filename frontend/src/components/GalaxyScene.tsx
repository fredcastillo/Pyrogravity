import { OrbitControls, Stars } from '@react-three/drei'
import { Canvas, useFrame } from '@react-three/fiber'
import { useRef, useState } from 'react'
import type { Group, Mesh } from 'three'
import type { Experiment } from '../types'

interface GalaxySceneProps {
  experiments: Experiment[]
  selectedId: string
  onSelect: (id: string) => void
}

function ExperimentNode({ experiment, active, onSelect }: { experiment: Experiment; active: boolean; onSelect: () => void }) {
  const mesh = useRef<Mesh>(null)
  const [hovered, setHovered] = useState(false)
  useFrame(({ clock }) => {
    if (mesh.current) {
      mesh.current.rotation.y = clock.elapsedTime * 0.2
      const scale = (active ? 1.24 : 1) + Math.sin(clock.elapsedTime * 1.8 + experiment.position[0]) * 0.035
      mesh.current.scale.setScalar(scale)
    }
  })
  return (
    <group position={experiment.position}>
      <mesh
        ref={mesh}
        onClick={(event) => { event.stopPropagation(); onSelect() }}
        onPointerOver={(event) => { event.stopPropagation(); setHovered(true); document.body.style.cursor = 'pointer' }}
        onPointerOut={() => { setHovered(false); document.body.style.cursor = 'default' }}
      >
        <icosahedronGeometry args={[active ? 0.34 : 0.25, 2]} />
        <meshStandardMaterial color={experiment.color} emissive={experiment.color} emissiveIntensity={active || hovered ? 2.4 : 1.15} roughness={0.28} />
      </mesh>
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[active ? 0.55 : 0.4, 0.012, 8, 80]} />
        <meshBasicMaterial color={experiment.color} transparent opacity={active ? 0.72 : 0.24} />
      </mesh>
    </group>
  )
}

function Galaxy({ experiments, selectedId, onSelect }: GalaxySceneProps) {
  const group = useRef<Group>(null)
  useFrame(({ clock }) => {
    if (group.current) group.current.rotation.y = Math.sin(clock.elapsedTime * 0.08) * 0.08
  })
  return (
    <>
      <ambientLight intensity={0.25} />
      <pointLight position={[0, 0, 2]} intensity={18} color="#ff8b47" />
      <pointLight position={[-4, 3, -1]} intensity={12} color="#38cbff" />
      <Stars radius={42} depth={20} count={1600} factor={2.5} saturation={0.35} fade speed={0.3} />
      <group ref={group}>
        <mesh>
          <sphereGeometry args={[0.72, 32, 32]} />
          <meshStandardMaterial color="#ffb35a" emissive="#ff6a2b" emissiveIntensity={2.4} roughness={0.7} />
        </mesh>
        <mesh rotation={[Math.PI / 2.15, 0, 0]}>
          <torusGeometry args={[1.2, 0.018, 8, 120]} />
          <meshBasicMaterial color="#ff944d" transparent opacity={0.24} />
        </mesh>
        {experiments.map((experiment) => (
          <ExperimentNode key={experiment.id} experiment={experiment} active={experiment.id === selectedId} onSelect={() => onSelect(experiment.id)} />
        ))}
      </group>
      <OrbitControls enablePan={false} minDistance={5.5} maxDistance={10} autoRotate autoRotateSpeed={0.22} />
    </>
  )
}

export function GalaxyScene(props: GalaxySceneProps) {
  return (
    <div className="galaxy-canvas" aria-label="Mapa tridimensional interactivo de investigaciones">
      <Canvas camera={{ position: [0, 0.5, 7.2], fov: 48 }} dpr={[1, 1.6]} gl={{ antialias: true }}>
        <Galaxy {...props} />
      </Canvas>
      <div className="galaxy-canvas__hint">Arrastra para orbitar · rueda para acercar</div>
    </div>
  )
}
