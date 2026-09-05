"use client";
import React, { useRef, useMemo } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";

function ParticleField() {
  const ref = useRef<THREE.Points>(null);
  const count = 800;

  const positions = useMemo(() => {
    const arr = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      const r = 2.2 + Math.random() * 1.8;
      arr[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      arr[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      arr[i * 3 + 2] = r * Math.cos(phi);
    }
    return arr;
  }, []);

  useFrame((_, delta) => {
    if (ref.current) {
      ref.current.rotation.y += delta * 0.04;
      ref.current.rotation.x += delta * 0.01;
    }
  });

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          count={count}
          array={positions}
          itemSize={3}
        />
      </bufferGeometry>
      <pointsMaterial
        color="#6366F1"
        size={0.022}
        transparent
        opacity={0.55}
        sizeAttenuation
      />
    </points>
  );
}

function WireframeGlobe() {
  const ref = useRef<THREE.Mesh>(null);

  useFrame((_, delta) => {
    if (ref.current) {
      ref.current.rotation.y += delta * 0.08;
    }
  });

  return (
    <mesh ref={ref}>
      <icosahedronGeometry args={[1.8, 3]} />
      <meshBasicMaterial
        color="#3B82F6"
        wireframe
        transparent
        opacity={0.12}
      />
    </mesh>
  );
}

function InnerSphere() {
  const ref = useRef<THREE.Mesh>(null);

  useFrame((_, delta) => {
    if (ref.current) {
      ref.current.rotation.y -= delta * 0.05;
      ref.current.rotation.z += delta * 0.02;
    }
  });

  return (
    <mesh ref={ref}>
      <icosahedronGeometry args={[1.2, 2]} />
      <meshBasicMaterial
        color="#6366F1"
        wireframe
        transparent
        opacity={0.07}
      />
    </mesh>
  );
}

function ScanRing() {
  const ref = useRef<THREE.Mesh>(null);

  useFrame((state) => {
    if (ref.current) {
      ref.current.rotation.z = state.clock.elapsedTime * 0.6;
      ref.current.rotation.x = Math.sin(state.clock.elapsedTime * 0.3) * 0.5;
    }
  });

  return (
    <mesh ref={ref}>
      <torusGeometry args={[2.1, 0.005, 8, 80]} />
      <meshBasicMaterial color="#3B82F6" transparent opacity={0.35} />
    </mesh>
  );
}

interface ScannerGlobeProps {
  className?: string;
}

export default function ScannerGlobe({ className = "" }: ScannerGlobeProps) {
  return (
    <div className={`w-full h-full ${className}`}>
      <Canvas
        camera={{ position: [0, 0, 5.5], fov: 50 }}
        style={{ background: "transparent" }}
        gl={{ alpha: true, antialias: true }}
      >
        <ambientLight intensity={0.4} />
        <pointLight position={[5, 5, 5]} intensity={0.8} color="#6366F1" />
        <pointLight position={[-5, -5, -5]} intensity={0.3} color="#3B82F6" />
        <WireframeGlobe />
        <InnerSphere />
        <ScanRing />
        <ParticleField />
        <OrbitControls
          enableZoom={false}
          enablePan={false}
          autoRotate
          autoRotateSpeed={0.5}
          maxPolarAngle={Math.PI}
          minPolarAngle={0}
        />
      </Canvas>
    </div>
  );
}
