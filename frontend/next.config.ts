import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone", // the Docker image runs .next/standalone/server.js without node_modules
};

export default nextConfig;
