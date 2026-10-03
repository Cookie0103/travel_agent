/** Same-origin proxy has only the native and isolated Compose destinations. */
import type { NextConfig } from "next";
const apiOrigin = process.env.TRAVEL_API_ORIGIN ?? "http://127.0.0.1:8000";
if (!["http://127.0.0.1:8000", "http://api:8000"].includes(apiOrigin)) {
  throw new Error("TRAVEL_API_ORIGIN must be the local or Compose API");
}
const config: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/:path*` }];
  },
};
export default config;
