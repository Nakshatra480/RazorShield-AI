/** @type {import('next').NextConfig} */
const nextConfig = {
  // Allow Three.js / R3F to work in Next.js
  transpilePackages: ["three", "@react-three/fiber", "@react-three/drei"],
  webpack: (config) => {
    // Ensure Three.js shaders are handled
    config.module.rules.push({
      test: /\.(glsl|vs|fs|vert|frag)$/,
      exclude: /node_modules/,
      use: ["raw-loader"],
    });
    return config;
  },
};

export default nextConfig;
