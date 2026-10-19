/** Same-origin proxy supports local, Compose and Railway private API destinations. */
import type { NextConfig } from "next";
const apiOrigin = process.env.TRAVEL_API_ORIGIN ?? "http://127.0.0.1:8000";
if (
  !["http://127.0.0.1:8000", "http://api:8000"].includes(apiOrigin) &&
  !/^http:\/\/[a-z0-9-]+\.railway\.internal:[0-9]+$/.test(apiOrigin)
) {
  throw new Error(
    "TRAVEL_API_ORIGIN must be a local, Compose or Railway private API",
  );
}
const config: NextConfig = {
  output: "standalone",
  // rewrites 代理默认 30s 无响应就断开（socket hang up）；放宽到 2 分钟，
  // 慢读取不再被代理截断。SSE 另有 5s 心跳，断线由前端按游标重连兜底。
  experimental: { proxyTimeout: 120_000 },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/:path*` }];
  },
};
export default config;
