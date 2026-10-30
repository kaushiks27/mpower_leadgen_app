/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Standalone output → self-contained .next/standalone/server.js for Docker.
  output: "standalone",
};

export default nextConfig;
