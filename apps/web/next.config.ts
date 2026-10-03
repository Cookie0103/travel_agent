/** Same-origin proxy keeps credentials on the backend; it is fixed to local development. */
import type { NextConfig } from "next";
const config: NextConfig = {
  async rewrites() {
    return [
      { source: "/api/:path*", destination: "http://127.0.0.1:8000/:path*" },
    ];
  },
};
export default config;
